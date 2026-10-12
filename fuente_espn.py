"""
fuente_espn.py
ESPN (API pÃºblica, sin clave): fuente de RESPALDO y ranking WTA; nunca es el proveedor principal
(en main.py tiene la menor prioridad salvo en tenis, donde es la Ãºnica con ranking).
Ligas femeninas verificadas en producciÃ³n. Los fallos transitorios se cachean pocos minutos para
que una caÃ­da momentÃ¡nea no deje al radar sin calendario durante horas.
"""

import os
import re
import time
from datetime import datetime, timedelta, timezone

import libro_resultados as L
import utilidades as U

BASE = "https://site.api.espn.com/apis/site/v2/sports"
FUENTE = "espn"
HORAS_VENTANA = 24
DIAS_HISTORIAL = int(os.environ.get("ESPN_HIST_DIAS", "45"))

# Ligas verificadas contra la API en vivo
LIGAS = {
    "Soccer": {
        "eng.w.1": "Women's Super League (Inglaterra)",
        "usa.nwsl": "NWSL (EE.UU.)",
        "esp.w.1": "Liga F (EspaÃ±a)",
        "fra.w.1": "PremiÃ¨re Ligue (Francia)",
        "ned.w.1": "Vrouwen Eredivisie (PaÃ­ses Bajos)",
        "aus.w.1": "A-League Women (Australia)",
        "uefa.wchampions": "UEFA Women's Champions League",
    },
    "Basketball": {
        "wnba": "WNBA",
        "womens-college-basketball": "NCAA Women's Basketball",
    },
    "Ice Hockey": {
        "womens-college-hockey": "NCAA Women's Hockey",
    },
    "Tennis": {
        "wta": "WTA",
    },
    "Softball": {"college-softball": "NCAA Softball femenino"},
    "Lacrosse": {"womens-college-lacrosse": "NCAA Women's Lacrosse"},
    "Field Hockey": {"womens-college-field-hockey": "NCAA Women's Field Hockey"},
}

_DEPORTE_ESPN = {"Soccer": "soccer", "Basketball": "basketball", "Ice Hockey": "hockey", "Tennis": "tennis",
                 "Softball": "baseball", "Lacrosse": "lacrosse", "Field Hockey": "field-hockey"}
_SPORT_A_INTERNO = {v: k for k, v in _DEPORTE_ESPN.items()}

_RE_SLUG_FEM = re.compile(r"(\.w\.|nwsl|wchampions|\.wwc|shebelieves|womens|wnba|wta)", re.I)
_ESTADOS_NO_JUGADOS = ("POSTPONED", "CANCELED", "CANCELLED", "SUSPENDED", "ABANDONED", "DELAYED", "FORFEIT")

_cache_proximos = U.CachePersistente("espn_proximos", max(10, int(os.environ.get("ESPN_SCOREBOARD_CACHE_MINUTES", "180"))) * 60)
_cache_dia_pasado = U.CachePersistente("espn_pasados", 24 * 3600)
_cache_historial = U.CachePersistente("espn_historial", 6 * 3600)
_cache_ranking = U.CacheTTL(12 * 3600)
_cache_lesiones = U.CacheTTL(3 * 3600)
_lesiones_sin_soporte = {}  # (sport, slug) -> timestamp hasta el cual no se reintenta
TTL_FALLO = 5 * 60  # un error de red/HTTP se reintenta a los 5 minutos, no a las 3 horas


def _ligas_configuradas():
    ligas = {d: dict(v) for d, v in LIGAS.items()}
    extra = os.environ.get("ESPN_SLUGS_EXTRA", "")
    for par in filter(None, (x.strip() for x in extra.split(","))):
        if ":" not in par:
            continue
        sport, slug = (t.strip() for t in par.split(":", 1))
        interno = _SPORT_A_INTERNO.get(sport)
        if not interno:
            continue
        if not _RE_SLUG_FEM.search(slug):
            U.log(f"[espn] slug extra ignorado (no parece femenino): {slug}")
            continue
        ligas[interno].setdefault(slug, slug)
    return ligas


def _scoreboard(sport, slug, fechas, cache, limit=None):
    clave = (sport, slug, fechas, limit)
    hit, valor = cache.get(clave)
    if hit:
        return valor
    params = {"dates": fechas}
    if limit:
        params["limit"] = limit
    data = U.get_json(f"{BASE}/{sport}/{slug}/scoreboard", FUENTE, params=params, timeout=12)
    data = data if isinstance(data, dict) else None
    cache.set(clave, data, ttl=None if data is not None else TTL_FALLO)
    return data


