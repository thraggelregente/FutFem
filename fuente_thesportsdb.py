"""
fuente_thesportsdb.py
Fuente de datos de TheSportsDB (https://www.thesportsdb.com/).

API V1 gratuita con clave "3" (para testing).
Documentación: https://www.thesportsdb.com/free_sports_api

Deportes soportados (con ligas femeninas):
- Soccer: múltiples ligas femeninas.
- Basketball: WNBA y otras.
- Ice Hockey: ligas femeninas.
- Handball: ligas femeninas.
- Volleyball: ligas femeninas.
- Rugby: ligas femeninas.

NOTA: TheSportsDB tiene menos cobertura que ESPN o API-Sports,
pero es un complemento útil para deportes menos cubiertos.
"""

import os
from datetime import datetime, timedelta, timezone

import utilidades as U

# Clave pública de testing (gratuita, sin registro)
API_KEY = os.environ.get("THESPORTSDB_KEY", "3")
BASE = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"

# Mapeo de nuestros deportes internos a los nombres de deporte en TheSportsDB
_DEPORTE_TSDB = {
    "Soccer": "Soccer",
    "Basketball": "Basketball",
    "Handball": "Handball",
    "Ice Hockey": "Ice Hockey",
    "Volleyball": "Volleyball",
    "Rugby": "Rugby",
}

# Palabras clave femeninas
_KEYWORDS_FEM = [
    "women", "womens", "women's", "woman",
    "fem", "femenil", "femenino", "femenina",
    "feminin", "feminine", "femminile",
    "dames", "damen", "frauen", "ladies",
    "wta", "wnba", "nwsl", "wsl",
    "kvinde", "damallsvenskan", "toppserien",
]

_KEYWORDS_MASC = [
    "atp", "challenger", "men", "mens", "men's",
    "nba", "nfl", "nhl", "mlb", "mls",
    "premier league", "la liga", "serie a",
]

# Cachés
_cache_ligas = U.CacheTTL(12 * 3600)   # 12h (las ligas cambian poco)
_cache_eventos = U.CacheTTL(30 * 60)   # 30 min


def _es_liga_femenina(nombre):
    """Determina si una liga es femenina."""
    if not nombre:
        return False
    texto = nombre.lower()
    if any(kw in texto for kw in _KEYWORDS_FEM):
        return True
    if any(kw in texto for kw in _KEYWORDS_MASC):
        return False
    return False


def _obtener_ligas_femeninas(deporte_tsdb):
    """
    Obtiene las ligas femeninas de un deporte.
    TheSportsDB tiene un endpoint /all_leagues.php que devuelve todas las ligas.
    """
    cache_key = f"ligas_{deporte_tsdb}"
    hit, valor = _cache_ligas.get(cache_key)
    if hit:
        return valor

    url = f"{BASE}/all_leagues.php"
    data = U.get_json(url, "thesportsdb", timeout=15)

    ligas_femeninas = []
    if isinstance(data, dict):
        for liga in data.get("leagues", []) or []:
            # El campo sport es "Soccer", "Basketball", etc.
            sport = liga.get("strSport", "")
            if sport != deporte_tsdb:
                continue
            nombre = liga.get("strLeague", "")
            if _es_liga_femenina(nombre):
                ligas_femeninas.append({
                    "id": liga.get("idLeague"),
                    "nombre": nombre,
                    "alternativo": liga.get("strLeagueAlternate", ""),
                })

    U.log(f"[thesportsdb/{deporte_tsdb}] {len(ligas_femeninas)} ligas femeninas encontradas")
    _cache_ligas.set(cache_key, ligas_femeninas)
    return ligas_femeninas


def _obtener_eventos_liga(liga_id, fecha_yyyymmdd):
    """
    Obtiene los eventos de una liga en una fecha (YYYY-MM-DD).
    TheSportsDB usa /eventsday.php con parámetros d (fecha) y l (liga).
    """
    url = f"{BASE}/eventsday.php"
    params = {"d": fecha_yyyymmdd, "l": liga_id}
    data = U.get_json(url, "thesportsdb", params=params, timeout=10)
    if isinstance(data, dict):
        return data.get("events", []) or []
    return []


def _normalizar_evento(deporte, liga_nombre, evento):
    """Normaliza un evento de TheSportsDB al formato interno."""
    fecha_str = evento.get("strTimestamp") or evento.get("dateEvent")
    hora_str = evento.get("strTime") or ""

    start_ts = 0
    if fecha_str:
        try:
            if "T" in fecha_str:
                fecha_dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
            else:
                # Formato "YYYY-MM-DD" + hora "HH:MM:SS"
                dt_completo = f"{fecha_str}T{hora_str or '00:00:00'}"
                fecha_dt = datetime.fromisoformat(dt_completo).replace(tzinfo=timezone.utc)
            start_ts = int(fecha_dt.timestamp())
        except Exception:
            pass

    # Determinar estado
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

    # Scores
    try:
        score_local = int(evento.get("intHomeScore") or 0)
        score_visita = int(evento.get("intAwayScore") or 0)
    except (ValueError, TypeError):
        score_local = score_visita = None

    return {
        "id": f"thesportsdb_{evento.get('idEvent')}",
        "deporte": deporte,
        "torneo": liga_nombre,
        "local": {
            "id": evento.get("idHomeTeam"),
            "nombre": evento.get("strHomeTeam", "Local"),
            "record": None,
            "ranking": None,
        },
        "visita": {
            "id": evento.get("idAwayTeam"),
            "nombre": evento.get("strAwayTeam", "Visitante"),
            "record": None,
            "ranking": None,
        },
        "horario": U.formatear_hora_arg(start_ts) if start_ts else "A confirmar",
        "estado": estado_txt,
        "tipo_estado": tipo_estado,
        "startTimestamp": start_ts,
        "fuente": "thesportsdb",
        "score_local": score_local,
        "score_visita": score_visita,
    }


def obtener_eventos(deporte_interno):
    """Función principal."""
    deporte_tsdb = _DEPORTE_TSDB.get(deporte_interno)
    if not deporte_tsdb:
        return []

    ligas = _obtener_ligas_femeninas(deporte_tsdb)
    if not ligas:
        return []

    fecha_hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fecha_manana = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

    eventos_totales = []
    # Limitar a las 5 ligas más importantes
    for liga in ligas[:5]:
        liga_id = liga["id"]
        liga_nombre = liga["nombre"]

        for fecha in (fecha_hoy, fecha_manana):
            eventos = _obtener_eventos_liga(liga_id, fecha)
            for ev in eventos:
                normalizado = _normalizar_evento(deporte_interno, liga_nombre, ev)
                if normalizado:
                    eventos_totales.append(normalizado)

    unicos = {ev["id"]: ev for ev in eventos_totales}
    return list(unicos.values())


def es_femenino(evento):
    """Verifica que el torneo sea femenino."""
    return _es_liga_femenina(evento.get("torneo", ""))