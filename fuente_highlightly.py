"""
fuente_highlightly.py
Highlightly (https://highlightly.net/) — fuente COMPLEMENTARIA de datos profundos.

Qué aporta:
- H2H entre dos equipos por nombre.
- Historial reciente de un equipo (últimos partidos).
- Tabla de posiciones (si la liga la tiene).

Se usa SOLO cuando ESPN no tiene historial de ese equipo (por ejemplo, ligas que ESPN
no cubre). No es fuente de eventos: `obtener_eventos` devuelve [].

Requiere: HIGHLIGHTLY_API_KEY en las variables de entorno.
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

_cache_busqueda = U.CacheTTL(12 * 3600)   # búsqueda de equipo por nombre: 12h
_cache_h2h = U.CacheTTL(6 * 3600)
_cache_forma = U.CacheTTL(3 * 3600)


def _headers():
    return {"x-api-key": API_KEY, "Accept": "application/json"}


def disponible():
    return bool(API_KEY)


def _buscar_equipo(nombre, deporte="Soccer"):
    """
    Busca el ID de un equipo por nombre. Cachea el resultado 12h.
    Devuelve el ID o None.
    """
    if not API_KEY or not nombre:
        return None

    deporte_hl = _DEPORTES_HL.get(deporte)
    if not deporte_hl:
        return None

    clave = f"busq|{deporte_hl}|{U.normalizar(nombre)}"
    hit, valor = _cache_busqueda.get(clave)
    if hit:
        return valor

    url = f"{BASE}/v1/{deporte_hl}/teams"
    params = {"name": nombre}

    data = U.get_json(url, "highlightly", headers=_headers(), params=params, timeout=10)
    equipo_id = None
    if isinstance(data, dict):
        equipos = data.get("data", []) or []
        # Buscar el equipo más parecido por nombre
        for e in equipos:
            nom_e = e.get("name") or ""
            if U.nombres_coinciden(nombre, nom_e):
                equipo_id = e.get("id")
                break
        if equipo_id is None and equipos:
            equipo_id = equipos[0].get("id")

    _cache_busqueda.set(clave, equipo_id)
    return equipo_id


def obtener_h2h(nombre_local, nombre_visita, deporte="Soccer"):
    """
    Obtiene el H2H entre dos equipos por nombre.
    Devuelve lista de partidos en formato interno del radar:
    [{fecha, id_local, id_visita, puntos_local, puntos_visita}]
    """
    if not API_KEY:
        return []

    id_loc = _buscar_equipo(nombre_local, deporte)
    id_vis = _buscar_equipo(nombre_visita, deporte)
    if not id_loc or not id_vis:
        return []

    deporte_hl = _DEPORTES_HL.get(deporte)
    if not deporte_hl:
        return []

    clave = f"h2h|{deporte_hl}|{id_loc}|{id_vis}"
    hit, valor = _cache_h2h.get(clave)
    if hit:
        return valor

    url = f"{BASE}/v1/{deporte_hl}/h2h"
    params = {"team1": id_loc, "team2": id_vis}

    data = U.get_json(url, "highlightly", headers=_headers(), params=params, timeout=10)
    partidos = []
    if isinstance(data, dict):
        for p in data.get("data", []) or []:
            try:
                fecha = p.get("date") or ""
                marcador = p.get("score") or {}
                # Intentar extraer los goles/puntos
                pl = marcador.get("home")
                pv = marcador.get("away")
                if pl is None or pv is None:
                    continue
                # Determinar quién es local en el partido histórico
                home_team = p.get("homeTeam") or {}
                away_team = p.get("awayTeam") or {}
                id_home = home_team.get("id")
                id_away = away_team.get("id")
                # El motor espera id_local y id_visita REFERIDOS AL EVENTO ACTUAL
                # (id_loc = equipo actual local, id_vis = equipo actual visita)
                if id_home == id_loc:
                    id_local, id_visita = id_loc, id_vis
                    puntos_local, puntos_visita = pl, pv
                else:
                    id_local, id_visita = id_vis, id_loc
                    puntos_local, puntos_visita = pv, pl

                partidos.append({
                    "fecha": fecha,
                    "id_local": str(id_local),
                    "id_visita": str(id_visita),
                    "puntos_local": int(puntos_local),
                    "puntos_visita": int(puntos_visita),
                })
            except Exception:
                continue

    _cache_h2h.set(clave, partidos)
    return partidos


def obtener_forma_reciente(nombre_equipo, deporte="Soccer", limite=6):
    """
    Obtiene los últimos N partidos de un equipo por nombre.
    Devuelve formato interno del radar.
    """
    if not API_KEY:
        return []

    equipo_id = _buscar_equipo(nombre_equipo, deporte)
    if not equipo_id:
        return []

    deporte_hl = _DEPORTES_HL.get(deporte)
    if not deporte_hl:
        return []

    clave = f"forma|{deporte_hl}|{equipo_id}|{limite}"
    hit, valor = _cache_forma.get(clave)
    if hit:
        return valor

    url = f"{BASE}/v1/{deporte_hl}/teams/{equipo_id}/matches"
    params = {"limit": limite}

    data = U.get_json(url, "highlightly", headers=_headers(), params=params, timeout=10)
    partidos = []
    if isinstance(data, dict):
        for p in data.get("data", []) or []:
            try:
                home_team = p.get("homeTeam") or {}
                away_team = p.get("awayTeam") or {}
                marcador = p.get("score") or {}
                partidos.append({
                    "fecha": p.get("date") or "",
                    "id_local": str(home_team.get("id")),
                    "nom_local": home_team.get("name") or "?",
                    "id_visita": str(away_team.get("id")),
                    "nom_visita": away_team.get("name") or "?",
                    "puntos_local": marcador.get("home"),
                    "puntos_visita": marcador.get("away"),
                })
            except Exception:
                continue

    _cache_forma.set(clave, partidos)
    return partidos


def obtener_eventos(deporte_interno):
    """Highlightly NO es fuente de eventos. Solo profundidad."""
    return []


def es_femenino(evento):
    """No se usa: Highlightly no da eventos."""
    return False