"""
fuente_espn.py
ESPN (API pública, sin clave y sin cuota diaria): fuente principal del radar.
Cobertura multideporte femenino expandida (Fútbol, WNBA, NCAA, WTA).
"""

import os
import re
import time
from datetime import datetime, timedelta, timezone

import utilidades as U

BASE = "https://site.api.espn.com/apis/site/v2/sports"
FUENTE = "espn"
HORAS_VENTANA = 24
DIAS_HISTORIAL = int(os.environ.get("ESPN_HIST_DIAS", "45"))

# Ligas femeninas verificadas en la API de ESPN
LIGAS = {
    "Soccer": {
        "eng.w.1": "Women's Super League (Inglaterra)",
        "usa.nwsl": "NWSL (EE.UU.)",
        "esp.w.1": "Liga F (España)",
        "fra.w.1": "Première Ligue (Francia)",
        "ned.w.1": "Vrouwen Eredivisie (Países Bajos)",
        "aus.w.1": "A-League Women (Australia)",
        "ger.w.1": "Frauen-Bundesliga (Alemania)",
        "ita.w.1": "Serie A Femminile (Italia)",
        "mex.w.1": "Liga MX Femenil (México)",
        "bra.w.1": "Brasileirão Feminino (Brasil)",
        "uefa.wchampions": "UEFA Women's Champions League",
        "fifa.wwc": "Copa Mundial Femenina",
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
}

_DEPORTE_ESPN = {"Soccer": "soccer", "Basketball": "basketball", "Ice Hockey": "hockey", "Tennis": "tennis"}
_SPORT_A_INTERNO = {v: k for k, v in _DEPORTE_ESPN.items()}

_RE_SLUG_FEM = re.compile(r"(\.w\.|nwsl|wchampions|\.wwc|shebelieves|womens|wnba|wta)", re.I)
_ESTADOS_NO_JUGADOS = ("POSTPONED", "CANCELED", "CANCELLED", "SUSPENDED", "ABANDONED", "DELAYED", "FORFEIT")

_cache_proximos = U.CacheTTL(20 * 60)
_cache_dia_pasado = U.CacheTTL(24 * 3600)
_cache_historial = U.CacheTTL(6 * 3600)
_cache_ranking = U.CacheTTL(12 * 3600)


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
    cache.set(clave, data)
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
    }


def ranking_wta():
    hit, valor = _cache_ranking.get("wta")
    if hit:
        return valor
    data = U.get_json(f"{BASE}/tennis/wta/rankings", FUENTE, timeout=12)
    mapa = {}
    try:
        for r in (data or {}).get("rankings", [])[0].get("ranks", []) or []:
            ath = r.get("athlete") or {}
            pos = _entero(r.get("current"))
            if ath.get("id") is not None and pos:
                mapa[str(ath["id"])] = pos
    except Exception:
        mapa = {}
    _cache_ranking.set("wta", mapa)
    return mapa


def _jugadora(c, ranking):
    ath = c.get("athlete") or {}
    pid = c.get("id") or ath.get("guid")
    nombre = ath.get("displayName") or ath.get("fullName")
    if not nombre or pid is None:
        return None
    pid = str(pid)
    rk = _entero((c.get("curatedRank") or {}).get("current")) or ranking.get(pid)
    return {"id": pid, "nombre": nombre, "ranking": rk, "fuera_ranking": bool(ranking) and rk is None}


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
            data = _scoreboard(sport, slug, fecha, _cache_proximos)
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
    rango = f"{desde}-{hasta}"
    for limite in (1000, None):
        data = _scoreboard(sport, slug, rango, _cache_dia_pasado, limit=limite)
        eventos = (data or {}).get("events") or []
        if eventos:
            return eventos
    U.log(f"[espn] {slug}: el rango de fechas no devolvió datos; pido día por día ({DIAS_HISTORIAL} pedidos)")
    todos = []
    for d in range(1, DIAS_HISTORIAL + 1):
        data = _scoreboard(sport, slug, _fecha_utc(-d), _cache_dia_pasado)
        todos.extend((data or {}).get("events") or [])
        time.sleep(0.15)
    return todos


def _historial_liga(sport, slug):
    clave = (sport, slug)
    hit, valor = _cache_historial.get(clave)
    if hit:
        return valor

    por_equipo, vistos = {}, set()
    for e in _eventos_pasados(sport, slug):
        try:
            p = _partido_terminado(e)
        except Exception:
            continue
        if not p or p["_id"] in vistos:
            continue
        vistos.add(p["_id"])
        for tid in (p["id_local"], p["id_visita"]):
            por_equipo.setdefault(tid, []).append(p)
    for lista in por_equipo.values():
        lista.sort(key=lambda p: p["fecha"], reverse=True)

    U.log(f"[espn] historial {slug}: {len(vistos)} partidos, {len(por_equipo)} equipos")
    _cache_historial.set(clave, por_equipo)
    return por_equipo


def historial_equipo(evento, lado):
    sport, slug = evento.get("liga_ref") or (None, None)
    if not sport or sport == "tennis":
        return []
    tid = (evento.get(lado) or {}).get("id")
    return _historial_liga(sport, slug).get(tid, [])