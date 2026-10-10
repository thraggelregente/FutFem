"""
fuente_espn.py
Fuente de datos de ESPN API (pública, sin autenticación, sin Cloudflare).

Slugs verificados de ESPN:
- soccer/esp.1       -> Liga F (España)
- soccer/eng.1       -> Women's Super League (Inglaterra)
- soccer/usa.1       -> NWSL (EE.UU.)
- soccer/ger.1       -> Frauen-Bundesliga (Alemania)
- soccer/fra.1       -> Division 1 Feminine (Francia)
- soccer/ita.1       -> Serie A Femminile (Italia)
- soccer/uefa.weuro  -> UEFA Women's Euro
- basketball/wnba    -> WNBA
- tennis/wta         -> WTA (endpoint especial)
- hockey/womens-college-hockey -> Hockey femenino NCAA
- rugby/270557       -> Rugby femenino (liga específica)
"""

import time
from datetime import datetime, timedelta, timezone

import utilidades as U

# Mapeo de nuestros deportes internos a los slugs verificados de ESPN
DEPORTES_ESPN = {
    "Soccer": {
        "esp.1": "Liga F (España)",
        "eng.1": "Women's Super League (Inglaterra)",
        "usa.1": "NWSL (EE.UU.)",
        "ger.1": "Frauen-Bundesliga (Alemania)",
        "fra.1": "Division 1 Feminine (Francia)",
        "ita.1": "Serie A Femminile (Italia)",
    },
    "Basketball": {
        "wnba": "WNBA",
    },
    "Tennis": {
        "wta": "WTA",
    },
    "Ice Hockey": {
        "womens-college-hockey": "NCAA Women's Hockey",
    },
}

# Mapeo a slugs de deporte
_DEPORTE_ESPN = {
    "Soccer": "soccer",
    "Basketball": "basketball",
    "Tennis": "tennis",
    "Ice Hockey": "hockey",
}

_cache_scoreboard = U.CacheTTL(30 * 60)


def _deporte_espn_para(deporte_interno):
    return _DEPORTE_ESPN.get(deporte_interno)


def _obtener_scoreboard(deporte_espn, liga, fecha_yyyymmdd):
    clave = (deporte_espn, liga, fecha_yyyymmdd)
    hit, valor = _cache_scoreboard.get(clave)
    if hit:
        return valor

    url = f"https://site.api.espn.com/apis/site/v2/sports/{deporte_espn}/{liga}/scoreboard"
    data = U.get_json(url, "espn", params={"dates": fecha_yyyymmdd}, timeout=10)

    eventos = []
    if isinstance(data, dict):
        eventos = data.get("events", []) or []
    _cache_scoreboard.set(clave, eventos)
    return eventos


def _extraer_equipo(obj):
    team = obj.get("team") or {}
    record = None
    records = obj.get("records") or []
    if records:
        record = records[0].get("summary")
    return {
        "id": team.get("id"),
        "nombre": team.get("displayName") or team.get("name") or "?",
        "abrev": team.get("abbreviation"),
        "ranking": (obj.get("curatedRank") or {}).get("current"),
        "record": record,
        "logo": (team.get("logo") or None),
    }


def _normalizar_evento_espn(evento, deporte_interno, liga_nombre):
    competiciones = evento.get("competitions", []) or []
    if not competiciones:
        return None

    comp = competiciones[0]
    competidores = comp.get("competitors", []) or []
    if len(competidores) < 2:
        return None

    local_obj = next((c for c in competidores if c.get("homeAway") == "home"), None)
    visita_obj = next((c for c in competidores if c.get("homeAway") == "away"), None)
    if not local_obj or not visita_obj:
        local_obj, visita_obj = competidores[0], competidores[1]

    local = _extraer_equipo(local_obj)
    visita = _extraer_equipo(visita_obj)

    fecha_str = evento.get("date")
    try:
        if fecha_str:
            fecha_dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
            start_ts = int(fecha_dt.timestamp())
        else:
            start_ts = 0
    except Exception:
        start_ts = 0

    estado_obj = (comp.get("status") or evento.get("status") or {})
    tipo_estado = (estado_obj.get("type") or {}).get("state", "pre")
    estado_txt = (estado_obj.get("type") or {}).get("description") or "Programado"

    return {
        "id": f"espn_{evento.get('id')}",
        "deporte": deporte_interno,
        "torneo": liga_nombre,
        "local": local,
        "visita": visita,
        "horario": U.formatear_hora_arg(start_ts) if start_ts else "A confirmar",
        "estado": estado_txt,
        "tipo_estado": tipo_estado,
        "startTimestamp": start_ts,
        "fuente": "espn",
    }


def obtener_eventos_espn(deporte_interno):
    deporte_espn = _deporte_espn_para(deporte_interno)
    if not deporte_espn:
        return []

    ligas = DEPORTES_ESPN.get(deporte_interno, {})
    if not ligas:
        return []

    eventos_totales = []
    for dias in (0, 1):
        fecha = (datetime.now(timezone.utc) + timedelta(days=dias)).strftime("%Y%m%d")
        for liga_slug, liga_nombre in ligas.items():
            eventos = _obtener_scoreboard(deporte_espn, liga_slug, fecha)
            for ev in eventos:
                normalizado = _normalizar_evento_espn(ev, deporte_interno, liga_nombre)
                if normalizado:
                    eventos_totales.append(normalizado)

    unicos = {ev["id"]: ev for ev in eventos_totales}
    return list(unicos.values())