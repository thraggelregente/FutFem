"""SportAPI.ai: fixtures y forma femenina; key solo en SPORTAPI_API_KEY.

Las fechas de fixtures son CET/CEST, kickoff_utc es UTC. El catálogo valida
género por liga; los historiales se aíslan por competición. Sin tabla de temporada
verificada y sin señales de descanso desde fechas que solo tienen día.
"""
import os
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import utilidades as U
from fuentes_publicas import enteros
from presupuesto_mensual import DiarioMensual

FUENTE = "sportapi"
API_KEY = os.environ.get("SPORTAPI_API_KEY", "").strip()
BASE = "https://sportapi.ai/api"
presupuesto = DiarioMensual("sportapi", 2000, 14000, desde='2026-11-01', reserva=0)
_cache = U.CachePersistente("sportapi_v1", 6 * 3600, max_items=1024)
_ritmo = U.RitmoPedidos(20, minimo_segundos=1)
_pausa = 0
_deshabilitada = False


def disponible():
    return bool(API_KEY) and not _deshabilitada


def _get(ruta, ttl=6 * 3600):
    global _pausa, _deshabilitada
    if not disponible():
        return None
    hit, dato = _cache.get(ruta)
    if hit:
        return dato
    if time.time() < _pausa or not presupuesto.puede_gastar():
        return None
    _ritmo.esperar()
    info = {}
    dato = U.get_json(BASE + ruta, FUENTE, headers={"X-Api-Key": API_KEY},
                      info=info, timeout=25, reintentar=False)
    headers = {k.lower(): v for k, v in (info.get("headers") or {}).items()}
    presupuesto.registrar(restantes_reales=headers.get("x-ratelimit-remaining"))
    if info.get("status") in (401, 403):
        _deshabilitada = True
        U.log("[sportapi] acceso rechazado: no se repite con esa key durante el proceso")
    elif info.get("status") == 429:
        try:
            _pausa = max(time.time()+60, float(headers.get("x-ratelimit-reset", 0)),
                         time.time()+float(headers.get("retry-after", 60)))
        except (TypeError, ValueError):
            _pausa = time.time()+3600
    if not isinstance(dato, dict) or dato.get("success") is not True:
        _cache.set(ruta, None, ttl=3600)
        return None
    _cache.set(ruta, dato, ttl=ttl)
    return dato


def catalogo_femenino():
    dato = _get("/leagues", ttl=24 * 3600) or {}
    salida = {}
    for pais in dato.get("data") or []:
        if not isinstance(pais, dict):
            continue
        for liga in pais.get("leagues") or []:
            if not isinstance(liga, dict) or not isinstance(liga.get("name"), str):
                continue
            nombre = liga["name"]
            if not (U.es_femenino(nombre, "", "") or re.search(r"\bWSL\b", nombre)):
                continue
            try:
                salida[int(liga["id"])] = nombre
            except (KeyError, TypeError, ValueError):
                continue
    return salida


