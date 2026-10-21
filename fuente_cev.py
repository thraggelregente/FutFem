"""CEV Live Scores: usa su proxy público, sin extraer ni reutilizar claves internas."""
import os
import re
import time
from datetime import datetime, timedelta, timezone

import utilidades as U
from fuentes_publicas import Cliente, enteros, fechas_validas, instante_utc

FUENTE = "cev"
ACTIVO = os.environ.get("CEV_ACTIVO", "1") != "0"
_cache = U.CachePersistente("cev_v1", 6 * 3600, max_items=12)
cliente = Cliente(FUENTE, _cache)
presupuesto = cliente.presupuesto
_historial = []
_competiciones = {}
_tablas_ciclo = {}
_table_calls = 0
_estado_tablas = {"verified": 0, "rejected": 0}


def disponible():
    return ACTIVO


def respuesta_vigente(data):
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        return False
    ts = instante_utc((data.get("meta") or {}).get("CacheTime"))
    return bool(ts and -6 * 3600 <= time.time() - ts <= 24 * 3600)


def normalizar(raw, competiciones, ahora=None):
    ahora = time.time() if ahora is None else ahora
    if not isinstance(raw, dict) or not raw.get("MatchID"):
        return None
    torneo = competiciones.get(str(raw.get("CompetitionID")))
    # CEV Gender=0 significa mujeres; FIVB usa 1. Son esquemas distintos.
    if not torneo or torneo.get("Gender") != 0 or raw.get("MaleNotFemale") is not False:
        return None
    if raw.get("IsBeach") is not False or raw.get("IsSnow") is not False:
        return None  # no interpretar beach/snow como vóley indoor
    if re.search(r"\bbeach\b|\bsnow\b|\bBV\b", raw.get("CompetitionName", ""), re.I):
        return None  # discrepancia de modalidad en la respuesta
    if str(raw.get("SeasonID")) != str(torneo.get("SeasonID")):
        return None
    ts = instante_utc(raw.get("MatchDateTime_UTC"))
    if not fechas_validas(ts, torneo.get("DateFrom"), torneo.get("DateTo")):
        return None  # nunca sustituir por MatchDateTime local ni fecha 1900
    ids = enteros(raw.get("HomeTeamID"), raw.get("GuestTeamID"))
    na, nb = raw.get("HomeTeamName", ""), raw.get("GuestTeamName", "")
    if not ids or min(ids) <= 0 or ids[0] == ids[1] or not all(U.participante_definido(n) for n in (na, nb)):
        return None
    if any(re.search(r"seed\s*position|team\s*tbd", n, re.I) for n in (na, nb)):
        return None
    edades = re.findall(r"\bU[ -]?(\d{2})\b", torneo.get("CompetitionName", ""), re.I)
    sufijo = " U" + edades[0] if edades else ""
    contexto = f"cev:{raw['CompetitionID']}:{raw['SeasonID']}"
    comunes = {"deporte": "Volleyball", "fuente": FUENTE, "torneo": raw.get("CompetitionName"),
               "contexto_competicion": contexto, "historial_aislado": True, "femenino_seguro": True,
               "startTimestamp": ts, "cev_match_id": raw["MatchID"], "cev_group": raw.get("ChampionshipID"),
               "season_ref": raw.get("SeasonID"), "local": {"id": f"cev:{ids[0]}", "nombre": na + sufijo},
               "visita": {"id": f"cev:{ids[1]}", "nombre": nb + sufijo}}
    estado = str(raw.get("MatchStatusDescription", "")).lower()
    if raw.get("HomeDisqualification") or raw.get("GuestDisqualification") or any(k in estado for k in ("cancel", "postpon", "abandon", "forfeit")):
        return None
    scores = enteros(raw.get("WonSetHome"), raw.get("WonSetGuest"))
    if (raw.get("Finalized") is False and scores == (0, 0) and ahora < ts <= ahora + 86400
            and estado in ("scheduled", "not started", "fixture", "")):
        return dict(comunes, id="cev_" + str(raw["MatchID"]), tipo_estado="pre", horario=U.formatear_hora_arg(ts))
    if (raw.get("Finalized") is not True or estado not in ("complete", "completed", "finished")
            or not ahora - 90 * 86400 <= ts < ahora or not scores or max(scores) != 3 or min(scores) not in (0, 1, 2)):
        return None
    return dict(comunes, id="cev_" + str(raw["MatchID"]), _outcome_status="normal", fecha=U.ts_a_iso_utc(ts), id_local=comunes["local"]["id"],
                id_visita=comunes["visita"]["id"], nom_local=na + sufijo, nom_visita=nb + sufijo,
                puntos_local=scores[0], puntos_visita=scores[1])


def obtener_eventos(deporte):
    global _historial, _competiciones
    if deporte != "Volleyball" or not disponible():
        return []
    now = datetime.now(timezone.utc)
    desde, hasta = (now - timedelta(days=90)).strftime("%Y%m%d"), (now + timedelta(days=2)).strftime("%Y%m%d")
    comps = cliente.pedir("https://livescores.cev.eu/api/competitions", ttl=24 * 3600)
    data = cliente.pedir(f"https://livescores.cev.eu/api/matches/period/{desde}/{hasta}")
    if not respuesta_vigente(comps) or not respuesta_vigente(data):
        U.log("[cev] respuesta sin fecha de caché vigente; se omite")
        return []
    competiciones = {str(c["CompetitionID"]): c for c in comps.get("data", []) if isinstance(c, dict) and c.get("CompetitionID")}
    _competiciones = competiciones
    registros = [p for p in (normalizar(r, competiciones, now.timestamp()) for r in data.get("data", [])) if p]
    _historial = [p for p in registros if "fecha" in p]
    eventos = [p for p in registros if p.get("tipo_estado") == "pre"]
    U.log(f"[cev] {len(eventos)} próximos y {len(_historial)} resultados de competición/temporada verificada")
    return eventos


