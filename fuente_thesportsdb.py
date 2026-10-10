"""
fuente_thesportsdb.py
Fuente de datos TheSportsDB (API pública V1 con clave '3').
Optimizada para capturar ligas y eventos femeninos vía strGender y whitelist oficial.
"""

import os
from datetime import datetime, timedelta, timezone

import utilidades as U

API_KEY = os.environ.get("THESPORTSDB_KEY", "3")
BASE = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"

_DEPORTE_TSDB = {
    "Soccer": "Soccer",
    "Basketball": "Basketball",
    "Handball": "Handball",
    "Ice Hockey": "Ice Hockey",
    "Volleyball": "Volleyball",
    "Rugby": "Rugby",
}

_KEYWORDS_FEM = [
    "women", "womens", "women's", "woman", "fem", "femenil", "femenino",
    "femenina", "feminin", "feminine", "femminile", "dames", "damen",
    "frauen", "ladies", "wta", "wnba", "nwsl", "wsl", "liga f", "damallsvenskan"
]

_cache_ligas = U.CacheTTL(12 * 3600)
_cache_eventos = U.CacheTTL(30 * 60)


def _es_liga_femenina(liga):
    """Detecta si la liga es femenina usando strGender o keywords en el nombre."""
    if not isinstance(liga, dict):
        return False

    # 1. Chequeo directo por el campo de género de la API
    genero = str(liga.get("strGender") or "").strip().lower()
    if genero in ("female", "women"):
        return True

    # 2. Chequeo por nombre y nombres alternativos
    texto = f"{liga.get('strLeague', '')} {liga.get('strLeagueAlternate', '')}".lower()
    return any(kw in texto for kw in _KEYWORDS_FEM)


def _obtener_ligas_femeninas(deporte_tsdb):
    cache_key = f"ligas_{deporte_tsdb}"
    hit, valor = _cache_ligas.get(cache_key)
    if hit:
        return valor

    url = f"{BASE}/all_leagues.php"
    data = U.get_json(url, "thesportsdb", timeout=15)

    ligas_femeninas = []
    if isinstance(data, dict):
        for liga in data.get("leagues", []) or []:
            sport = liga.get("strSport", "")
            if sport != deporte_tsdb:
                continue
            if _es_liga_femenina(liga):
                ligas_femeninas.append({
                    "id": liga.get("idLeague"),
                    "nombre": liga.get("strLeague", ""),
                })

    U.log(f"[thesportsdb/{deporte_tsdb}] {len(ligas_femeninas)} ligas femeninas encontradas")
    _cache_ligas.set(cache_key, ligas_femeninas)
    return ligas_femeninas


def _obtener_eventos_liga(liga_id, fecha_yyyymmdd):
    url = f"{BASE}/eventsday.php"
    params = {"d": fecha_yyyymmdd, "l": liga_id}
    data = U.get_json(url, "thesportsdb", params=params, timeout=10)
    if isinstance(data, dict):
        return data.get("events", []) or []
    return []


def _normalizar_evento(deporte, liga_nombre, evento):
    fecha_str = evento.get("strTimestamp") or evento.get("dateEvent")
    hora_str = evento.get("strTime") or ""

    start_ts = 0
    if fecha_str:
        try:
            if "T" in fecha_str:
                fecha_dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
            else:
                dt_completo = f"{fecha_str}T{hora_str or '00:00:00'}"
                fecha_dt = datetime.fromisoformat(dt_completo).replace(tzinfo=timezone.utc)
            start_ts = int(fecha_dt.timestamp())
        except Exception:
            pass

    estado_api = (evento.get("strStatus") or "").lower()
    if estado_api in ("", "not started", "ns"):
        tipo_estado = "pre"
        estado_txt = "Programado"
    elif "live" in estado_api or "progress" in estado_api:
        tipo_estado = "in"
        estado_txt = "En vivo"
    else:
        tipo_estado = "post"
        estado_txt = "Finalizado"

    try:
        score_local = int(evento.get("intHomeScore") or 0)
        score_visita = int(evento.get("intAwayScore") or 0)
    except (ValueError, TypeError):
        score_local = score_visita = None

    nom_loc = evento.get("strHomeTeam", "Local")
    nom_vis = evento.get("strAwayTeam", "Visitante")

    return {
        "id": f"thesportsdb_{evento.get('idEvent')}",
        "clave": U.clave_partido(nom_loc, nom_vis, start_ts),
        "deporte": deporte,
        "torneo": liga_nombre,
        "local": {
            "id": evento.get("idHomeTeam"),
            "nombre": nom_loc,
            "ranking": None,
            "fuera_ranking": False,
        },
        "visita": {
            "id": evento.get("idAwayTeam"),
            "nombre": nom_vis,
            "ranking": None,
            "fuera_ranking": False,
        },
        "horario": U.formatear_hora_arg(start_ts) if start_ts else "A confirmar",
        "tipo_estado": tipo_estado,
        "startTimestamp": start_ts,
        "fuente": "thesportsdb",
        "femenino_seguro": True,
        "score_local": score_local,
        "score_visita": score_visita,
    }


def obtener_eventos(deporte_interno):
    deporte_tsdb = _DEPORTE_TSDB.get(deporte_interno)
    if not deporte_tsdb:
        return []

    ligas = _obtener_ligas_femeninas(deporte_tsdb)
    if not ligas:
        return []

    hoy = datetime.now(timezone.utc)
    fechas = [hoy.strftime("%Y-%m-%d"), (hoy + timedelta(days=1)).strftime("%Y-%m-%d")]

    eventos_totales = []
    for liga in ligas[:10]:
        liga_id = liga["id"]
        liga_nombre = liga["nombre"]

        for fecha in fechas:
            eventos = _obtener_eventos_liga(liga_id, fecha)
            for ev in eventos:
                normalizado = _normalizar_evento(deporte_interno, liga_nombre, ev)
                if normalizado and normalizado["tipo_estado"] == "pre":
                    eventos_totales.append(normalizado)

    unicos = {ev["id"]: ev for ev in eventos_totales}
    return list(unicos.values())