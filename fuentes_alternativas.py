"""
fuentes_alternativas.py
Conectores auxiliares para el Radar Femenino:
- ITF World Tennis Tour (Cuadros oficiales, WC, Q, rankings)
- AiScore / Feeds Multideporte
- Validador de Cuotas (OddsPapi / The Odds API)
"""

import requests
import os
from datetime import datetime

HEADERS_ITF = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.itftennis.com/"
}

HEADERS_AISCORE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
ODDSPAPI_API_KEY = os.environ.get("ODDSPAPI_API_KEY")


# ---------- 1. ITF WORLD TENNIS TOUR OFICIAL ----------
def obtener_mismatches_itf():
    """
    Consulta los torneos y partidos del circuito femenino ITF (W15 a W100).
    Detecta Wild Cards (WC) y jugadoras no clasificadas frente a favoritas.
    """
    hoy = datetime.now().strftime("%Y-%m-%d")
    url = f"https://www.itftennis.com/api/v1/tournaments/order-of-play?date={hoy}&circuit=WTT"
    mismatches_itf = []

    try:
        r = requests.get(url, headers=HEADERS_ITF, timeout=10)
        if r.status_code != 200:
            return []

        data = r.json()
        matches = data.get("matches", []) or []

        for m in matches:
            if not m.get("isWomen"):
                continue

            p1 = m.get("player1", {})
            p2 = m.get("player2", {})

            entry_p1 = (p1.get("entryStatus") or "").upper()
            entry_p2 = (p2.get("entryStatus") or "").upper()
            rank_p1 = p1.get("rank")
            rank_p2 = p2.get("rank")

            # Señal WC o Qualy sin ranking frente a profesional de cuadro principal
            asimetria = False
            detalle = ""

            if entry_p1 == "WC" and (not rank_p1 or rank_p1 > 900) and (rank_p2 and rank_p2 < 450):
                asimetria = True
                detalle = f"ITF Draw Oficial: {p1.get('name')} entra por WC (sin ranking) vs {p2.get('name')} (Rank #{rank_p2})"
            elif entry_p2 == "WC" and (not rank_p2 or rank_p2 > 900) and (rank_p1 and rank_p1 < 450):
                asimetria = True
                detalle = f"ITF Draw Oficial: {p2.get('name')} entra por WC (sin ranking) vs {p1.get('name')} (Rank #{rank_p1})"

            if asimetria:
                mismatches_itf.append({
                    "id": f"itf_{m.get('id')}",
                    "torneo": m.get("tournamentName", "ITF Women"),
                    "local": p1.get("name", "Jugadora 1"),
                    "visita": p2.get("name", "Jugadora 2"),
                    "horario": m.get("scheduledTime", "A confirmar"),
                    "detalle": detalle
                })
    except Exception:
        pass

    return mismatches_itf


# ---------- 2. AISCORE (BÁSQUET, VÓLEY Y LIGAS FORMATIVAS) ----------
def obtener_eventos_aiscore(deporte="basketball"):
    """
    Trae partidos programados desde el feed de AiScore para complementar ligas secundarias.
    """
    hoy = datetime.now().strftime("%Y-%m-%d")
    url = f"https://api.aiscore.com/v1/m/match/list?sport={deporte}&date={hoy}"
    try:
        r = requests.get(url, headers=HEADERS_AISCORE, timeout=10)
        if r.status_code == 200:
            return r.json().get("data", []) or []
    except Exception:
        pass
    return []


# ---------- 3. VALIDACIÓN DE CUOTAS (ODDS CHECK) ----------
def validar_cuota_mercado(equipo_favorito):
    """
    Verifica si las casas de apuestas ya reventaron la línea (1.01)
    o si todavía se mantiene con valor para entrar en pre-partido.
    """
    if not ODDS_API_KEY:
        return "Cuota no verificada (Sin API Key)"

    url = "https://api.the-odds-api.com/v4/sports/upcoming/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h,spreads"
    }

    try:
        r = requests.get(url, params=params, timeout=8)
        if r.status_code != 200:
            return "Línea abierta (Revisar en bookie)"

        eventos = r.json()
        fav_clean = equipo_favorito.lower()

        for ev in eventos:
            nom_h = ev.get("home_team", "").lower()
            nom_a = ev.get("away_team", "").lower()

            if fav_clean in nom_h or fav_clean in nom_a:
                bookmakers = ev.get("bookmakers", [])
                if not bookmakers:
                    continue

                for b in bookmakers:
                    for m in b.get("markets", []):
                        if m.get("key") == "h2h":
                            for out in m.get("outcomes", []):
                                if fav_clean in out.get("name", "").lower():
                                    cuota = out.get("price", 0.0)
                                    if cuota <= 1.08:
                                        return f"Cuota colapsada @{cuota} (Conviene esperar LIVE o Hándicap alto)"
                                    return f"Cuota de entrada con valor @{cuota}"
    except Exception:
        pass

    return "Línea disponible en bookies locales"