"""
fuente_oddspapi.py
Fuente de datos de OddsPapi (https://oddspapi.io/).

Plan gratuito: límite de requests diarios.
Requiere API key: variable de entorno ODDSPAPI_API_KEY.
"""

import os
from datetime import datetime, timezone

import utilidades as U

API_KEY = os.environ.get("ODDSPAPI_API_KEY")
BASE = "https://api.oddspapi.io"

_cache_h2h = U.CacheTTL(6 * 3600)
_cache_cuotas = U.CacheTTL(15 * 60)


def _headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
    }


def obtener_h2h(equipo_local, equipo_visita, deporte="Soccer"):
    """
    Obtiene H2H desde OddsPapi.
    """
    if not API_KEY:
        return []

    clave = f"h2h|{equipo_local}|{equipo_visita}"
    hit, valor = _cache_h2h.get(clave)
    if hit:
        return valor

    url = f"{BASE}/v1/h2h"
    params = {"home": equipo_local, "away": equipo_visita, "sport": deporte.lower()}

    data = U.get_json(url, "oddspapi", headers=_headers(), params=params, timeout=10)
    partidos = []
    if isinstance(data, dict):
        partidos = data.get("matches", []) or []

    _cache_h2h.set(clave, partidos)
    return partidos


def obtener_cuotas(evento_id):
    """
    Obtiene las cuotas de un evento.
    """
    if not API_KEY or not evento_id:
        return {}

    clave = f"cuotas|{evento_id}"
    hit, valor = _cache_cuotas.get(clave)
    if hit:
        return valor

    url = f"{BASE}/v1/odds"
    params = {"eventId": evento_id}

    data = U.get_json(url, "oddspapi", headers=_headers(), params=params, timeout=10)
    cuotas = {}
    if isinstance(data, dict):
        cuotas = data.get("odds", {}) or {}

    _cache_cuotas.set(clave, cuotas)
    return cuotas


def obtener_eventos(deporte_interno):
    """OddsPapi no es fuente principal de eventos."""
    return []