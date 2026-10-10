# ---------------------------------------------------------------------------
# H2H Y TABLAS (datos profundos para el motor de señales)
# ---------------------------------------------------------------------------
_cache_h2h = U.CacheTTL(6 * 3600)
_cache_tabla = U.CacheTTL(6 * 3600)
_cache_forma = U.CacheTTL(3 * 3600)


def obtener_h2h(equipo_local_id, equipo_visita_id, deporte="Soccer"):
    """
    Obtiene el H2H entre dos equipos vía /fixtures/headtohead.
    """
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
    """
    Obtiene la tabla de posiciones de una liga.
    """
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
    """
    Obtiene los últimos N partidos de un equipo.
    """
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