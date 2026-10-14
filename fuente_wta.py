"""Backend público oficial WTA usado por wtatennis.com, sin key privada.

Rutas y semántica comprobadas con el cliente oficial tournament-player-service.js
y tennis.js. No es un API con SLA; se limita el tráfico y se falla de forma explícita.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone

import ranking_wta as R
import utilidades as U

BASE = "https://api.wtatennis.com/tennis"
FUENTE = "wta"
ACTIVO = os.environ.get("WTA_API_ACTIVO", "1") != "0"
MAX_POR_CICLO = int(os.environ.get("WTA_API_MAX_POR_CICLO", "16"))
MAX_TORNEOS = int(os.environ.get("WTA_API_MAX_TORNEOS", "4"))
presupuesto = U.PresupuestoMultiple("wta_publica", mensual=os.environ.get("WTA_API_MES", "3000"),
                                    semanal=os.environ.get("WTA_API_SEMANA", "650"),
                                    diario=os.environ.get("WTA_API_DIA", "100"), reserva_mensual=100)
_cache = U.CachePersistente("wta_api_v1", 24 * 3600, max_items=192)
_ritmo = U.RitmoPedidos(8, minimo_segundos=0.5)
_ciclo = 0
_pausa = 0.0
_indice = {}
_partidos = []


def disponible():
    return ACTIVO and time.time() >= _pausa


def iniciar_ciclo():
    global _ciclo
    _ciclo = 0


def _get(ruta, params=None, ttl=24 * 3600):
    global _ciclo, _pausa
    clave = (ruta, params or {})
    hit, data = _cache.get(clave)
    if hit:
        return data
    if not disponible() or _ciclo >= MAX_POR_CICLO or not presupuesto.puede_gastar():
        return None
    _ritmo.esperar()
    _ciclo += 1
    info = {}
    data = U.get_json(BASE + ruta, FUENTE, params=params, timeout=20, info=info, reintentar=False)
    presupuesto.registrar(1)
    if info.get("status") in (403, 429):
        _pausa = time.time() + 6 * 3600
    if data is None:
        _cache.set(clave, None, ttl=3600)
    else:
        _cache.set(clave, data, ttl=ttl)
    return data


def _ts(valor):
    f = U._parsear_iso(valor)
    return int(f.timestamp()) if f else 0


def _entry(valor):
    return "WC" if str(valor or "").strip().upper() in {"WC", "W", "WILD CARD"} else str(valor or "").strip().upper()


def _jugadora(raw, lado):
    nombre = f"{raw.get('PlayerNameFirst' + lado, '')} {raw.get('PlayerNameLast' + lado, '')}".strip()
    pid = str(raw.get("PlayerID" + lado) or "")
    if not pid.isdigit() or not U.participante_definido(nombre):
        return None
    j = {"id": "wta:" + pid, "wta_id": pid, "nombre": nombre,
         "entry": _entry(raw.get("EntryType" + lado)), "entry_fuente": "WTA cuadro oficial",
         "pais": raw.get("PlayerCountry" + lado), "ranking": None, "fuera_ranking": False}
    _indice[R.clave_nombre(nombre)] = pid
    return j


def normalizar_evento(raw, torneo, ahora=None):
    ahora = time.time() if ahora is None else ahora
    if raw.get("DrawMatchType") != "S" or raw.get("MatchState") != "U":
        return None
    if raw.get("Unscheduled") or raw.get("isEstimatedStartTime"):
        return None  # no usar la hora artificial 23:59 como comienzo cierto
    ts = _ts(raw.get("MatchTimeStamp"))
    if not ahora < ts <= ahora + 24 * 3600:
        return None
    a, b = _jugadora(raw, "A"), _jugadora(raw, "B")
    if not a or not b or a["id"] == b["id"]:
        return None
    return {"id": f"wta_{raw.get('EventID')}_{raw.get('EventYear')}_{raw.get('MatchID')}",
            "local": a, "visita": b, "deporte": "Tennis", "fuente": FUENTE,
            "femenino_seguro": True, "tipo_estado": "pre", "startTimestamp": ts,
            "horario": U.formatear_hora_arg(ts), "torneo": torneo.get("title") or torneo["tournamentGroup"]["name"],
            "superficie": torneo.get("surface"), "nivel_torneo": torneo.get("level"),
            "wta_torneo": [torneo["tournamentGroup"]["id"], torneo["year"]]}


def obtener_eventos(deporte):
    global _partidos
    if deporte != "Tennis" or not ACTIVO:
        return []
    ahora = datetime.now(timezone.utc)
    desde, hasta = (ahora - timedelta(days=10)).date().isoformat(), (ahora + timedelta(days=4)).date().isoformat()
    data = _get("/tournaments", {"from": desde, "to": hasta, "pageSize": 100, "page": 0}, ttl=12 * 3600)
    if not isinstance(data, dict):
        return []
    torneos = [t for t in data.get("content", [])
               if t.get("startDate", "") <= hasta and t.get("endDate", "") >= ahora.date().isoformat()
               and (t.get("tournamentGroup") or {}).get("id") != 2084]  # United Cup contiene partidos masculinos
    if data.get("pageInfo", {}).get("numEntries", 0) > len(data.get("content", [])):
        U.log("[wta] calendario paginado/incompleto; se limita a la página validada")
    torneos.sort(key=lambda t: (t.get("startDate", "") > ahora.date().isoformat(),
                                t.get("level") == "ITF", t.get("startDate", "")))
    salida, observados = [], []
    for torneo in torneos[:MAX_TORNEOS]:
        grupo, year = torneo["tournamentGroup"]["id"], torneo["year"]
        datos = _get(f"/tournaments/{grupo}/{year}/matches", ttl=4 * 3600)
        if not isinstance(datos, dict):
            continue
        for raw in datos.get("matches", []):
            if raw.get("DrawMatchType") != "S":
                continue
            a, b = _jugadora(raw, "A"), _jugadora(raw, "B")
            if a and b:
                observados.append({"a": a, "b": b, "ts": _ts(raw.get("MatchTimeStamp")),
                                   "torneo": torneo, "estado": raw.get("MatchState")})
            evento = normalizar_evento(raw, torneo, ahora.timestamp())
            if evento:
                salida.append(evento)
    _partidos = observados
    U.log(f"[wta] {len(salida)} encuentros con horario fiable; {len(observados)} cruces para entry/superficie")
    return salida


def enriquecer(eventos):
    for ev in eventos:
        if ev.get("deporte") != "Tennis":
            continue
        nombres = {R.clave_nombre((ev.get(l) or {}).get("nombre", "")) for l in ("local", "visita")}
        for obs in _partidos:
            if obs["estado"] != "U" or {R.clave_nombre(obs[k]["nombre"]) for k in ("a", "b")} != nombres:
                continue
            if abs(obs["ts"] - ev.get("startTimestamp", 0)) > 48 * 3600:
                continue
            for lado in ("local", "visita"):
                j = ev[lado]
                otro = next(o for o in (obs["a"], obs["b"]) if R.clave_nombre(o["nombre"]) == R.clave_nombre(j["nombre"]))
                for campo in ("wta_id", "entry", "entry_fuente", "pais"):
                    j[campo] = otro[campo]
            ev["superficie"] = obs["torneo"].get("surface")
            ev["nivel_torneo"] = obs["torneo"].get("level")
            ev.setdefault("_fuentes_detectadas", [])
            if "wta" not in ev["_fuentes_detectadas"]:
                ev["_fuentes_detectadas"].append("wta")
            break


def resolver(nombre):
    key = R.clave_nombre(nombre)
    if key in _indice:
        return _indice[key]
    hit, pid = _cache.get(("identidad", key))
    if hit:
        return pid
    data = _get("/players", {"name": nombre, "pageSize": 20, "page": 0}, ttl=7 * 86400)
    if not isinstance(data, dict):
        return None
    candidatos = [p for p in data.get("content", []) if R.clave_nombre(p.get("fullName", "")) == key]
    pid = str(candidatos[0]["id"]) if len(candidatos) == 1 else None
    _cache.set(("identidad", key), pid, ttl=7 * 86400)
    return pid


def normalizar_historial(raw, pid):
    """El historial expresa el score desde la ganadora (cliente oficial tennis.js)."""
    if raw.get("s_d_flag") != "S" or str(raw.get("player_1")) != str(pid):
        return None
    if raw.get("reason_code") != "W" or raw.get("winner") not in (1, 2):
        return None  # walkovers, retiros, byes y defaults no miden dominio de juego
    sets = re.findall(r"(\d+)(?:\(\d+\))?\s*-\s*(\d+)(?:\(\d+\))?", raw.get("scores") or "")
    if len(sets) not in (2, 3) or not all(max(int(a), int(b)) >= 6 for a, b in sets):
        return None
    ts = _ts(raw.get("StartDate"))
    if not ts or ts > time.time():
        return None
    gf, gc = sum(int(a) for a, b in sets), sum(int(b) for a, b in sets)
    gano = raw["winner"] == 1
    torneo = raw.get("tournament") or {}
    return {"ts": ts, "gano": gano, "marcador_original": raw.get("scores"),
            "sets_desde_ganadora": [[int(a), int(b)] for a,b in sets], "estado_resultado": "normal", "juegos_favor": gf if gano else gc, "juegos_contra": gc if gano else gf,
            "superficie": str(raw.get("Surface") or "").title(), "rival": (raw.get("opponent") or {}).get("fullName"),
            "ranking_rival": raw.get("rank_2") if isinstance(raw.get("rank_2"), int) and raw["rank_2"] > 0 else None,
            "nivel": torneo.get("level") or raw.get("TournamentLevel"), "fecha_precision": "semana del torneo",
            "torneo": raw.get("tourn_nbr"), "round": raw.get("tourn_round"), "entry": _entry(raw.get("entry_type_1"))}


def perfil(jugadora):
    pid = jugadora.get("wta_id") or resolver(jugadora.get("nombre", ""))
    if not pid:
        return None
    jugadora["wta_id"] = pid
    year = datetime.now(timezone.utc).year
    filas, completo = [], True
    for anio in (year, year - 1):
        for pagina in range(3):
            data = _get(f"/players/{pid}/matches", {"year": anio, "type": "S", "pageSize": 100, "page": pagina}, ttl=24 * 3600)
            if not isinstance(data, dict) or str((data.get("player") or {}).get("id")) != str(pid):
                completo = False
                break
            matches = data.get("matches")
            if not isinstance(matches, list):
                completo = False
                break
            if any(str(m.get("tourn_year")) != str(anio) for m in matches):
                completo = False
                break  # filtro ignorado: no confundir la primera página de la carrera con forma reciente
            filas.extend(p for p in (normalizar_historial(m, pid) for m in matches) if p)
            if len(matches) < 100:
                break
        else:
            completo = False
    vistos = {(p["torneo"], p["ts"], p["round"], p["rival"]): p for p in filas}
    filas = sorted(vistos.values(), key=lambda p: p["ts"], reverse=True)
    # El summary ayuda a evitar confundir a una ex top con una debutante tras inactividad.
    datos = _get(f"/players/{pid}/performance", ttl=7 * 86400)
    summary = datos.get("summary") if isinstance(datos, dict) else None
    carrera = None
    mejor_rank = None
    if isinstance(summary, dict):
        w, l = summary.get("Singles_Career_Wins"), summary.get("Singles_Career_Losses")
        if isinstance(w, (int, float)) and isinstance(l, (int, float)):
            carrera = int(w + l)
        mejor_rank = summary.get("highest_rank")
    servicio = None
    # Estadísticas opcionales solo para WC con muestra previa, no una consulta por cada jugadora.
    if jugadora.get("entry") == "WC" and len(filas) >= 5 and presupuesto.puede_gastar(3):
        stats_data = _get(f"/players/{pid}/year/{year}", ttl=24 * 3600)
        stats = stats_data.get("stats") if isinstance(stats_data, dict) else None
        if isinstance(stats, dict) and isinstance(stats.get("MatchCount"), (int, float)) and stats["MatchCount"] >= 5:
            dobles = stats.get("Double_Faults")
            if isinstance(dobles, (int, float)):
                servicio = {"partidos": int(stats["MatchCount"]), "dobles_faltas_por_partido": round(dobles / stats["MatchCount"], 2)}
    reciente = [p for p in filas if p["ts"] >= time.time() - 120 * 86400][:10]
    return {"id": pid, "fuente": "WTA historial oficial", "partidos": filas, "recientes": reciente,
            "cobertura_completa_2anios": completo, "muestras_2anios": len(filas),
            "experiencia_carrera_wta": carrera, "mejor_ranking": mejor_rank,
            "servicio": servicio,
            "sin_resultados_registrados": completo and carrera == 0 and not filas,
            "actualizado_utc": datetime.now(timezone.utc).isoformat()}
