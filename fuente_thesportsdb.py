"""TheSportsDB V1: fixtures femeninos de ligas allowlisteadas.

La API V1 pública utiliza la key 123. El endpoint global eventsday.php tiene un
límite de respuesta muy bajo en el plan gratuito, de modo que la fuente consulta
por ID de liga cuando se configura THESPORTSDB_WOMENS_LEAGUES. No se consultan
cuotas, mercados ni bookmakers.

Formato THESPORTSDB_WOMENS_LEAGUES:
    Soccer:ID_LIGA,Basketball:ID_LIGA,Volleyball:ID_LIGA
Solo agregar IDs comprobados como competiciones femeninas. Opcionalmente se puede
activar THESPORTSDB_BUSQUEDA_GLOBAL=1; esa búsqueda es menos completa y solo deja
pasar partidos con evidencia explícita de género femenino en la respuesta.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone

import utilidades as U

API_KEY = (os.environ.get("THESPORTSDB_KEY") or "123").strip() or "123"
BASE = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"
FUENTE = "thesportsdb"
CACHE_MINUTOS = max(10, int(os.environ.get("THESPORTSDB_CACHE_MINUTOS", "240")))
BUSQUEDA_GLOBAL = os.environ.get("THESPORTSDB_BUSQUEDA_GLOBAL", "0").strip().lower() in {"1", "true", "yes", "on"}

_DEPORTES_TSDB = {
    "Soccer": "Soccer",
    "Basketball": "Basketball",
    "Handball": "Handball",
    "Ice Hockey": "Ice Hockey",
    "Volleyball": "Volleyball",
    "Rugby": "Rugby",
    "Tennis": "Tennis",
}


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
_avisos = set()
_ultimo_aviso_sin_ligas = 0.0


def disponible():
    return bool(API_KEY) and (bool(_LIGAS_FEMENINAS) or BUSQUEDA_GLOBAL)


def _avisar_una_vez(clave, mensaje):
    if clave not in _avisos:
        _avisos.add(clave)
        U.log(mensaje)


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


def _eventos_fecha(deporte_tsdb, fecha, league_id=None):
    clave = (deporte_tsdb, fecha, str(league_id or "global"))
    hit, valor = _cache_eventos.get(clave)
    if hit:
        return valor
    params = {"d": fecha, "s": deporte_tsdb}
    if league_id:
        params["l"] = str(league_id)
    url = f"{BASE}/eventsday.php"
    data = U.get_json(url, FUENTE, params=params, timeout=12)
    if not isinstance(data, dict):
        # Los errores/transitorios se cachean también para no repetir en cada barrido.
        _cache_eventos.set(clave, None)
        return None
    events = data.get("events")
    if events is None:
        events = []
    if not isinstance(events, list):
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
    # del evento y desplazarlo varias horas. Sin timestamp/offset explícito se descarta.
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
    liga_ids = sorted(_LIGAS_FEMENINAS.get(deporte_interno, set()))
    consultas = [(fecha, league_id, True) for league_id in liga_ids for fecha in fechas]
    if BUSQUEDA_GLOBAL:
        consultas.extend((fecha, None, False) for fecha in fechas)

    by_id = {}
    for fecha, league_id, autorizada in consultas:
        events = _eventos_fecha(deporte_tsdb, fecha, league_id)
        if events is None:
            continue
        for raw in events:
            # Si se llamó /eventsday con l=ID, solo se confía en ese ID exacto.
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
        # Respeta holgadamente el límite documentado de 30 peticiones/minuto.
        if len(consultas) > 12:
            time.sleep(0.08)

    if by_id:
        U.log(f"[thesportsdb/{deporte_interno}] {len(by_id)} partidos femeninos capturados")
    elif not _LIGAS_FEMENINAS and not BUSQUEDA_GLOBAL:
        global _ultimo_aviso_sin_ligas
        if time.time() - _ultimo_aviso_sin_ligas > 6 * 3600:
            _ultimo_aviso_sin_ligas = time.time()
            U.log(
                "[thesportsdb] sin consumo de API: configurá THESPORTSDB_WOMENS_LEAGUES con IDs "
                "verificados (por ejemplo Soccer:ID). El listado global gratuito tiene cobertura limitada."
            )
    return list(by_id.values())
