"""
fuentes_alternativas.py
ITF World Tennis Tour femenino (W15 a W100).
Consume el calendario y orden de juego oficial de la API de ITF.
"""

from datetime import datetime, timezone

import utilidades as U

try:
    import motor_mismatches
except Exception as e:
    motor_mismatches = None
    U.log(f"[itf] no pude importar motor_mismatches: {e}")

HEADERS_ITF = dict(U.HEADERS_NAVEGADOR, Referer="https://www.itftennis.com/")
BASE_ITF = "https://www.itftennis.com/tennis/api/TournamentApi"


def _obtener_partidos_torneo(tournament_key, hoy_str):
    url = f"{BASE_ITF}/GetOrderOfPlay"
    params = {"tournamentKey": tournament_key, "date": hoy_str}
    data = U.get_json(url, "itf", headers=HEADERS_ITF, params=params, timeout=10)
    if not isinstance(data, dict):
        return []

    partidos = []
    # Procesa canchas y turnos de juego
    for court in data.get("courts", []) or []:
        for m in court.get("matches", []) or []:
            if not isinstance(m, dict):
                continue
            # Ignora partidos de dobles
            tipo = str(m.get("matchType") or m.get("eventTypeName") or "").lower()
            if "double" in tipo or "doble" in tipo:
                continue
            partidos.append(m)
    return partidos


def obtener_mismatches_itf():
    """
    Obtiene los partidos de torneos ITF WTT femeninos de hoy y evalúa asimetrías de ranking.
    """
    if motor_mismatches is None:
        return []

    hoy_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = f"{BASE_ITF}/GetCalendar"
    params = {
        "circuitCode": "WT",
        "searchString": "",
        "skip": 0,
        "take": 50,
        "dateFrom": hoy_str,
        "dateTo": hoy_str,
        "isOrderAscending": "true",
        "orderField": "startDate",
    }

    data = U.get_json(url, "itf", headers=HEADERS_ITF, params=params, timeout=12)
    if not isinstance(data, dict):
        return []

    torneos = data.get("items") or data.get("tournaments") or []
    if not torneos:
        return []

    resultados = []
    for t in torneos:
        if not isinstance(t, dict):
            continue

        t_key = t.get("tournamentKey") or t.get("id")
        if not t_key:
            continue

        nombre_torneo = t.get("tournamentName") or t.get("name") or "ITF Women"
        categoria = t.get("categoryName") or t.get("category") or ""
        sede = f"{t.get('hostNationName', '')} - {t.get('cityTown', '')}".strip(" -")
        torneo_desc = f"{nombre_torneo} ({categoria}) {sede}".strip()

        partidos = _obtener_partidos_torneo(t_key, hoy_str)
        for m in partidos:
            p1 = m.get("player1") or m.get("team1") or {}
            p2 = m.get("player2") or m.get("team2") or {}
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

            mid = str(m.get("matchId") or m.get("id") or hash(nom1 + nom2))
            resultados.append({
                "id": f"itf_{mid}",
                "torneo": torneo_desc,
                "local": nom1,
                "visita": nom2,
                "horario": m.get("scheduledTime") or m.get("startTime") or "A confirmar",
                "detalle": f"ITF Draw Oficial — {detalle}",
                "favorito": favorito,
            })

    return resultados