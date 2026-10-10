"""
fuente_oddspapi.py
OddsPapi (https://oddspapi.io/) — fuente COMPLEMENTARIA de H2H.

Qué aporta:
- H2H entre dos equipos por nombre (plan free permite un número limitado de requests).

Se usa SOLO cuando ESPN y Highlightly no dan H2H.

Requiere: ODDSPAPI_API_KEY en las variables de entorno.
"""

import os
from datetime import datetime, timezone

import utilidades as U

API_KEY = os.environ.get("ODDSPAPI_API_KEY")
BASE = "https://api.oddspapi.io"

_cache_h2h = U.CacheTTL(6 * 3600)


def _headers():
    return {"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}


def disponible():
    return bool(API_KEY)


def obtener_h2h(nombre_local, nombre_visita, deporte="Soccer"):
    """
    Obtiene H2H entre dos equipos por nombre.
    Devuelve lista en formato interno del radar.
    """
    if not API_KEY:
        return []

    clave = f"h2h|{U.normalizar(nombre_local)}|{U.normalizar(nombre_visita)}"
    hit, valor = _cache_h2h.get(clave)
    if hit:
        return valor

    url = f"{BASE}/v1/h2h"
    params = {
        "home": nombre_local,
        "away": nombre_visita,
        "sport": deporte.lower(),
    }

    data = U.get_json(url, "oddspapi", headers=_headers(), params=params, timeout=10)
    partidos = []
    if isinstance(data, dict):
        for p in data.get("matches", []) or []:
            try:
                # El formato varía; intentamos adaptarlo
                fecha = p.get("date") or p.get("startTime") or ""
                home = p.get("home") or p.get("homeTeam") or {}
                away = p.get("away") or p.get("awayTeam") or {}
                score = p.get("score") or {}
                # Intentar varias estructuras
                id_loc = home.get("id") if isinstance(home, dict) else None
                id_vis = away.get("id") if isinstance(away, dict) else None
                pl = score.get("home") if isinstance(score, dict) else None
                pv = score.get("away") if isinstance(score, dict) else None
                if pl is None or pv is None:
                    continue
                partidos.append({
                    "fecha": fecha,
                    "id_local": str(id_loc) if id_loc else None,
                    "id_visita": str(id_vis) if id_vis else None,
                    "puntos_local": int(pl),
                    "puntos_visita": int(pv),
                })
            except Exception:
                continue

    _cache_h2h.set(clave, partidos)
    return partidos


def obtener_cuotas(evento_id):
    """No implementado por ahora."""
    return {}


def obtener_eventos(deporte_interno):
    """OddsPapi NO es fuente de eventos."""
    return []


def es_femenino(evento):
    return False