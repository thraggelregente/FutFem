"""TheSportsDB V1 (key pÃºblica 123): fixtures femeninos e historial reciente, sin cuotas.

QuÃ© aporta, todo gratis y sin cuota diaria (solo el lÃ­mite de 30 requests/minuto, que esta fuente
respeta con un limitador propio):
- Fixtures: eventsday.php consultado POR LIGA (el endpoint global del plan gratuito devuelve muy pocos
  eventos). Se configuran con THESPORTSDB_WOMENS_LEAGUES, formato Soccer:ID,Basketball:ID,Volleyball:ID.
  Solo agregar IDs comprobados como competiciones femeninas. Al arrancar se consulta lookupleague.php
  para loguear el nombre de cada liga y descartar las que TheSportsDB marque como masculinas.
- Historial: eventslast.php (Ãºltimos partidos terminados de un equipo) y searchteams.php para
  resolver un equipo por nombre. Sirve como fuente de forma reciente para eventos que llegan de
  otros proveedores, sin gastar la cuota de Highlightly ni de API-Sports.

Opcionalmente THESPORTSDB_BUSQUEDA_GLOBAL=1 activa el listado global (menos completo); solo deja pasar
partidos con evidencia explÃ­cita de gÃ©nero femenino en la respuesta. No se consultan cuotas, mercados
ni bookmakers.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import libro_resultados as L
import utilidades as U

API_KEY = (os.environ.get("THESPORTSDB_KEY") or "123").strip() or "123"
BASE = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"
FUENTE = "thesportsdb"
CACHE_MINUTOS = max(10, int(os.environ.get("THESPORTSDB_CACHE_MINUTOS", "240")))
BUSQUEDA_GLOBAL = os.environ.get("THESPORTSDB_BUSQUEDA_GLOBAL", "0").strip().lower() in {"1", "true", "yes", "on"}
HISTORIAL_ACTIVO = os.environ.get("THESPORTSDB_HISTORIAL", "1").strip().lower() not in {"0", "false", "no", "off"}
EXIGIR_FEMENINO = os.environ.get("THESPORTSDB_EXIGIR_FEMENINO", "1").strip().lower() not in {"0", "false", "no", "off"}
MAX_PEDIDOS_MINUTO = max(5, min(30, int(os.environ.get("THESPORTSDB_MAX_PEDIDOS_MINUTO", "24"))))
TTL_FALLO = 5 * 60  # un error transitorio se reintenta a los 5 minutos, no tras CACHE_MINUTOS

_DEPORTES_TSDB = {
    "Soccer": "Soccer",
    "Basketball": "Basketball",
    "Handball": "Handball",
    "Ice Hockey": "Ice Hockey",
    "Volleyball": "Volleyball",
    "Rugby": "Rugby",
    "Tennis": "Tennis",
}
_GENEROS_MASCULINOS = {"male", "masculine", "men", "man", "m"}
_NO_JUGADOS = ("postp", "cancel", "abandon", "suspend", "walkover", "w.o", "not played")


def _leer_ligas():
    ligas = {}
    raw = (os.environ.get("THESPORTSDB_WOMENS_LEAGUES") or "").strip()
    for item in re.split(r"[,;\n]+", raw):
        item = item.strip()
        if not item or ":" not in item:
            continue
        deporte, league_id = (x.strip() for x in item.split(":", 1))
        if deporte in _DEPORTES_TSDB and league_id.isdigit():
            ligas.setdefault(deporte, set()).add(league_id)
    return ligas


_LIGAS_FEMENINAS = _leer_ligas()
_cache_eventos = U.CacheTTL(CACHE_MINUTOS * 60)
_cache_ligas = U.CacheTTL(24 * 3600)
_cache_busqueda = U.CachePersistente("tsdb_busqueda", 43200)
_cache_forma = U.CachePersistente("tsdb_forma", 10800)
_avisos = set()
_ultimo_aviso_sin_ligas = 0.0
_lock = threading.Lock()
_pedidos_recientes = deque()
_backoff_hasta = {"t": 0.0}


def disponible():
    """Hay fixtures que consultar: ligas allowlisteadas o bÃºsqueda global."""
    return bool(API_KEY) and (bool(_LIGAS_FEMENINAS) or BUSQUEDA_GLOBAL)


def historial_disponible():
    """El historial por equipo no necesita ligas configuradas."""
    return bool(API_KEY) and HISTORIAL_ACTIVO


def _avisar_una_vez(clave, mensaje):
    if clave not in _avisos:
        _avisos.add(clave)
        U.log(mensaje)


# ---------------------------------------------------------------------------
# HTTP con limitador de ritmo (30 requests/minuto en el plan gratuito)
# ---------------------------------------------------------------------------
def _esperar_cupo():
    """Bloquea lo necesario para no pasar de MAX_PEDIDOS_MINUTO en una ventana de 60 s."""
    while True:
        with _lock:
            ahora = time.monotonic()
            while _pedidos_recientes and ahora - _pedidos_recientes[0] >= 60:
                _pedidos_recientes.popleft()
            if len(_pedidos_recientes) < MAX_PEDIDOS_MINUTO:
                _pedidos_recientes.append(ahora)
                return
            espera = 60 - (ahora - _pedidos_recientes[0]) + 0.05
        time.sleep(min(max(espera, 0.05), 61))


def _get(ruta, params=None, timeout=12):
    """Devuelve el JSON o None. Respeta el ritmo y se pausa 2 minutos tras un HTTP 429."""
    if time.time() < _backoff_hasta["t"]:
        return None
    _esperar_cupo()
    info = {}
    data = U.get_json(f"{BASE}/{ruta}", FUENTE, params=params, timeout=timeout, info=info, reintentar=False)
    if info.get("status") == 429:
        _backoff_hasta["t"] = time.time() + 120
        _avisar_una_vez(("429", int(time.time() // 600)), "[thesportsdb] HTTP 429; pausa de 2 minutos")
    return data


def _parsear_timestamp(valor):
    if valor is None or valor == "":
        return 0
    if isinstance(valor, (int, float)):
        numero = int(valor)
        return numero if numero > 10**9 else 0
    texto = str(valor).strip()
    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (TypeError, ValueError, OverflowError):
        return 0


# ---------------------------------------------------------------------------
# VALIDACIÃ“N DE LIGAS CONFIGURADAS
# ---------------------------------------------------------------------------
def _liga_valida(league_id):
    """
    Consulta lookupleague.php una vez por liga y por dÃ­a. Se descarta solo si TheSportsDB declara
    la liga como masculina; si no responde o no informa gÃ©nero, se confÃ­a en el operador (y se
    reintenta la comprobaciÃ³n mÃ¡s tarde). El nombre queda en el log para que lo verifiques.
    """
    hit, valor = _cache_ligas.get(league_id)
    if hit:
        return valor
    data = _get("lookupleague.php", {"id": league_id})
    ligas = data.get("leagues") if isinstance(data, dict) else None
    if not isinstance(ligas, list) or not ligas or not isinstance(ligas[0], dict):
        _cache_ligas.set(league_id, True, ttl=3600)
        return True
    liga = ligas[0]
    nombre = str(liga.get("strLeague") or "?")
    genero = str(liga.get("strGender") or "").strip().lower()
    if genero in _GENEROS_MASCULINOS:
        U.log(f"[thesportsdb] liga {league_id} ({nombre}) figura como MASCULINA en TheSportsDB: se descarta; "
              "quitala de THESPORTSDB_WOMENS_LEAGUES")
        _cache_ligas.set(league_id, False)
        return False
    detalle = f"gÃ©nero={genero}" if genero else "gÃ©nero sin informar"
    U.log(f"[thesportsdb] liga {league_id}: {nombre} ({detalle})")
    _cache_ligas.set(league_id, True)
    return True


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
def _eventos_fecha(deporte_tsdb, fecha, league_id=None):
    clave = (deporte_tsdb, fecha, str(league_id or "global"))
    hit, valor = _cache_eventos.get(clave)
    if hit:
        return valor
    params = {"d": fecha, "s": deporte_tsdb}
    if league_id:
        params["l"] = str(league_id)
    data = _get("eventsday.php", params)
    if not isinstance(data, dict):
        _cache_eventos.set(clave, None, ttl=TTL_FALLO)
        return None
    events = data.get("events")
    if events is None:
        events = []
    if not isinstance(events, list):
        _cache_eventos.set(clave, None, ttl=TTL_FALLO)
        return None
    _cache_eventos.set(clave, events)
    return events


def _normalizar_evento(deporte, ev, liga_autorizada=False):
    if not isinstance(ev, dict):
        return None
    liga = str(ev.get("strLeague") or "").strip()
    local = str(ev.get("strHomeTeam") or "").strip()
    visita = str(ev.get("strAwayTeam") or "").strip()
    if not local or not visita:
        return None

    es_fem = liga_autorizada or U.es_femenino(liga, local, visita)
    if not es_fem:
        return None

    raw_ts = ev.get("strTimestamp")
    ts = _parsear_timestamp(raw_ts)
    # No reinterpretar strTime sin zona horaria como UTC: puede ser hora local
    # del evento y desplazarlo varias horas. Sin timestamp/offset explÃ­cito se descarta.
    if not ts:
        return None

    status = str(ev.get("strStatus") or "").strip().lower()
    if status in {"", "not started", "ns", "scheduled", "time to be defined", "pre-game"}:
        estado = "pre"
    elif any(token in status for token in ("live", "progress", "half-time", "in play")):
        estado = "in"
    else:
        estado = "post"

    event_id = ev.get("idEvent")
    if event_id is None:
        return None
    league_id = ev.get("idLeague")
    tournament = liga or (f"TheSportsDB liga {league_id}" if league_id else "TheSportsDB")
    return {
        "id": f"thesportsdb_{event_id}",
        "clave": U.clave_partido(local, visita, ts),
        "deporte": deporte,
        "torneo": tournament,
        "local": {
            "id": str(ev.get("idHomeTeam") or local),
            "nombre": local,
            "ranking": None,
            "fuera_ranking": False,
        },
        "visita": {
            "id": str(ev.get("idAwayTeam") or visita),
            "nombre": visita,
            "ranking": None,
            "fuera_ranking": False,
        },
        "horario": U.formatear_hora_arg(ts),
        "tipo_estado": estado,
        "startTimestamp": ts,
        "fuente": FUENTE,
        "femenino_seguro": True,
        "liga_ref": (str(league_id or ""),),
    }


def obtener_eventos(deporte_interno):
    deporte_tsdb = _DEPORTES_TSDB.get(deporte_interno)
    if not deporte_tsdb or not disponible():
        return []

    ahora = datetime.now(timezone.utc)
    fechas = [ahora.strftime("%Y-%m-%d"), (ahora + timedelta(days=1)).strftime("%Y-%m-%d")]
    liga_ids = [lid for lid in sorted(_LIGAS_FEMENINAS.get(deporte_interno, set())) if _liga_valida(lid)]
    consultas = [(fecha, league_id, True) for league_id in liga_ids for fecha in fechas]
    if BUSQUEDA_GLOBAL:
        consultas.extend((fecha, None, False) for fecha in fechas)

    by_id = {}
    for fecha, league_id, autorizada in consultas:
        events = _eventos_fecha(deporte_tsdb, fecha, league_id)
        if events is None:
            continue
        for raw in events:
            # Si se llamÃ³ /eventsday con l=ID, solo se confÃ­a en ese ID exacto.
            event_league_id = str((raw or {}).get("idLeague") or "")
            whitelist = autorizada and (not event_league_id or event_league_id == str(league_id))
            normalized = _normalizar_evento(deporte_interno, raw, liga_autorizada=whitelist)
            if not normalized or normalized["tipo_estado"] != "pre":
                continue
            ts = normalized["startTimestamp"]
            now = ahora.timestamp()
            if ts <= now or ts > now + 36 * 3600:
                continue
            by_id[normalized["id"]] = normalized
            # Identidades femeninas verificadas del calendario, sin searchteams gratuito.
            for lado in ("local", "visita"):
                j = normalized[lado]
                _cache_busqueda.set(f"{deporte_tsdb}|{U.normalizar(j['nombre'])}", str(j["id"]))

    # La key 123 devuelve un eventslast incompleto: recolectar resultados por liga/día
    # y acumularlos en el libro, sin presentarlos como historial exhaustivo.
    for liga_id in liga_ids:
        clave_resultados = ("resultados", deporte_tsdb, liga_id, ahora.date().isoformat())
        hit, _ = _cache_busqueda.get(clave_resultados)
        if hit:
            continue
        fecha_ayer = (ahora - timedelta(days=1)).date().isoformat()
        crudos = _eventos_fecha(deporte_tsdb, fecha_ayer, liga_id)
        if crudos is not None:
            partidos = [p for e in crudos if str(e.get("idLeague") or "") == str(liga_id)
                        if (p := _normalizar_terminado(e, time.time(), exigir_final=True))]
            L.ingestar(deporte_interno, partidos, FUENTE)
            _cache_busqueda.set(clave_resultados, True, ttl=24 * 3600)

    if by_id:
        U.log(f"[thesportsdb/{deporte_interno}] {len(by_id)} partidos femeninos capturados")
    elif not _LIGAS_FEMENINAS and not BUSQUEDA_GLOBAL:
        global _ultimo_aviso_sin_ligas
        if time.time() - _ultimo_aviso_sin_ligas > 6 * 3600:
            _ultimo_aviso_sin_ligas = time.time()
            U.log(
                "[thesportsdb] sin fixtures: configurÃ¡ THESPORTSDB_WOMENS_LEAGUES con IDs "
                "verificados (por ejemplo Soccer:ID). El listado global gratuito tiene cobertura limitada."
            )
    return list(by_id.values())


# ---------------------------------------------------------------------------
# HISTORIAL (eventslast.php) Y BÃšSQUEDA DE EQUIPOS (searchteams.php)
# ---------------------------------------------------------------------------
def _entero(valor):
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _normalizar_terminado(ev, ahora_ts, exigir_final=False):
    """Partido ya jugado con marcador en el formato interno del radar, o None."""
    if not isinstance(ev, dict):
        return None
    if str(ev.get("strPostponed") or "").strip().lower() == "yes":
        return None
    estado = str(ev.get("strStatus") or "").strip().lower()
    if exigir_final and estado not in {"ft", "aet", "pen", "finished", "match finished", "final", "ended", "after extra time"}:
        return None
    if any(token in estado for token in _NO_JUGADOS):
        return None
    id_local, id_visita = ev.get("idHomeTeam"), ev.get("idAwayTeam")
    nom_local = str(ev.get("strHomeTeam") or "").strip()
    nom_visita = str(ev.get("strAwayTeam") or "").strip()
    pl, pv = _entero(ev.get("intHomeScore")), _entero(ev.get("intAwayScore"))
    if id_local is None or id_visita is None or not nom_local or not nom_visita or pl is None or pv is None:
        return None
    ts = _parsear_timestamp(ev.get("strTimestamp"))
    if not ts:
        # Para historial alcanza la precisiÃ³n de dÃ­a: 12:00 UTC de dateEvent.
        ts = _parsear_timestamp(f"{str(ev.get('dateEvent') or '')[:10]}T12:00:00") if ev.get("dateEvent") else 0
    if not ts or ts >= ahora_ts:
        return None
    return {
        "fecha": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
        "id_local": str(id_local), "nom_local": nom_local,
        "id_visita": str(id_visita), "nom_visita": nom_visita,
        "puntos_local": pl, "puntos_visita": pv,
    }


def _ultimos_partidos(team_id, deporte=None):
    """Ãšltimos partidos terminados del equipo (formato interno, mÃ¡s reciente primero)."""
    team_id = str(team_id)
    hit, valor = _cache_forma.get(team_id)
    if hit:
        return valor
    data = _get("eventslast.php", {"id": team_id})
    if not isinstance(data, dict):
        _cache_forma.set(team_id, [], ttl=TTL_FALLO)
        return []
    crudos = data.get("results")
    if not isinstance(crudos, list):
        crudos = data.get("events")
    if not isinstance(crudos, list):
        crudos = []
    ahora_ts = time.time()
    partidos = []
    for crudo in crudos:
        p = _normalizar_terminado(crudo, ahora_ts)
        # Defensa ante respuestas que mezclen eventos de otros equipos.
        if p and team_id in (p["id_local"], p["id_visita"]):
            partidos.append(p)
    partidos.sort(key=lambda p: p["fecha"], reverse=True)
    if deporte and partidos:
        L.ingestar(deporte, partidos, "thesportsdb")
    if crudos and not partidos:
        _avisar_una_vez(("forma", team_id), f"[thesportsdb] eventslast del equipo {team_id}: {len(crudos)} items sin forma esperada")
    _cache_forma.set(team_id, partidos, ttl=None if partidos else 3600)
    return partidos


def _con_id_interno(partidos, equipo_id, id_interno):
    """Copia el historial reescribiendo el id del equipo consultado por el id que usa el evento."""
    if id_interno is None or str(id_interno) == str(equipo_id):
        return [dict(p) for p in partidos]
    copia = []
    for p in partidos:
        q = dict(p)
        if q["id_local"] == str(equipo_id):
            q["id_local"] = str(id_interno)
        if q["id_visita"] == str(equipo_id):
            q["id_visita"] = str(id_interno)
        copia.append(q)
    return copia


def historial_equipo(evento, lado):
    """Para eventos que vienen de TheSportsDB: el id del equipo ya es el de TheSportsDB."""
    if not historial_disponible() or evento.get("fuente") != FUENTE:
        return []
    equipo_id = str((evento.get(lado) or {}).get("id") or "")
    if not equipo_id.isdigit():
        return []
    return _ultimos_partidos(equipo_id, evento.get("deporte"))


def _alias(equipo):
    nombres = [str(equipo.get("strTeam") or "")]
    nombres += [x.strip() for x in str(equipo.get("strAlternate") or "").split(",") if x.strip()]
    return [n for n in nombres if n]


def _elegir_equipo(nombre, deporte_tsdb, candidatos):
    objetivo = U.normalizar(nombre)
    mejor, mejor_pts = None, 0
    for c in candidatos:
        if not isinstance(c, dict) or c.get("idTeam") is None:
            continue
        deporte_c = str(c.get("strSport") or "")
        if deporte_c and deporte_tsdb and deporte_c.lower() != deporte_tsdb.lower():
            continue
        genero = str(c.get("strGender") or "").strip().lower()
        if genero in _GENEROS_MASCULINOS:
            continue
        alias = _alias(c)
        if not any(U.nombres_coinciden(nombre, a) for a in alias):
            continue
        fem = genero == "female" or any(U.es_femenino("", a, "") for a in alias)
        if EXIGIR_FEMENINO and not fem:
            continue  # "Arsenal W" nunca se resuelve al Arsenal masculino
        pts = 1 + (2 if any(U.normalizar(a) == objetivo for a in alias) else 0) + (1 if fem else 0)
        if pts > mejor_pts:
            mejor, mejor_pts = str(c["idTeam"]), pts
    return mejor


def _buscar_equipo(nombre, deporte):
    deporte_tsdb = _DEPORTES_TSDB.get(deporte)
    if not historial_disponible() or not nombre or not deporte_tsdb:
        return None
    clave = f"{deporte_tsdb}|{U.normalizar(nombre)}"
    hit, valor = _cache_busqueda.get(clave)
    if hit:
        return valor
    if API_KEY == "123":
        return None  # Documentación: searchteams Free está limitado a Arsenal.
    data = _get("searchteams.php", {"t": nombre})
    if not isinstance(data, dict):
        return None  # fallo de red: se reintenta en el prÃ³ximo barrido
    candidatos = data.get("teams") if isinstance(data.get("teams"), list) else []
    equipo_id = _elegir_equipo(nombre, deporte_tsdb, candidatos)
    _cache_busqueda.set(clave, equipo_id, ttl=None if equipo_id else 6 * 3600)
    return equipo_id


def obtener_forma_reciente(nombre_equipo, deporte="Soccer", limite=8, id_interno=None):
    """Ãšltimos partidos de un equipo buscado por nombre; el id del equipo queda como `id_interno`."""
    equipo_id = _buscar_equipo(nombre_equipo, deporte)
    if not equipo_id:
        return []
    partidos = _ultimos_partidos(equipo_id, deporte)[:max(1, int(limite))]
    return _con_id_interno(partidos, equipo_id, id_interno)