def _fecha_utc(dias):
    return (datetime.now(timezone.utc) + timedelta(days=dias)).strftime("%Y%m%d")


def _iso_a_ts(texto):
    try:
        return int(datetime.fromisoformat(str(texto).replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def _entero(valor):
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def _equipo(c):
    team = c.get("team") or {}
    return {
        "id": str(team.get("id")) if team.get("id") is not None else None,
        "nombre": team.get("displayName") or team.get("name") or "?",
        "ranking": None,
        "fuera_ranking": False,
    }


def _normalizar_equipos(evento, deporte, slug, nombre_liga, ahora):
    comps = evento.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    cs = comp.get("competitors") or []
    if len(cs) < 2:
        return None
    local_c = next((c for c in cs if c.get("homeAway") == "home"), cs[0])
    visita_c = next((c for c in cs if c.get("homeAway") == "away"), cs[1])

    estado = ((comp.get("status") or evento.get("status") or {}).get("type") or {})
    if estado.get("state") != "pre":
        return None
    if comp.get("timeValid") is False or any(k in str(estado.get("name", "")).upper() for k in _ESTADOS_NO_JUGADOS):
        return None
    start = _iso_a_ts(evento.get("date"))
    if not start or start < ahora or start > ahora + HORAS_VENTANA * 3600:
        return None

    local, visita = _equipo(local_c), _equipo(visita_c)
    if not local["id"] or not visita["id"]:
        return None
    return {
        "id": f"espn_{evento.get('id')}",
        "clave": U.clave_partido(local["nombre"], visita["nombre"], start),
        "deporte": deporte,
        "torneo": nombre_liga,
        "local": local,
        "visita": visita,
        "horario": U.formatear_hora_arg(start),
        "tipo_estado": "pre",
        "startTimestamp": start,
        "fuente": FUENTE,
        "femenino_seguro": True,
        "liga_ref": (_DEPORTE_ESPN[deporte], slug),
        "season_ref": (evento.get("season") or {}).get("year"),
    }


_ranking_nombres = {}   # firma de nombre -> posiciÃ³n (segundo Ã­ndice por si los ids no coinciden)
_discrepancias = set()


def ranking_corte():
    """Ãšltima posiciÃ³n que trae la lista de ranking de ESPN (p. ej. 150): mÃ¡s allÃ¡ solo se sabe "rank > corte"."""
    mapa = ranking_wta()
    return max(mapa.values()) if mapa else None


_ranking_fecha = None
_ranking_nombres_completos = {}


def ranking_wta():
    global _ranking_fecha
    hit, valor = _cache_ranking.get("wta")
    if hit:
        return valor
    data = U.get_json(f"{BASE}/tennis/wta/rankings", FUENTE, timeout=12)
    mapa = {}
    nombres = {}
    completos = {}
    _ranking_fecha = None
    try:
        lista = next((x for x in (data or {}).get("rankings", []) if x.get("type") == "wta"), {})
        _ranking_fecha = lista.get("update")
        for r in lista.get("ranks", []) or []:
            ath = r.get("athlete") or {}
            pos = _entero(r.get("current"))
            if ath.get("id") is not None and pos:
                mapa[str(ath["id"])] = pos
                nombre = ath.get("displayName") or ath.get("fullName")
                if nombre:
                    completos[nombre] = pos
                if nombre and len(U.tokens_significativos(nombre)) >= 2:
                    nombres[U.firma_equipo(nombre)] = pos
    except Exception:
        mapa, nombres = {}, {}
    _ranking_nombres_completos.clear()
    _ranking_nombres_completos.update(completos)
    _ranking_nombres.clear()
    _ranking_nombres.update(nombres)
    if mapa:
        U.log(f"[espn] ranking WTA: {len(mapa)} jugadoras (top {max(mapa.values())}); ausencia significa ranking desconocido")
    # Un ranking vacÃ­o (fallo de ESPN) no se cachea 12 h: dejarÃ­a al tenis ciego medio dÃ­a.
    _cache_ranking.set("wta", mapa, ttl=None if mapa else TTL_FALLO * 2)
    return mapa


def _jugadora(c, ranking):
    ath = c.get("athlete") or {}
    pid = c.get("id") or ath.get("guid")
    nombre = ath.get("displayName") or ath.get("fullName")
    if not nombre or pid is None:
        return None
    pid = str(pid)
    # El ranking sale SOLO de la lista oficial de ESPN (por id y, si el id no figura, por nombre completo).
    # `curatedRank` NO es el ranking WTA: en las pruebas de tu reporte mostraba #8 para una jugadora #125
    # (es la posiciÃ³n dentro del cuadro/sembrado del torneo). Solo se guarda como semilla informativa.
    rk = ranking.get(pid)
    if rk is None and len(U.tokens_significativos(nombre)) >= 2:
        rk = _ranking_nombres.get(U.firma_equipo(nombre))
    curado = _entero((c.get("curatedRank") or {}).get("current"))
    if rk is not None and curado is not None and curado != rk and (pid, curado) not in _discrepancias:
        _discrepancias.add((pid, curado))
        U.log(f"[espn/tenis] {nombre}: ranking WTA #{rk} pero curatedRank={curado} (se usa #{rk}; curatedRank es la semilla del torneo)")
    corte = max(ranking.values()) if ranking else None
    return {"id": pid, "nombre": nombre, "ranking": rk, "semilla": curado,
            "fuera_ranking": False, "ranking_corte": None, "ranking_fecha": _ranking_fecha}


def _eventos_tenis(slug, nombre_liga, ahora):
    ranking = ranking_wta()
    eventos = []
    for fecha in (_fecha_utc(0), _fecha_utc(1)):
        data = _scoreboard("tennis", slug, fecha, _cache_proximos)
        for torneo in (data or {}).get("events", []) or []:
            for grupo in torneo.get("groupings", []) or []:
                nombre_grupo = ((grupo.get("grouping") or {}).get("displayName") or "").lower()
                if "double" in nombre_grupo or "doble" in nombre_grupo:
                    continue
                for comp in grupo.get("competitions", []) or []:
                    estado = ((comp.get("status") or {}).get("type") or {}).get("state")
                    cs = comp.get("competitors") or []
                    if estado != "pre" or len(cs) < 2:
                        continue
                    start = _iso_a_ts(comp.get("date") or comp.get("startDate"))
                    if not start or start < ahora or start > ahora + HORAS_VENTANA * 3600:
                        continue
                    j1, j2 = _jugadora(cs[0], ranking), _jugadora(cs[1], ranking)
                    if not j1 or not j2:
                        continue
                    ronda = (comp.get("round") or {}).get("displayName", "")
                    nombre = f"{torneo.get('name', nombre_liga)} {('- ' + ronda) if ronda else ''}".strip()
                    eventos.append({
                        "id": f"espn_{comp.get('id')}",
                        "clave": U.clave_partido(j1["nombre"], j2["nombre"], start),
                        "deporte": "Tennis",
                        "torneo": nombre,
                        "local": j1,
                        "visita": j2,
                        "horario": U.formatear_hora_arg(start),
                        "tipo_estado": "pre",
                        "startTimestamp": start,
                        "fuente": FUENTE,
                        "femenino_seguro": True,
                        "liga_ref": ("tennis", slug),
                    })
    return eventos


def obtener_eventos(deporte_interno):
    sport = _DEPORTE_ESPN.get(deporte_interno)
    ligas = _ligas_configuradas().get(deporte_interno, {})
    if not sport or not ligas:
        return []

    ahora = time.time()
    por_id = {}
    for slug, nombre_liga in ligas.items():
        if deporte_interno == "Tennis":
            for ev in _eventos_tenis(slug, nombre_liga, ahora):
                por_id[ev["id"]] = ev
            continue
        for fecha in (_fecha_utc(0), _fecha_utc(1)):
            data = _scoreboard(sport, slug, fecha, _cache_proximos,
                               limit=100 if deporte_interno in {"Softball", "Lacrosse", "Field Hockey"} else None)
            for e in (data or {}).get("events", []) or []:
                try:
                    ev = _normalizar_equipos(e, deporte_interno, slug, nombre_liga, ahora)
                except Exception as ex:
                    U.log(f"[espn] evento ilegible en {slug}: {type(ex).__name__}")
                    continue
                if ev:
                    por_id[ev["id"]] = ev
    return list(por_id.values())


def _partido_terminado(evento):
    comps = evento.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    tipo = ((comp.get("status") or evento.get("status") or {}).get("type") or {})
    nombre_estado = str(tipo.get("name", "")).upper()
    if not tipo.get("completed") or any(x in nombre_estado for x in _ESTADOS_NO_JUGADOS):
        return None
    cs = comp.get("competitors") or []
    if len(cs) < 2:
        return None
    local_c = next((c for c in cs if c.get("homeAway") == "home"), cs[0])
    visita_c = next((c for c in cs if c.get("homeAway") == "away"), cs[1])
    pl, pv = _entero(local_c.get("score")), _entero(visita_c.get("score"))
    if pl is None or pv is None:
        return None
    el, ev = _equipo(local_c), _equipo(visita_c)
    if not el["id"] or not ev["id"]:
        return None
    return {
        "fecha": str(evento.get("date", "")),
        "id_local": el["id"], "nom_local": el["nombre"],
        "id_visita": ev["id"], "nom_visita": ev["nombre"],
        "puntos_local": pl, "puntos_visita": pv,
        "_id": evento.get("id"),
    }


def _eventos_pasados(sport, slug):
    desde, hasta = _fecha_utc(-DIAS_HISTORIAL), _fecha_utc(0)
    if sport in {"baseball", "lacrosse", "field-hockey"}:
        # Estos scoreboards no aceptan todos los rangos/límites usados por fútbol.
        # El calendario del feed indica los días reales: máximo siete por barrido.
        data = _scoreboard(sport, slug, hasta, _cache_proximos, limit=100)
        if not data:
            return []
        fechas = {str(f)[:10].replace("-", "") for l in data.get("leagues", []) for f in l.get("calendar", [])}
        salida = []
        for fecha in sorted((f for f in fechas if desde <= f <= hasta), reverse=True)[:7]:
            dia = data if fecha == hasta else _scoreboard(sport, slug, fecha, _cache_dia_pasado, limit=100)
            salida.extend((dia or {}).get("events", []))
        return salida
    rango = f"{desde}-{hasta}"
    for limite in (1000, None):
        data = _scoreboard(sport, slug, rango, _cache_dia_pasado, limit=limite)
        if data is None:
            return []  # ESPN no respondiÃ³: no se dispara el barrido dÃ­a por dÃ­a (45 pedidos inÃºtiles)
        eventos = data.get("events") or []
        if eventos:
            return eventos
    # Fuera de temporada, un feed vacío no justifica 45 consultas. Usar solo
    # días de competición anunciados en el calendario, con máximo siete.
    calendario = {str(f)[:10].replace("-", "") for l in data.get("leagues", []) for f in l.get("calendar", [])}
    fechas = [f for f in calendario if desde <= f <= hasta]
    U.log(f"[espn] {slug}: rango vacío; respaldo en {min(7, len(fechas))} días anunciados")
    todos = []
    for fecha in sorted(fechas, reverse=True)[:7]:
        data = _scoreboard(sport, slug, fecha, _cache_dia_pasado)
        todos.extend((data or {}).get("events") or [])
        time.sleep(0.15)
    return todos


def _historial_liga(sport, slug, season=None):
    clave = (sport, slug, season)
    hit, valor = _cache_historial.get(clave)
    if hit:
        return valor

    por_equipo, vistos, unicos = {}, set(), []
    for e in _eventos_pasados(sport, slug):
        if season is not None and str((e.get("season") or {}).get("year")) != str(season):
            continue
        try:
            p = _partido_terminado(e)
        except Exception:
            continue
        if not p or p["_id"] in vistos:
            continue
        vistos.add(p["_id"])
        unicos.append(p)
        for tid in (p["id_local"], p["id_visita"]):
            por_equipo.setdefault(tid, []).append(p)
    for lista in por_equipo.values():
        lista.sort(key=lambda p: p["fecha"], reverse=True)

    if unicos and sport in _SPORT_A_INTERNO and _SPORT_A_INTERNO[sport] not in {"Softball", "Lacrosse", "Field Hockey"}:
        L.ingestar(_SPORT_A_INTERNO[sport], unicos, "espn")  # alimenta el libro (Elo e historial por nombre)
    U.log(f"[espn] historial {slug}: {len(vistos)} partidos, {len(por_equipo)} equipos")
    _cache_historial.set(clave, por_equipo, ttl=None if por_equipo else TTL_FALLO * 2)
    return por_equipo


def historial_equipo(evento, lado):
    sport, slug = evento.get("liga_ref") or (None, None)
    if not sport or sport == "tennis":
        return []
    tid = (evento.get(lado) or {}).get("id")
    return _historial_liga(sport, slug, evento.get("season_ref")).get(tid, [])


_cache_tablas = U.CachePersistente("espn_tablas", 6 * 3600)


def tabla_partido(evento):
    sport, slug = evento.get("liga_ref") or (None, None)
    if not sport or sport == "tennis":
        return None, 0
    hit, data = _cache_tablas.get((sport, slug))
    if not hit:
        data = U.get_json(f"https://site.api.espn.com/apis/v2/sports/{sport}/{slug}/standings", FUENTE, timeout=12)
        _cache_tablas.set((sport, slug), data, ttl=None if data else 3600)
    # Un JSON descargado hoy puede seguir conteniendo una tabla de otra temporada.
    season = evento.get("season_ref")
    temporada_tabla = (data or {}).get("season") or {}
    if (season is None or not isinstance(temporada_tabla, dict)
            or str(temporada_tabla.get("year")) != str(season)):
        return None, 0
    def grupos(nodo):
        if not isinstance(nodo, dict):
            return
        if nodo.get("standings"):
            yield nodo["standings"].get("entries", [])
        for hijo in nodo.get("children", []):
            yield from grupos(hijo)
    il, iv = str(evento["local"]["id"]), str(evento["visita"]["id"])
    for grupo in grupos(data):
        filas = {}
        for entrada in grupo:
            tid = str((entrada.get("team") or {}).get("id") or "")
            stats = {s.get("name"): s.get("value") for s in entrada.get("stats", [])}
            if stats.get("wins") is None or stats.get("losses") is None:
                continue
            filas[tid] = {"posicion": int(stats.get("rank") or 0), "victorias": int(stats["wins"]),
                          "empates": int(stats.get("ties") or stats.get("draws") or 0), "derrotas": int(stats["losses"]),
                          "dif_neta": int(stats.get("pointDifferential") or stats.get("differential") or 0)}
        if il in filas and iv in filas:
            return filas, len(filas)
    return None, 0


# ---------------------------------------------------------------------------
# BAJAS CONFIRMADAS (endpoint /injuries de ESPN, solo para las ligas configuradas)
# ---------------------------------------------------------------------------
def _slugs_lesiones():
    """ESPN_LESIONES_SLUGS = "basketball:wnba,hockey:..."; por defecto solo la WNBA."""
    resultado = {}
    for par in filter(None, (x.strip() for x in os.environ.get("ESPN_LESIONES_SLUGS", "basketball:wnba").split(","))):
        if ":" not in par:
            continue
        sport, slug = (t.strip() for t in par.split(":", 1))
        interno = _SPORT_A_INTERNO.get(sport)
        if interno and _RE_SLUG_FEM.search(slug):
            resultado.setdefault(interno, []).append((sport, slug))
    return resultado


def _lesiones_liga(sport, slug):
    """{firma_equipo: {"fuera": n, "dudosas": m}} o None si ESPN no expone el endpoint para esa liga."""
    clave = (sport, slug)
    if time.time() < _lesiones_sin_soporte.get(clave, 0):
        return None
    hit, valor = _cache_lesiones.get(clave)
    if hit:
        return valor
    info = {}
    data = U.get_json(f"{BASE}/{sport}/{slug}/injuries", FUENTE, timeout=12, info=info)
    if not isinstance(data, dict) or not isinstance(data.get("injuries"), list):
        # 404/formato distinto: se asume sin soporte por 24 h (no se reintenta en cada barrido)
        espera = 24 * 3600 if info.get("status") in (400, 404) or isinstance(data, dict) else TTL_FALLO
        _lesiones_sin_soporte[clave] = time.time() + espera
        U.log(f"[espn] sin datos de lesiones para {slug}; no se reintenta pronto")
        return None
    por_equipo = {}
    for equipo in data["injuries"]:
        if not isinstance(equipo, dict):
            continue
        nombre = equipo.get("displayName") or ""
        fuera = dudosas = 0
        for i in equipo.get("injuries") or []:
            estado = str((i or {}).get("status") or "").lower()
            if "out" in estado:
                fuera += 1
            elif any(x in estado for x in ("doubtful", "questionable", "day-to-day", "day to day")):
                dudosas += 1
        if nombre:
            por_equipo[U.firma_equipo(nombre)] = {"fuera": fuera, "dudosas": dudosas}
    _cache_lesiones.set(clave, por_equipo)
    return por_equipo


def lesiones_equipo(deporte_interno, nombre_equipo, inferir_cero=False):
    """
    Bajas de un equipo (por nombre) en las ligas configuradas del deporte, o None si no hay dato.
    `inferir_cero=True` (solo vÃ¡lido con nombres de ESPN) interpreta "el equipo no figura en un listado
    que sÃ­ trae a otros" como 0 bajas; con nombres de otro proveedor serÃ­a arriesgado y no se hace.
    """
    firma = U.firma_equipo(nombre_equipo or "")
    for sport, slug in _slugs_lesiones().get(deporte_interno, []):
        tabla = _lesiones_liga(sport, slug)
        if not tabla:
            continue
        if firma in tabla:
            return tabla[firma]
        # Ausencia en el feed no demuestra cero lesiones.
    return None
