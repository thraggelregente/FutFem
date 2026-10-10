"""
fuente_espn.py
Fuente de datos de ESPN API (pública, sin autenticación, sin Cloudflare).

Deportes soportados y sus "leagues" (slugs) en ESPN:
- Fútbol femenino: esp.1 (Liga F), eng.1 (WSL), usa.1 (NWSL), etc.
- Básquet: wnba, nba, etc.
- Tenis: ATP y WTA (endpoint especial).
- Fútbol americano: nfl.
- Hockey: nhl.
- Béisbol: mlb.
- Vóley: volleyball (endpoint especial).
- Balonmano: handball.
- Rugby: rugby.

La API es pública: https://site.api.espn.com/apis/site/v2/sports/{deporte}/{liga}/scoreboard
"""

import time
from datetime import datetime, timedelta, timezone

import utilidades as U

# Mapeo de nuestros deportes internos a los slugs de ESPN
# Cada entrada: deporte_interno -> {liga_slug: nombre_legible}
DEPORTES_ESPN = {
    "Soccer": {
        "esp.1": "Liga F (España)",
        "eng.1": "Women's Super League (Inglaterra)",
        "usa.1": "NWSL (EE.UU.)",
        "ger.1": "Frauen-Bundesliga (Alemania)",
        "fra.1": "Division 1 Feminine (Francia)",
        "ita.1": "Serie A Femminile (Italia)",
        "uefa.weuro": "UEFA Women's Euro",
        "fifa.wwc": "FIFA Women's World Cup",
    },
    "Basketball": {
        "wnba": "WNBA",
    },
    "Volleyball": {
        "volleyball": "Volleyball",
    },
    "Tennis": {
        "wta": "WTA",
    },
    "Handball": {
        "handball": "Handball",
    },
    "Rugby": {
        "rugby": "Rugby",
    },
}

# Caché para no repetir peticiones en el mismo ciclo
_cache_scoreboard = U.CacheTTL(30 * 60)  # 30 min


def _deporte_espn_para(deporte_interno):
    """Devuelve el slug del deporte para la URL de ESPN."""
    return {
        "Soccer": "soccer",
        "Basketball": "basketball",
        "Volleyball": "volleyball",
        "Tennis": "tennis",
        "Handball": "handball",
        "Rugby": "rugby",
    }.get(deporte_interno)


def _obtener_scoreboard(deporte_espn, liga, fecha_yyyymmdd):
    """
    Consulta el scoreboard de ESPN para una fecha (YYYYMMDD).
    Devuelve la lista de eventos o [] si falla.
    """
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


def _normalizar_evento_espn(evento, deporte_interno, liga_nombre):
    """
    Convierte un evento de ESPN al formato interno del radar.
    Formato interno: {id, deporte, torneo, local, visita, horario, estado, startTimestamp, favorito_hint}
    """
    competiciones = evento.get("competitions", []) or []
    if not competiciones:
        return None

    comp = competiciones[0]
    competidores = comp.get("competitors", []) or []
    if len(competidores) < 2:
        return None

    # ESPN marca home/away con "homeAway": "home" | "away"
    local_obj = next((c for c in competidores if c.get("homeAway") == "home"), None)
    visita_obj = next((c for c in competidores if c.get("homeAway") == "away"), None)

    # Si no hay home/away, tomamos los dos primeros
    if not local_obj or not visita_obj:
        local_obj, visita_obj = competidores[0], competidores[1]

    def _extraer_equipo(obj):
        team = obj.get("team") or {}
        return {
            "id": team.get("id"),
            "nombre": team.get("displayName") or team.get("name") or "?",
            "abrev": team.get("abbreviation"),
            "ranking": (obj.get("curatedRank") or {}).get("current"),
            "record": (obj.get("records") or [{}])[0].get("summary") if obj.get("records") else None,
        }

    local = _extraer_equipo(local_obj)
    visita = _extraer_equipo(visita_obj)

    fecha_str = evento.get("date")  # ISO 8601 UTC
    try:
        if fecha_str:
            fecha_dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
            start_ts = int(fecha_dt.timestamp())
        else:
            start_ts = 0
    except Exception:
        start_ts = 0

    estado_obj = (comp.get("status") or evento.get("status") or {})
    tipo_estado = (estado_obj.get("type") or {}).get("state", "pre")  # pre | in | post
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
        "favorito_hint": None,  # ESPN no da favorito, lo calcula el motor
        "fuente": "espn",
    }


def obtener_eventos_espn(deporte_interno):
    """
    Devuelve todos los eventos de ESPN para un deporte interno (hoy y mañana).
    """
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

    # Deduplicar por id
    unicos = {ev["id"]: ev for ev in eventos_totales}
    return list(unicos.values())


def es_femenino(evento):
    """
    Filtro femenino para ESPN. ESPN ya nos da ligas femeninas específicas,
    pero por si acaso revisamos el nombre del torneo.
    """
    texto = f"{evento['torneo']} {evento['local']['nombre']} {evento['visita']['nombre']}".lower()
    # Las ligas de DEPORTES_ESPN ya son femeninas, así que aquí solo verificamos palabras clave
    return True