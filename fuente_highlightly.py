"""
fuente_highlightly.py
Fuente de datos de Highlightly (https://highlightly.net/).

Plan gratuito: límite de requests diarios (consultar dashboard).
Requiere API key: variable de entorno HIGHLIGHTLY_API_KEY.

Endpoints útiles:
- /v1/football/matches       -> Partidos del día
- /v1/football/h2h           -> Head-to-head
- /v1/football/standings     -> Tabla de posiciones
"""

import os
from datetime import datetime, timezone

import utilidades as U

API_KEY = os.environ.get("HIGHLIGHTLY_API_KEY")
BASE = "https://sports.highlightly.net"

# Mapeo de nuestros deportes internos a los de Highlightly
_DEPORTES_HL = {
    "Soccer": "football",
    "Basketball": "basketball",
    "Ice Hockey": "hockey",
    "Handball": "handball",
    "Volleyball": "volleyball",
    "Rugby": "rugby",
}

_cache_h2h = U.CacheTTL(6 * 3600)
_cache_tabla = U.CacheTTL(6 * 3600)


def _headers():
    return {
        "x-api-key": API_KEY,
        "Accept": "application/json",
    }


def obtener_h2h(equipo_local_id, equipo_visita_id, deporte="Soccer"):
    """
    Obtiene el H2H entre dos equipos.
    Devuelve lista de enfrentamientos o [].
    """
    if not API_KEY:
        return []

    deporte_hl = _DEPORTES_HL.get(deporte)
    if not deporte_hl:
        return []

    clave = f"{deporte_hl}|{equipo_local_id}|{equipo_visita_id}"
    hit, valor = _cache_h2h.get(clave)
    if hit:
        return valor

    url = f"{BASE}/v1/{deporte_hl}/h2h"
    params = {
        "team1": equipo_local_id,
        "team2": equipo_visita_id,
    }

    data = U.get_json(url, "highlightly", headers=_headers(), params=params, timeout=10)
    partidos = []
    if isinstance(data, dict):
        partidos = data.get("data", []) or []

    _cache_h2h.set(clave, partidos)
    return partidos


def obtener_tabla(liga_id, temporada, deporte="Soccer"):
    """
    Obtiene la tabla de posiciones de una liga.
    """
    if not API_KEY:
        return []

    deporte_hl = _DEPORTES_HL.get(deporte)
    if not deporte_hl:
        return []

    clave = f"{deporte_hl}|{liga_id}|{temporada}"
    hit, valor = _cache_tabla.get(clave)
    if hit:
        return valor

    url = f"{BASE}/v1/{deporte_hl}/standings"
    params = {"leagueId": liga_id, "season": temporada}

    data = U.get_json(url, "highlightly", headers=_headers(), params=params, timeout=10)
    tabla = []
    if isinstance(data, dict):
        tabla = data.get("data", []) or []

    _cache_tabla.set(clave, tabla)
    return tabla


def obtener_forma_reciente(equipo_id, deporte="Soccer", limite=6):
    """
    Obtiene los últimos partidos de un equipo.
    """
    if not API_KEY:
        return []

    deporte_hl = _DEPORTES_HL.get(deporte)
    if not deporte_hl:
        return []

    url = f"{BASE}/v1/{deporte_hl}/teams/{equipo_id}/matches"
    params = {"limit": limite}

    data = U.get_json(url, "highlightly", headers=_headers(), params=params, timeout=10)
    partidos = []
    if isinstance(data, dict):
        partidos = data.get("data", []) or []

    return partidos[:limite]


def obtener_eventos(deporte_interno):
    """Highlightly no es fuente principal de eventos, solo profundidad."""
    return []