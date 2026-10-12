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
               "startTimestamp": ts, "local": {"id": f"cev:{ids[0]}", "nombre": na + sufijo},
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
    return dict(comunes, fecha=U.ts_a_iso_utc(ts), id_local=comunes["local"]["id"],
                id_visita=comunes["visita"]["id"], nom_local=na + sufijo, nom_visita=nb + sufijo,
                puntos_local=scores[0], puntos_visita=scores[1])


def obtener_eventos(deporte):
    global _historial
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
