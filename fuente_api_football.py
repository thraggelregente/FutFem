"""
fuente_api_football.py
Fuente de datos de API-Sports (https://www.api-sports.io/).

UNA SOLA API KEY para todos los deportes con ligas femeninas:
- Football: v3.football.api-sports.io
- Basketball: v1.basketball.api-sports.io
- Handball: v1.handball.api-sports.io
- Ice Hockey: v1.hockey.api-sports.io
- Volleyball: v1.volleyball.api-sports.io
- Rugby: v1.rugby.api-sports.io

Deportes descartados: Formula-1, MLB, NFL, AFL y MMA porque
no tienen ligas femeninas organizadas dentro de la API de API-Sports.

Plan Free: 100 requests/día COMPARTIDOS entre todos los deportes.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import utilidades as U

API_KEY = os.environ.get("API_FOOTBALL_KEY")

# Hosts de cada deporte CON ligas femeninas confirmadas
_HOSTS = {
    "Soccer": "v3.football.api-sports.io",
    "Basketball": "v1.basketball.api-sports.io",
    "Handball": "v1.handball.api-sports.io",
    "Ice Hockey": "v1.hockey.api-sports.io",
    "Volleyball": "v1.volleyball.api-sports.io",
    "Rugby": "v1.rugby.api-sports.io",
}

# Palabras clave femeninas
_KEYWORDS_FEM = [
    "women", "womens", "women's", "woman",
    "fem", "femenil", "femenino", "femenina",
    "feminin", "feminine", "femminile",
    "dames", "damen", "frauen", "ladies",
    "wta", "wnba", "nwsl", "wsl",
    "kvinde", "damallsvenskan", "toppserien",
    "we league", "liga f",
]

# Palabras clave masculinas (para descartar)
_KEYWORDS_MASC = [
    "atp", "challenger", "davis cup",
    "nba", "nfl", "nhl", "mlb", "mls",
    "premier league", "la liga", "serie a",
    "bundesliga", "ligue 1", "eredivisie",
    "champions league", "europa league",
    "copa america", "eurocopa", "world cup",
]

# Cachés
_cache_ligas = U.CacheTTL(6 * 3600)
_cache_eventos = U.CacheTTL(30 * 60)
_cache_h2h = U.CacheTTL(6 * 3600)
_cache_tabla = U.CacheTTL(6 * 3600)
_cache_forma = U.CacheTTL(3 * 3600)


def _headers():
    return {"x-apisports-key": API_KEY}


def _es_liga_femenina(nombre_liga):
    """Determina si una liga es femenina por su nombre."""
    if not nombre_liga:
        return False
    texto = nombre_liga.lower()
    if any(kw in texto for kw in _KEYWORDS_FEM):
        return True
    if any(kw in texto for kw in _KEYWORDS_MASC):
        return False
    return False


def _obtener_ligas_femeninas(deporte):
    """Obtiene las ligas femeninas activas de un deporte (cache 6h)."""
    if not API_KEY:
        return []

    host = _HOSTS.get(deporte)
    if not host:
        return []

    cache_key = f"ligas_{deporte}"
    hit, valor = _cache_ligas.get(cache_key)
    if hit:
        return valor

    season = datetime.now(timezone.utc).year
    url = f"https://{host}/leagues"
    params = {"season": season}

    data = U.get_json(url, f"api_football_{deporte}", headers=_headers(),
                      params=params, timeout=15)

    ligas_femeninas = []
    if isinstance(data, dict):
        for item in data.get("response", []) or []:
            liga = item.get("league") or {}
            pais = item.get("country") or {}
            nombre = liga.get("name", "")
            if _es_liga_femenina(nombre):
                ligas_femeninas.append({
                    "id": liga.get("id"),
                    "nombre": nombre,
                    "pais": pais.get("name", ""),
                    "temporada": season,
                })

    U.log(f"[api_football/{deporte}] {len(ligas_femeninas)} ligas femeninas encontradas")
    _cache_ligas.set(cache_key, ligas_femeninas)
    return ligas_femeninas


def _obtener_eventos_liga(deporte, liga_id, fecha_yyyymmdd):
    """Obtiene los eventos de una liga en una fecha."""
    host = _HOSTS.get(deporte)
    if not host or not liga_id:
        return []

    url = f"https://{host}/games"
    params = {
        "league": liga_id,
        "date": fecha_yyyymmdd,
        "season": datetime.now(timezone.utc).year,
    }

    data = U.get_json(url, f"api_football_{deporte}", headers=_headers(),
                      params=params, timeout=10)
    if isinstance(data, dict):
        return data.get("response", []) or []
    return []


def _normalizar_evento(deporte, liga_nombre, evento):
    """Normaliza un evento de API-Sports al formato interno."""
    teams = evento.get("teams") or {}
    local_obj = teams.get("home") or {}
    visita_obj = teams.get("away") or {}

    goals = evento.get("goals") or {}
    score_local = goals.get("home")
    score_visita = goals.get("away")

    fixture = evento.get("fixture") or {}
    fecha_str = fixture.get("date")

    try:
        if fecha_str:
            fecha_dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
            start_ts = int(fecha_dt.timestamp())
        else:
            start_ts = 0
    except Exception:
        start_ts = 0

    status = (fixture.get("status") or {})
    short = status.get("short", "NS")

    if short in ("NS", "TBD"):
        tipo_estado = "pre"
        estado_txt = "Programado"
    elif short in ("1H", "2H", "HT", "ET", "P", "LIVE", "BT"):
        tipo_estado = "in"
        estado_txt = "En vivo"
    else:
        tipo_estado = "post"
        estado_txt = "Finalizado"

    return {
        "id": f"apifootball_{fixture.get('id')}",
        "deporte": deporte,
        "torneo": liga_nombre,
        "local": {
            "id": local_obj.get("id"),
            "nombre": local_obj.get("name", "Local"),
            "record": None,
            "ranking": None,
        },
        "visita": {
            "id": visita_obj.get("id"),
            "nombre": visita_obj.get("name", "Visitante"),
            "record": None,
            "ranking": None,
        },
        "horario": U.formatear_hora_arg(start_ts) if start_ts else "A confirmar",
        "estado": estado_txt,
        "tipo_estado": tipo_estado,
        "startTimestamp": start_ts,
        "fuente": "api_football",
        "score_local": score_local,
        "score_visita": score_visita,
    }


def obtener_eventos(deporte_interno):
    """Devuelve todos los eventos de API-Sports para un deporte."""
    if not API_KEY:
        return []

    if deporte_interno not in _HOSTS:
        return []

    ligas = _obtener_ligas_femeninas(deporte_interno)
    if not ligas:
        return []

    fecha_hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fecha_manana = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

    eventos_totales = []
    # Limitar a las 5 ligas más importantes para no agotar el límite de requests
    for liga in ligas[:5]:
        liga_id = liga["id"]
        liga_nombre = f"{liga['nombre']} ({liga['pais']})" if liga["pais"] else liga["nombre"]

        for fecha in (fecha_hoy, fecha_manana):
            eventos = _obtener_eventos_liga(deporte_interno, liga_id, fecha)
            for ev in eventos:
                normalizado = _normalizar_evento(deporte_interno, liga_nombre, ev)
                if normalizado:
                    eventos_totales.append(normalizado)
            time.sleep(0.3)

    unicos = {ev["id"]: ev for ev in eventos_totales}
    return list(unicos.values())


def obtener_h2h(equipo_local_id, equipo_visita_id, deporte="Soccer"):
    """Obtiene el H2H entre dos equipos."""
    if not API_KEY:
        return []

    host = _HOSTS.get(deporte)
    if not host:
        return []

    clave = f"h2h|{equipo_local_id}|{equipo_visita_id}"
    hit, valor = _cache_h2h.get(clave)
    if hit:
        return valor

    url = f"https://{host}/fixtures/headtohead"
    params = {"h2h": f"{equipo_local_id}-{equipo_visita_id}", "last": 10}

    data = U.get_json(url, f"api_football_{deporte}", headers=_headers(),
                      params=params, timeout=10)
    partidos = []
    if isinstance(data, dict):
        partidos = data.get("response", []) or []

    _cache_h2h.set(clave, partidos)
    return partidos


def obtener_tabla(liga_id, temporada, deporte="Soccer"):
    """Obtiene la tabla de posiciones de una liga."""
    if not API_KEY:
        return []

    host = _HOSTS.get(deporte)
    if not host:
        return []

    clave = f"tabla|{liga_id}|{temporada}"
    hit, valor = _cache_tabla.get(clave)
    if hit:
        return valor

    url = f"https://{host}/standings"
    params = {"league": liga_id, "season": temporada}

    data = U.get_json(url, f"api_football_{deporte}", headers=_headers(),
                      params=params, timeout=10)
    tabla = []
    if isinstance(data, dict):
        response = data.get("response", []) or []
        if response and isinstance(response[0], dict):
            liga_data = response[0].get("league", {})
            standings = liga_data.get("standings", []) or []
            if standings and isinstance(standings[0], list):
                tabla = standings[0]

    _cache_tabla.set(clave, tabla)
    return tabla


def obtener_forma_reciente(equipo_id, deporte="Soccer", limite=6):
    """Obtiene los últimos N partidos de un equipo."""
    if not API_KEY:
        return []

    host = _HOSTS.get(deporte)
    if not host:
        return []

    clave = f"forma|{equipo_id}|{limite}"
    hit, valor = _cache_forma.get(clave)
    if hit:
        return valor

    url = f"https://{host}/fixtures"
    params = {"team": equipo_id, "last": limite}

    data = U.get_json(url, f"api_football_{deporte}", headers=_headers(),
                      params=params, timeout=10)
    partidos = []
    if isinstance(data, dict):
        partidos = data.get("response", []) or []

    _cache_forma.set(clave, partidos)
    return partidos


def es_femenino(evento):
    """Verifica que el torneo sea femenino."""
    return _es_liga_femenina(evento.get("torneo", ""))