"""Conector opcional Big Balls Sports Data: WNBA, sin endpoints de mercados.

Contrato contrastado con el OpenAPI público. Falta comprobar acceso autenticado
con BBS_API_KEY del usuario; sin esa variable no realiza ninguna consulta.
"""
import os
import time
from datetime import datetime, timezone

import utilidades as U
from fuentes_publicas import enteros, instante_utc

FUENTE = "bbs"
API_KEY = os.environ.get("BBS_API_KEY", "").strip()
presupuesto = U.PresupuestoDiario("bbs_wnba", 250, reserva=0)
_cache = U.CachePersistente("bbs_wnba_v1", 6 * 3600, max_items=16)
_ritmo = U.RitmoPedidos(8, minimo_segundos=1)
_historial = []
_pausa = 0


def disponible():
    return bool(API_KEY)


def _get(params):
    global _pausa
    hit, data = _cache.get(params)
    if hit:
        return data
    if not disponible() or time.time() < _pausa or not presupuesto.puede_gastar():
        return None
    _ritmo.esperar()
    info = {}
    data = U.get_json("https://api.bigballsdata.com/v1/matches", FUENTE, params=params,
                      headers={"Authorization": "Bearer " + API_KEY}, info=info, timeout=25, reintentar=False)
    headers = {k.lower(): v for k, v in (info.get("headers") or {}).items()}
    try:
        # Solo el bucket diario: el Remaining genérico puede pertenecer al minuto.
        diario = int(headers.get("x-ratelimit-limit-day", 250))
        if diario in (250, 500):
            presupuesto.limite = diario
    except (ValueError, TypeError):
        pass
    presupuesto.registrar()
    if info.get("status") in (401, 403):
        _pausa = time.time() + 24 * 3600
    elif info.get("status") == 429:
        _pausa = time.time() + 3600
    if not isinstance(data, dict) or data.get("error"):
        _cache.set(params, None, ttl=3600)
        return None
    meta = data.get("meta") or {}
    edad = meta.get("cache_age_ms")
    if not isinstance(edad, (int, float)) or not 0 <= edad <= 24 * 3600 * 1000:
        _cache.set(params, None, ttl=3600)
        U.log("[bbs] respuesta sin edad de caché verificable; se omite")
        return None
    _cache.set(params, data)
    return data


def normalizar(raw, year, ahora=None):
    ahora = time.time() if ahora is None else ahora
    if raw.get("sport") != "basketball" or str(raw.get("league", "")).lower() != "wnba":
        return None
    if raw.get("time_precision") == "date":
        return None
    ts = instante_utc(raw.get("kickoff_utc"))
    if not ts or datetime.fromtimestamp(ts, timezone.utc).year != year:
        return None
    a, b = raw.get("home") or {}, raw.get("away") or {}
    if not a.get("id") or not b.get("id") or a["id"] == b["id"] or not raw.get("id"):
        return None
    if not all(U.participante_definido(j.get("name", "")) for j in (a, b)):
        return None
    comunes = {"deporte": "Basketball", "fuente": FUENTE, "torneo": "WNBA Women",
               "femenino_seguro": True, "contexto_competicion": f"bbs:wnba:{year}", "historial_aislado": True,
               "startTimestamp": ts, "local": {"id": "bbs:" + str(a["id"]), "nombre": a["name"]},
               "visita": {"id": "bbs:" + str(b["id"]), "nombre": b["name"]}}
    if raw.get("status") == "scheduled" and ahora < ts <= ahora + 86400:
        return dict(comunes, id="bbs_" + str(raw["id"]), tipo_estado="pre", horario=U.formatear_hora_arg(ts))
    score = raw.get("score") or {}
    scores = enteros(score.get("home"), score.get("away"))
    if (raw.get("status") != "finished" or not ahora - 90 * 86400 <= ts < ahora
            or not scores or min(scores) < 0 or scores[0] == scores[1]):
        return None
    return dict(comunes, fecha=U.ts_a_iso_utc(ts), id_local=comunes["local"]["id"], id_visita=comunes["visita"]["id"],
                nom_local=a["name"], nom_visita=b["name"], puntos_local=scores[0], puntos_visita=scores[1])


def obtener_eventos(deporte):
    global _historial
    if deporte != "Basketball" or not disponible():
        return []
    year = datetime.now(timezone.utc).year
    registros, vistos = [], set()
    for offset in (0, 200, 400):
        data = _get({"sport": "basketball", "league": "wnba", "season": year, "limit": 200, "offset": offset})
        rows = (data or {}).get("data")
        if not isinstance(rows, list):
            break
        ids = {str(r.get("id")) for r in rows if isinstance(r, dict)}
        if ids and ids <= vistos:
            U.log("[bbs] paginación repetida; cobertura incompleta, no se insiste")
            break
        vistos.update(ids)
        registros.extend(p for p in (normalizar(r, year) for r in rows if isinstance(r, dict)) if p)
        if len(rows) < 200:
            break
    _historial = [p for p in registros if "fecha" in p]
    return [p for p in registros if p.get("tipo_estado") == "pre"]


def historial_equipo(evento, lado):
    tid = (evento.get(lado) or {}).get("id")
    contexto = evento.get("contexto_competicion")
    return sorted((p for p in _historial if p.get("contexto_competicion") == contexto and
                   tid in (p["id_local"], p["id_visita"])), key=lambda p: p["fecha"], reverse=True)[:10]