def historial_equipo(evento, lado):
    tid = (evento.get(lado) or {}).get("id")
    contexto = evento.get("contexto_competicion")
    return sorted((p for p in _historial if p.get("contexto_competicion") == contexto and
                   tid in (p["id_local"], p["id_visita"])), key=lambda p: p["fecha"], reverse=True)[:10]


def resultados_evaluacion(evento):
    """Reutiliza el listado verificado cargado por el calendario."""
    if evento.get("deporte") != 'Volleyball':
        return []
    from resultados_evaluacion import de_historial
    return [r for p in _historial if (r := de_historial(p, 'Volleyball', FUENTE))]


def iniciar_ciclo():
    global _table_calls
    _table_calls = 0
    _tablas_ciclo.clear()
    _estado_tablas.update(verified=0, rejected=0)


def normalizar_tabla(data, evento, competiciones, ahora=None):
    """Tabla de grupo oficial reconciliada con resultados de la misma edición."""
    ahora = time.time() if ahora is None else ahora
    if not isinstance(data, dict) or not isinstance(data.get("matches"), list) or not isinstance(data.get("standingGroups"), list):
        return None, 0
    if not all(isinstance(m, dict) for m in data['matches']+data['standingGroups']):
        return None, 0
    matches = [m for m in data["matches"] if str(m.get("MatchID")) == str(evento.get("cev_match_id"))]
    if len(matches) != 1:
        return None, 0
    target = normalizar(matches[0], competiciones, ahora)
    if not target or target.get("contexto_competicion") != evento.get("contexto_competicion") or target.get("startTimestamp") != evento.get("startTimestamp"):
        return None, 0
    if any(target[s]["id"] != evento[s]["id"] for s in ("local", "visita")):
        return None, 0
    group = evento.get("cev_group")
    groups = [g for g in data["standingGroups"] if str(g.get("championshipId")) == str(group)]
    if len(groups) != 1 or not isinstance(groups[0].get("rows"), list):
        return None, 0  # los cruces eliminatorios no tienen tabla de grupo
    history = {}
    for raw in data["matches"]:
        p = normalizar(raw, competiciones, ahora)
        if p and "fecha" in p and p["contexto_competicion"] == evento.get("contexto_competicion") and str(p.get("cev_group")) == str(group):
            history[p["id"]] = p
    tabla = {}
    for row in groups[0]["rows"]:
        if not isinstance(row, dict):
            return None, 0
        values = enteros(row.get("TeamID"), row.get("StandingPosition"), row.get("MatchesPlayed"),
                         row.get("MatchesWon"), row.get("MatchesLost"), row.get("SetsWon"), row.get("SetsLost"))
        if not values or min(values) < 0 or row.get("ChampionshipMethodID") != 1 or str(row.get("ChampionshipID")) != str(group):
            return None, 0
        tid, pos, played, won, lost, sw, sl = values
        key = "cev:" + str(tid)
        if not tid or not pos or key in tabla or played != won + lost or row.get("DisqualificationNotes"):
            return None, 0
        games = [p for p in history.values() if key in (p["id_local"], p["id_visita"])]
        wins = sum((p["puntos_local"] > p["puntos_visita"]) == (p["id_local"] == key) for p in games)
        diff = sum((p["puntos_local"]-p["puntos_visita"]) * (1 if p["id_local"] == key else -1) for p in games)
        if (wins, len(games)-wins, diff) != (won, lost, sw-sl):
            return None, 0
        tabla[key] = dict(posicion=pos, victorias=won, derrotas=lost, empates=0, dif_neta=sw-sl,
                          fuente=FUENTE, edicion=evento["contexto_competicion"], grupo=group)
    if len(tabla) < 2 or sorted(r["posicion"] for r in tabla.values()) != list(range(1, len(tabla)+1)):
        return None, 0
    return (tabla, len(tabla)) if all(evento[s]["id"] in tabla for s in ("local", "visita")) else (None, 0)


def tabla_partido(evento):
    global _table_calls
    if not disponible() or evento.get("fuente") != FUENTE or not evento.get("cev_match_id") or not evento.get("cev_group"):
        return None, 0
    context = evento.get("contexto_competicion") or ""
    comp = context.split(":")[1] if context.startswith("cev:") else ""
    if not comp.isdigit() or comp not in _competiciones:
        return None, 0
    url = f"https://livescores.cev.eu/api/competitions/{comp}/detail"
    if comp not in _tablas_ciclo:
        hit, _ = _cache.get((url, {}))
        if not hit and _table_calls >= 2:
            return None, 0
        _table_calls += int(not hit)
        _tablas_ciclo[comp] = cliente.pedir(url)
    tabla = normalizar_tabla(_tablas_ciclo[comp], evento, _competiciones)
    _estado_tablas["verified" if tabla[0] else "rejected"] += 1
    return tabla


def estado_contexto():
    return dict(_estado_tablas, table_requests_cycle=_table_calls)
