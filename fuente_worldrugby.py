"""Calendario oficial World Rugby: mujeres XV (WRU), separado de sevens y varones.

Contrato observado en el cliente público oficial de fixtures-results. Sin key ni
cuota comercial publicada: caché 6 h y tope propio, no promesa de cobertura total.
"""
import os
import re
import time
from datetime import datetime, timedelta, timezone

import utilidades as U
from fuentes_publicas import Cliente, enteros

FUENTE = "worldrugby"
ACTIVO = os.environ.get("WORLD_RUGBY_ACTIVO", "1") != "0"
BASE = "https://api.wr-rims-prod.pulselive.com/rugby/v3/match"
_cache = U.CachePersistente("worldrugby_v1", 6 * 3600, max_items=12)
cliente = Cliente(FUENTE, _cache, limite=30)
presupuesto = cliente.presupuesto
_historial = []


def disponible():
    return ACTIVO


def normalizar(raw, ahora=None):
    ahora = time.time() if ahora is None else ahora
    if not isinstance(raw, dict) or str(raw.get("sport", "")).lower() != "wru":
        return None
    eventos, equipos, hora = raw.get("events"), raw.get("teams"), raw.get("time")
    if not isinstance(eventos, list) or len(eventos) != 1 or not isinstance(eventos[0], dict):
        return None
    torneo = eventos[0]
    if torneo.get("sport") != "wru" or not torneo.get("id"):
        return None
    inicio, fin = torneo.get("start"), torneo.get("end")
    if not isinstance(inicio, dict) or not isinstance(fin, dict):
        return None
    if not all(isinstance(d.get("label"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["label"]) for d in (inicio, fin)):
        return None
    titulo = torneo.get("label", "")
    if not isinstance(titulo, str) or not titulo or re.search(r"\b(?:U[ -]?\d{2}|Under[ -]?\d{2})\b", titulo, re.I):
        return None  # Primera integración solo mayores; no inferir edad de selecciones ambiguas.
    if not isinstance(equipos, list) or len(equipos) != 2 or not all(isinstance(t, dict) for t in equipos):
        return None
    if not all(t.get("id") and U.participante_definido(t.get("name", "")) for t in equipos):
        return None
    if str(equipos[0]["id"]) == str(equipos[1]["id"]) or not raw.get("matchId") or not isinstance(hora, dict):
        return None
    try:
        millis, offset = hora.get("millis"), hora.get("gmtOffset")
        if isinstance(millis, bool) or isinstance(offset, bool) or not isinstance(millis, (float, int)) or not isinstance(offset, (float, int)) or not -14 <= offset <= 14:
            return None
        ts = millis / 1000
        f = datetime.fromtimestamp(ts, timezone.utc)
        dia_local = (f + timedelta(hours=offset)).date().isoformat()
        if hora.get("label") != dia_local:
            return None
        if inicio["label"] > dia_local or fin["label"] < dia_local:
            return None
    except (ValueError, OverflowError, OSError, TypeError):
        return None
    local = {"id": "wr:" + str(equipos[0]["id"]), "nombre": equipos[0]["name"]}
    visita = {"id": "wr:" + str(equipos[1]["id"]), "nombre": equipos[1]["name"]}
    comunes = {"fuente": FUENTE, "deporte": "Rugby", "torneo": titulo,
               "local": local, "visita": visita, "femenino_seguro": True, "historial_aislado": True,
               "contexto_competicion": "worldrugby:wru:" + str(torneo["id"]), "startTimestamp": int(ts)}
    if raw.get("status") in ("U", "UP") and ahora < ts <= ahora + 86400:
        if f.hour == 0 and f.minute == 0:
            return None  # No hay campo que confirme la precisión de una hora de medianoche.
        return dict(comunes, id="wr_" + str(raw["matchId"]), tipo_estado="pre", horario=U.formatear_hora_arg(ts))
    valores = raw.get("scores")
    if not isinstance(valores, list) or len(valores) != 2:
        return None
    puntos = enteros(*valores)
    if (raw.get("status") != "C" or raw.get("outcome") not in ("A", "B", "D")
            or not puntos or min(puntos) < 0 or puntos == (0, 0) or not ahora - 90 * 86400 <= ts < ahora):
        return None
    esperado = "A" if puntos[0] > puntos[1] else "B" if puntos[1] > puntos[0] else "D"
    if raw["outcome"] != esperado:
        return None
    return dict(comunes, fecha=U.ts_a_iso_utc(ts), id_local=local["id"], id_visita=visita["id"],
                nom_local=local["nombre"], nom_visita=visita["nombre"], puntos_local=puntos[0], puntos_visita=puntos[1])


def obtener_eventos(deporte):
    global _historial
    if deporte != "Rugby" or not disponible():
        return []
    hoy = datetime.now(timezone.utc).date()
    params = {"sport": "wru", "pageSize": 100, "startDate": (hoy - timedelta(days=90)).isoformat(),
              "endDate": (hoy + timedelta(days=2)).isoformat()}
    registros, vistos = {}, set()
    for pagina in range(4):
        data = cliente.pedir(BASE, dict(params, page=pagina))
        if not isinstance(data, dict) or not isinstance(data.get("content"), list):
            break
        info = data.get("pageInfo") or {}
        if info.get("page") != pagina:
            U.log("[worldrugby] página repetida/incorrecta; cobertura parcial")
            break
        filas = data["content"]
        ids = {str(r.get("matchId")) for r in filas if isinstance(r, dict)}
        if ids and ids <= vistos:
            break
        vistos.update(ids)
        for raw in filas:
            p = normalizar(raw)
            if p:
                registros[str(raw["matchId"])] = p
        total = info.get("numPages")
        if not isinstance(total, int) or total <= pagina + 1:
            break
        if pagina == 3:
            U.log("[worldrugby] límite de páginas: no se presume historial completo")
    _historial = [p for p in registros.values() if "fecha" in p]
    proximos = [p for p in registros.values() if p.get("tipo_estado") == "pre"]
    U.log(f"[worldrugby] {len(proximos)} próximos y {len(_historial)} resultados femeninos XV válidos")
    return proximos


def historial_equipo(evento, lado):
    tid = (evento.get(lado) or {}).get("id")
    return sorted((p for p in _historial if tid in (p["id_local"], p["id_visita"])
                   and p["contexto_competicion"] == evento.get("contexto_competicion")),
                  key=lambda p: p["fecha"], reverse=True)[:10]
