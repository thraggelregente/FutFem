"""
fuente_thesportsdb.py
Fuente TheSportsDB optimizada:
- Consulta eventos globales del día por deporte (/eventsday.php?d=...&s=Deporte).
- Aplica el filtro femenino unificado U.es_femenino (detecta Toppserien, Eredivisie Women, etc.).
"""

import os
from datetime import datetime, timedelta, timezone

import utilidades as U

API_KEY = os.environ.get("THESPORTSDB_KEY", "3")
BASE = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"

_DEPORTES_TSDB = {
    "Soccer": "Soccer",
    "Basketball": "Basketball",
    "Handball": "Handball",
    "Ice Hockey": "Ice Hockey",
    "Volleyball": "Volleyball",
    "Rugby": "Rugby",
}

_cache_eventos = U.CacheTTL(30 * 60)  # 30 minutos


def _obtener_eventos_deporte_fecha(deporte_tsdb, fecha_str):
    clave = (deporte_tsdb, fecha_str)
    hit, valor = _cache_eventos.get(clave)
    if hit:
        return valor

    url = f"{BASE}/eventsday.php"
    params = {"d": fecha_str, "s": deporte_tsdb}
    data = U.get_json(url, "thesportsdb", params=params, timeout=12)

    eventos = []
    if isinstance(data, dict):
        eventos = data.get("events") or []

    _cache_eventos.set(clave, eventos)
    return eventos


def _normalizar_evento(deporte_interno, ev):
    torneo = ev.get("strLeague") or ""
    nom_loc = ev.get("strHomeTeam") or "Local"
    nom_vis = ev.get("strAwayTeam") or "Visitante"

    # Filtro compartido: reconoce Toppserien, Frauen, W, Women, etc.
    if not U.es_femenino(torneo, nom_loc, nom_vis):
        return None

    fecha_str = ev.get("strTimestamp") or ev.get("dateEvent")
    hora_str = ev.get("strTime") or ""
    start_ts = 0

    if fecha_str:
        try:
            if "T" in fecha_str:
                dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
            else:
                dt_completo = f"{fecha_str}T{hora_str or '00:00:00'}"
                dt = datetime.fromisoformat(dt_completo).replace(tzinfo=timezone.utc)
            start_ts = int(dt.timestamp())
        except Exception:
            pass

    estado_raw = str(ev.get("strStatus") or "").lower()
    if estado_raw in ("", "not started", "ns", "scheduled", "time to be defined"):
        tipo_estado = "pre"
    elif "live" in estado_raw or "progress" in estado_raw:
        tipo_estado = "in"
    else:
        tipo_estado = "post"

    return {
        "id": f"thesportsdb_{ev.get('idEvent')}",
        "clave": U.clave_partido(nom_loc, nom_vis, start_ts),
        "deporte": deporte_interno,
        "torneo": torneo,
        "local": {
            "id": str(ev.get("idHomeTeam") or nom_loc),
            "nombre": nom_loc,
            "ranking": None,
            "fuera_ranking": False,
        },
        "visita": {
            "id": str(ev.get("idAwayTeam") or nom_vis),
            "nombre": nom_vis,
            "ranking": None,
            "fuera_ranking": False,
        },
        "horario": U.formatear_hora_arg(start_ts) if start_ts else "A confirmar",
        "tipo_estado": tipo_estado,
        "startTimestamp": start_ts,
        "fuente": "thesportsdb",
        "femenino_seguro": True,
    }


def obtener_eventos(deporte_interno):
    deporte_tsdb = _DEPORTES_TSDB.get(deporte_interno)
    if not deporte_tsdb:
        return []

    hoy = datetime.now(timezone.utc)
    fechas = [hoy.strftime("%Y-%m-%d"), (hoy + timedelta(days=1)).strftime("%Y-%m-%d")]

    eventos_encontrados = []
    for f in fechas:
        partidos = _obtener_eventos_deporte_fecha(deporte_tsdb, f)
        for ev in partidos:
            norm = _normalizar_evento(deporte_interno, ev)
            if norm and norm["tipo_estado"] == "pre":
                eventos_encontrados.append(norm)

    if eventos_encontrados:
        U.log(f"[thesportsdb/{deporte_interno}] {len(eventos_encontrados)} partidos femeninos capturados")

    unicos = {e["id"]: e for e in eventos_encontrados}
    return list(unicos.values())