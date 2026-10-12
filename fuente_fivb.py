"""FIVB VIS: vóley femenino público, fechas UTC y torneos verificados por fila."""
import os
import re
import time
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET

import utilidades as U
from fuentes_publicas import Cliente, enteros, fechas_validas, instante_utc, xml_seguro

FUENTE = "fivb"
ACTIVO = os.environ.get("FIVB_ACTIVO", "1") != "0"
_cache = U.CachePersistente("fivb_v1", 6 * 3600, max_items=8)
cliente = Cliente(FUENTE, _cache)
presupuesto = cliente.presupuesto
_historial = []


def disponible():
    return ACTIVO


def normalizar(nodo, ahora=None):
    ahora = time.time() if ahora is None else ahora
    raw, torneo = nodo.attrib, nodo.find("Tournament")
    if not str(raw.get("No", "")).isdigit() or not str(raw.get("NoTournament", "")).isdigit():
        return None
    if torneo is None or torneo.get("Gender") not in ("1", "W"):
        return None  # nunca confiar solamente en TournamentGenders del pedido
    torneo = torneo.attrib
    if torneo.get("No") != raw.get("NoTournament"):
        return None
    ts = instante_utc(raw.get("DateTimeUtc"))
    if not fechas_validas(ts, torneo.get("StartDate"), torneo.get("EndDate")):
        return None
    nums = enteros(raw.get("NoTeamA"), raw.get("NoTeamB"), raw.get("Status"))
    if not nums or min(nums[:2]) <= 0 or nums[0] == nums[1]:
        return None
    na, nb = raw.get("TeamAName", ""), raw.get("TeamBName", "")
    if not all(U.participante_definido(n) for n in (na, nb)):
        return None
    # El nombre del país puede ser idéntico en mayores y juveniles.
    edades = re.findall(r"\bU[ -]?(\d{2})\b", torneo.get("Name", ""), re.I)
    sufijo = " U" + edades[0] if edades else ""
    contexto = f"fivb:{raw.get('NoTournament')}"
    comunes = {"deporte": "Volleyball", "fuente": FUENTE, "contexto_competicion": contexto,
               "historial_aislado": True, "torneo": torneo.get("Name", "Vóley femenino FIVB"),
               "femenino_seguro": True, "startTimestamp": ts,
               "local": {"id": f"fivb:{nums[0]}", "nombre": na + sufijo},
               "visita": {"id": f"fivb:{nums[1]}", "nombre": nb + sufijo}}
    if 1 <= nums[2] <= 4 and ahora < ts <= ahora + 86400:
        return dict(comunes, id="fivb_" + raw["No"], tipo_estado="pre", horario=U.formatear_hora_arg(ts))
    scores = enteros(raw.get("MatchPointsA"), raw.get("MatchPointsB"))
    if (nums[2] not in (24, 25, 26, 27) or not ahora - 90 * 86400 <= ts < ahora
            or not scores or max(scores) != 3 or min(scores) not in (0, 1, 2)
            or raw.get("ResultType") != "0"):
        return None
    return dict(comunes, fecha=U.ts_a_iso_utc(ts), id_local=comunes["local"]["id"],
                id_visita=comunes["visita"]["id"], nom_local=na + sufijo, nom_visita=nb + sufijo,
                puntos_local=scores[0], puntos_visita=scores[1])


def obtener_eventos(deporte):
    global _historial
    if deporte != "Volleyball" or not disponible():
        return []
    now = datetime.now(timezone.utc)
    desde, hasta = (now - timedelta(days=90)).date().isoformat(), (now + timedelta(days=2)).date().isoformat()
    req = ET.Element("Request", Type="GetVolleyMatchList", Fields="No NoTournament DateTimeUtc Status TeamAName TeamBName NoTeamA NoTeamB MatchPointsA MatchPointsB ResultType")
    ET.SubElement(req, "Filter", FirstDate=desde, LastDate=hasta, TournamentGenders="W")
    ET.SubElement(req, "Relation", Name="Tournament", Fields="Name Gender StartDate EndDate")
    texto = cliente.pedir("https://www.fivb.org/Vis2009/XmlRequest.asmx", {"Request": ET.tostring(req, encoding="unicode")}, xml=True)
    root = xml_seguro(texto)
    if root is None or root.tag != "VolleyballMatches":
        return []
    registros = [p for p in (normalizar(n, now.timestamp()) for n in root) if p]
    _historial = [p for p in registros if "fecha" in p]
    eventos = [p for p in registros if p.get("tipo_estado") == "pre"]
    U.log(f"[fivb] {len(eventos)} próximos y {len(_historial)} resultados normales con fecha verificada")
    return eventos


def historial_equipo(evento, lado):
    tid = (evento.get(lado) or {}).get("id")
    contexto = evento.get("contexto_competicion")
    return sorted((p for p in _historial if p.get("contexto_competicion") == contexto and
                   tid in (p["id_local"], p["id_visita"])), key=lambda p: p["fecha"], reverse=True)[:10]
