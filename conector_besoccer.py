"""
conector_besoccer.py
Extractor de eventos de fútbol femenino de ascenso y formativas vía BeSoccer:
- Categorías regionales, ascenso (2da/3ra división) y formativas (Sub-19/20).
- Monitoreo de alineaciones confirmadas para detectar rotaciones tempranas.
"""

import requests
import time
from datetime import datetime

HEADERS_BESOCCER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://es.besoccer.com/"
}

KEYWORDS_ASCENSO_FEM = [
    "femenino", "femenina", "women", "fem", "frauen", "dames", "ladies",
    "sub-19", "sub-20", "u19", "u20", "2. division", "primera federacion",
    "segunda federacion", "tercera federacion", "liga b", "serie b", "serie c"
]

def obtener_partidos_ascenso_besoccer():
    """
    Consulta los partidos del día en el feed abierto de BeSoccer.
    Filtra torneos de ascenso y formativas femeninas.
    """
    hoy = datetime.now().strftime("%Y-%m-%d")
    url = f"https://es.besoccer.com/scripts/bigdata/matches_day.php?date={hoy}"
    partidos_ascenso = []

    try:
        r = requests.get(url, headers=HEADERS_BESOCCER, timeout=12)
        if r.status_code != 200:
            return []

        data = r.json()
        matches = data.get("matches", []) or []

        for m in matches:
            torneo = (m.get("league_name") or "").lower()
            local = (m.get("home_team_name") or "").lower()
            visita = (m.get("away_team_name") or "").lower()
            texto = f"{torneo} {local} {visita}"

            # Filtro estricto femenino para ascenso
            if not any(k in texto for k in KEYWORDS_ASCENSO_FEM):
                continue

            match_id = m.get("id")
            estado = m.get("status_name", "No empezado")
            hora = m.get("hour", "A confirmar")

            partidos_ascenso.append({
                "id": f"besoccer_{match_id}",
                "torneo": m.get("league_name", "Torneo Ascenso Fem"),
                "local": m.get("home_team_name", "Local"),
                "visita": m.get("away_team_name", "Visitante"),
                "horario": hora,
                "estado": estado,
                "tiene_alineaciones": bool(m.get("has_lineups", False))
            })

    except Exception:
        pass

    return partidos_ascenso


def verificar_rotacion_plantel(match_id):
    """
    Consulta si las alineaciones están disponibles y evalúa si hay
    indicios de formación alternativa en partidos de copa o cierre de temporada.
    """
    if not match_id:
        return {"alineaciones_disponibles": False, "alerta_rotacion": False}

    url = f"https://es.besoccer.com/scripts/bigdata/lineups.php?id={match_id}"
    try:
        r = requests.get(url, headers=HEADERS_BESOCCER, timeout=8)
        if r.status_code != 200:
            return {"alineaciones_disponibles": False, "alerta_rotacion": False}

        lineup_data = r.json()
        titulares_local = lineup_data.get("home_lineup", [])
        titulares_visita = lineup_data.get("away_lineup", [])

        if not titulares_local or not titulares_visita:
            return {"alineaciones_disponibles": False, "alerta_rotacion": False}

        # Verificación de presencia de dorsales altos (>25 o formativos en plantilla regular)
        dorsales_altos_local = sum(1 for jug in titulares_local if jug.get("dorsal", 0) > 28)
        dorsales_altos_visita = sum(1 for jug in titulares_visita if jug.get("dorsal", 0) > 28)

        alerta = (dorsales_altos_local >= 4) or (dorsales_altos_visita >= 4)

        return {
            "alineaciones_disponibles": True,
            "alerta_rotacion": alerta,
            "dorsales_reserva_local": dorsales_altos_local,
            "dorsales_reserva_visita": dorsales_altos_visita
        }

    except Exception:
        return {"alineaciones_disponibles": False, "alerta_rotacion": False}