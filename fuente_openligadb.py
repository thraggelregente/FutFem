"""OpenLigaDB: fixtures y resultados de ligas femeninas de fútbol.

Fuente comunitaria sin API key ni cuota publicada. El acceso se limita a las ligas
que el operador incluye explícitamente en OPENLIGADB_WOMENS_LEAGUES; nunca se
intenta inferir el género a partir de equipos ambiguos.

Formato de configuración:
    OPENLIGADB_WOMENS_LEAGUES=ffb1:2026
    OPENLIGADB_WOMENS_LEAGUES=ffb1:2026,ffb2:2026

Cada pareja es shortcut:temporada. La lista por defecto de Render incluye la
Frauen-Bundesliga alemana de 2026, cuyo shortcut es ffb1. Ajustar la temporada
cuando cambie el calendario oficial.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from urllib.parse import quote

import utilidades as U

BASE = (os.environ.get("OPENLIGADB_BASE") or "https://api.openligadb.de").rstrip("/")
FUENTE = "openligadb"
VENTANA_HORAS = max(1, int(os.environ.get("OPENLIGADB_VENTANA_HORAS", "36")))
CACHE_MINUTOS = max(5, int(os.environ.get("OPENLIGADB_CACHE_MINUTOS", "120")))


def _config_ligas():
    resultado = []
    raw = (os.environ.get("OPENLIGADB_WOMENS_LEAGUES") or "ffb1:2026").strip()
    for elemento in re.split(r"[,;\n]+", raw):
        elemento = elemento.strip()
        if not elemento or ":" not in elemento:
            continue
        shortcut, season = (parte.strip() for parte in elemento.split(":", 1))
        if not shortcut or not season or not re.fullmatch(r"[A-Za-z0-9_-]{2,24}", shortcut):
            continue
        if not re.fullmatch(r"\d{4}(?:-\d{4})?", season):
            continue
        pareja = (shortcut.lower(), season)
        if pareja not in resultado:
            resultado.append(pareja)
    return resultado[:12]


_LIGAS = _config_ligas()
_cache = U.CacheTTL(CACHE_MINUTOS * 60)
_avisos = set()


def disponible():
    return bool(_LIGAS)


def _avisar_una_vez(clave, mensaje):
    if clave not in _avisos:
        _avisos.add(clave)
        U.log(mensaje)


def _timestamp(valor):
    if not valor:
        return 0
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (TypeError, ValueError, OverflowError):
        return 0


def _equipo(match, key):
    dato = match.get(key) or {}
    ident = dato.get("TeamId")
    nombre = dato.get("TeamName") or dato.get("ShortName")
    if ident is None or not nombre:
        return None
    return {"id": str(ident), "nombre": str(nombre)}


def _resultado_final(match):
    resultados = match.get("MatchResults") or []
    validos = []
    for resultado in resultados:
        if not isinstance(resultado, dict):
            continue
        try:
            pl = int(resultado.get("PointsTeam1"))
            pv = int(resultado.get("PointsTeam2"))
        except (TypeError, ValueError):
            continue
        validos.append((int(resultado.get("ResultOrderID") or 0), pl, pv))
    if not validos:
        return None, None
    _, pl, pv = max(validos, key=lambda x: x[0])
    return pl, pv


def _partidos_liga(shortcut, season):
    clave = (shortcut, season)
    hit, valor = _cache.get(clave)
    if hit:
        return valor
    url = f"{BASE}/getmatchdata/{quote(shortcut, safe='')}/{quote(season, safe='') }"
    datos = U.get_json(url, FUENTE, timeout=15)
    if not isinstance(datos, list):
        return None
    partidos = [m for m in datos if isinstance(m, dict)]
    _cache.set(clave, partidos)
    U.log(f"[openligadb] {shortcut}/{season}: {len(partidos)} partidos en caché")
    return partidos


def _normalizar(match, shortcut, season, now_ts):
    local = _equipo(match, "Team1")
    visita = _equipo(match, "Team2")
    if not local or not visita:
        return None
    ts = _timestamp(match.get("MatchDateTimeUTC"))
    if not ts or ts <= now_ts or ts > now_ts + VENTANA_HORAS * 3600:
        return None
    if bool(match.get("MatchIsFinished")):
        return None
    liga_nombre = str(match.get("LeagueName") or "Frauen-Bundesliga")
    # La competición proviene de la allowlist explícita de ligas femeninas.
    match_id = match.get("MatchID")
    if match_id is None:
        # Sin MatchID fiable no se puede deduplicar de forma segura.
        return None
    return {
        "id": f"openligadb_{match_id}",
        "clave": U.clave_partido(local["nombre"], visita["nombre"], ts),
        "deporte": "Soccer",
        "torneo": liga_nombre,
        "local": {"id": local["id"], "nombre": local["nombre"], "ranking": None, "fuera_ranking": False},
        "visita": {"id": visita["id"], "nombre": visita["nombre"], "ranking": None, "fuera_ranking": False},
        "horario": U.formatear_hora_arg(ts),
        "tipo_estado": "pre",
        "startTimestamp": ts,
        "fuente": FUENTE,
        "femenino_seguro": True,
        "liga_ref": (shortcut, season),
    }


def obtener_eventos(deporte_interno):
    if deporte_interno != "Soccer" or not disponible():
        return []
    now_ts = datetime.now(timezone.utc).timestamp()
    by_id = {}
    for shortcut, season in _LIGAS:
        matches = _partidos_liga(shortcut, season)
        if matches is None:
            _avisar_una_vez(("fallo", shortcut, season), f"[openligadb] sin datos para {shortcut}/{season}; se reintentará")
            continue
        for match in matches:
            ev = _normalizar(match, shortcut, season, now_ts)
            if ev:
                by_id[ev["id"]] = ev
    eventos = list(by_id.values())
    if eventos:
        U.log(f"[openligadb] {len(eventos)} partidos femeninos próximos capturados")
    return eventos


def obtener_forma_reciente(nombre_equipo, deporte="Soccer", limite=8, id_interno=None):
    """Recupera resultados completos de la misma allowlist; no busca ligas externas."""
    if deporte != "Soccer" or not disponible() or not nombre_equipo:
        return []
    objetivo = U.normalizar(nombre_equipo)
    now_ts = datetime.now(timezone.utc).timestamp()
    partidos = []
    for shortcut, season in _LIGAS:
        matches = _partidos_liga(shortcut, season)
        if matches is None:
            continue
        for match in matches:
            local = _equipo(match, "Team1")
            visita = _equipo(match, "Team2")
            if not local or not visita or not bool(match.get("MatchIsFinished")):
                continue
            n_local = U.normalizar(local["nombre"])
            n_visita = U.normalizar(visita["nombre"])
            es_local = n_local == objetivo or U.nombres_coinciden(nombre_equipo, local["nombre"])
            es_visita = n_visita == objetivo or U.nombres_coinciden(nombre_equipo, visita["nombre"])
            if not es_local and not es_visita:
                continue
            pl, pv = _resultado_final(match)
            ts = _timestamp(match.get("MatchDateTimeUTC"))
            if pl is None or pv is None or not ts or ts >= now_ts:
                continue
            id_local, id_visita = local["id"], visita["id"]
            if id_interno is not None:
                if es_local:
                    id_local = str(id_interno)
                if es_visita:
                    id_visita = str(id_interno)
            partidos.append({
                "fecha": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                "id_local": id_local,
                "nom_local": local["nombre"],
                "id_visita": id_visita,
                "nom_visita": visita["nombre"],
                "puntos_local": pl,
                "puntos_visita": pv,
            })
    partidos.sort(key=lambda p: p["fecha"], reverse=True)
    return partidos[:max(1, int(limite))]
