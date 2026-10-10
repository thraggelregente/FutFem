"""
fuentes_alternativas.py
ITF Women's World Tennis Tour (W15 a W100).
Consume el endpoint oficial activo: /tennis/api/TournamentApi/GetCalendar
"""

import re
from datetime import datetime, timezone

import utilidades as U

try:
    import motor_mismatches
except Exception as e:
    motor_mismatches = None
    U.log(f"[itf] no pude importar motor_mismatches: {e}")

HEADERS_ITF = dict(U.HEADERS_NAVEGADOR, Referer="https://www.itftennis.com/")
BASE_ITF = "https://www.itftennis.com/tennis/api/TournamentApi"

_RE_TORNEO_FEM = re.compile(r"\bw\s?\d{2,3}\b|women", re.I)


def obtener_mismatches_itf():
    """
    Consulta los torneos y partidos activos del circuito femenino (WTT).
    """
    if motor_mismatches is None:
        return []

    hoy_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = f"{BASE_ITF}/GetCalendar"
    params = {
        "circuitCode": "WT",
        "searchString": "",
        "skip": 0,
        "take": 100,
        "dateFrom": hoy_str,
        "dateTo": hoy_str,
        "isOrderAscending": "true",
        "orderField": "startDate",
    }

    data = U.get_json(url, "itf", headers=HEADERS_ITF, params=params, timeout=12)
    if not isinstance(data, (dict, list)):
        return []

    items = data.get("items") or data.get("tournaments") or (data if isinstance(data, list) else [])
    if not items:
        return []

    resultados = []
    for t in items:
        if not isinstance(t, dict):
            continue

        nombre_torneo = t.get("tournamentName") or t.get("name") or "ITF Women"
        categoria = t.get("categoryName") or t.get("category") or ""
        sede = f"{t.get('hostNationName', '')} - {t.get('cityTown', '')}".strip(" -")
        torneo_desc = f"{nombre_torneo} ({categoria}) {sede}".strip()

        # Si el endpoint devuelve partidos/llaves directamente:
        for m in t.get("matches", []):
            if not isinstance(m, dict):
                continue

            p1 = m.get("player1") or {}
            p2 = m.get("player2") or {}
            nom1 = p1.get("name") or p1.get("playerName") or "Jugadora 1"
            nom2 = p2.get("name") or p2.get("playerName") or "Jugadora 2"

            hay, detalle, favorito, pts = motor_mismatches.evaluar_mismatch_tenis(
                nom1, nom2,
                p1.get("rank") or p1.get("ranking"),
                p2.get("rank") or p2.get("ranking"),
                entry_local=p1.get("entryStatus"),
                entry_visita=p2.get("entryStatus"),
            )
            if not hay or pts < 2:
                continue

            resultados.append({
                "id": f"itf_{m.get('id', hash(nom1 + nom2))}",
                "torneo": torneo_desc,
                "local": nom1,
                "visita": nom2,
                "horario": m.get("scheduledTime") or "A confirmar",
                "detalle": f"ITF Draw Oficial — {detalle}",
                "favorito": favorito,
            })

    return resultados