def normalizar(raw, catalogo, ahora=None, solo_fecha=False):
    ahora = time.time() if ahora is None else ahora
    if not isinstance(raw, dict):
        return None
    ids = enteros(raw.get("league_id"), raw.get("home_id"), raw.get("away_id"), raw.get("id"))
    if not ids or min(ids) <= 0 or ids[1] == ids[2]:
        return None
    liga_id, a_id, b_id, match_id = ids
    liga = catalogo.get(liga_id)
    if not liga or U.normalizar(raw.get("league_name", "")) != U.normalizar(liga):
        return None
    a, b = raw.get("home_team", ""), raw.get("away_team", "")
    if not all(isinstance(n, str) and U.participante_definido(n) for n in (a, b)):
        return None
    # Alias exacto contrastado con SportScore, sin buscar identidades por similitud.
    a, b = ({"United States": "USA"}.get(n, n) for n in (a, b))
    edades = re.findall(r"\b(?:Under[ -]?|U[ -]?)(\d{2})\b", liga, re.I)
    if edades:
        for nombre in (a, b):
            edad_equipo = U.categoria_equipo(nombre)[0]
            if edad_equipo and edades[0] not in {str(e) for e in edad_equipo}:
                return None
        a += " U" + edades[0] if U.categoria_equipo(a)[0] == () else ""
        b += " U" + edades[0] if U.categoria_equipo(b)[0] == () else ""
    comunes = {"fuente": FUENTE, "deporte": "Soccer", "torneo": liga, "femenino_seguro": True,
               "historial_aislado": True, "contexto_competicion": "sportapi:" + str(liga_id), "league_id": liga_id,
               "local": {"id": "spai:"+str(a_id), "nombre": a, "sportapi_id": a_id},
               "visita": {"id": "spai:"+str(b_id), "nombre": b, "sportapi_id": b_id}}
    fecha = str(raw.get("kickoff_utc") or "")
    precision_dia = False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", fecha):
        if not solo_fecha or raw.get("status") != "FT" or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(raw.get("date", ""))):
            return None
        fecha, precision_dia = raw["date"], True
    f = U._parsear_iso(fecha)
    if not f:
        return None
    ts = f.timestamp()
    if raw.get("status") == "Scheduled" and ahora < ts <= ahora + 86400:
        return dict(comunes, id="spai_"+str(match_id), tipo_estado="pre", startTimestamp=int(ts), horario=U.formatear_hora_arg(ts))
    puntos = enteros(raw.get("home_score"), raw.get("away_score"))
    if raw.get("status") != "FT" or not puntos or min(puntos) < 0 or not ahora - 90 * 86400 <= ts < ahora:
        return None
    return dict(comunes, id="spai_"+str(match_id), _outcome_status="normal", fecha=fecha, _fecha_solo_dia=precision_dia, _calendario_completo=False,
                id_local=comunes["local"]["id"], id_visita=comunes["visita"]["id"],
                nom_local=a, nom_visita=b, puntos_local=puntos[0], puntos_visita=puntos[1])


def obtener_eventos(deporte):
    if deporte != "Soccer" or not disponible():
        return []
    catalogo = catalogo_femenino()
    if not catalogo:
        return []
    ahora = datetime.now(timezone.utc)
    # La muestra real conserva date UTC en algunos partidos con datetime CET
    # del día siguiente. Consultar ambas fronteras, sin inferir kickoff desde date.
    dias = {ahora.date(), (ahora+timedelta(days=1)).date(),
            ahora.astimezone(ZoneInfo("Europe/Berlin")).date(),
            (ahora+timedelta(days=1)).astimezone(ZoneInfo("Europe/Berlin")).date()}
    salida = {}
    for dia in sorted(dias):
        dato = _get("/fixtures/date/"+dia.isoformat(), ttl=3600) or {}
        if dato.get("date") != dia.isoformat():
            continue
        for raw in dato.get("data") or []:
            p = normalizar(raw, catalogo)
            if p and p.get("tipo_estado") == "pre":
                salida[p["id"]] = p
    U.log(f"[sportapi] {len(salida)} próximos femeninos, catálogo de {len(catalogo)} competiciones")
    return list(salida.values())


def historial_equipo(evento, lado):
    equipo = evento.get(lado) or {}
    tid = equipo.get("sportapi_id")
    if not isinstance(tid, int) or tid <= 0:
        return []
    dato = _get("/teams/"+str(tid)) or {}
    if (dato.get("team") or {}).get("id") != tid:
        return []
    catalogo = catalogo_femenino()
    filas = [p for p in (normalizar(r, catalogo, solo_fecha=True) for r in dato.get("matches") or [])
             if p and "fecha" in p and p["contexto_competicion"] == evento.get("contexto_competicion")
             and equipo.get("id") in (p["id_local"], p["id_visita"])]
    return sorted(filas, key=lambda p: p["fecha"], reverse=True)[:10]


def resultados_evaluacion(evento):
    from resultados_evaluacion import de_historial
    if evento.get('deporte')!='Soccer' or not disponible():
        return []
    if not any(o.get('fuente')==FUENTE for o in evento.get('_observaciones') or [evento]):
        return []
    dia=datetime.fromtimestamp(evento['startTimestamp'],timezone.utc).date().isoformat()
    data=_get('/fixtures/date/'+dia,ttl=1800) or {}
    if data.get('date')!=dia:
        return []
    catalogo=catalogo_femenino()
    return [r for raw in data.get('data') or [] if (p:=normalizar(raw,catalogo,solo_fecha=True)) and 'fecha' in p
            and (r:=de_historial(p,'Soccer',FUENTE))]
