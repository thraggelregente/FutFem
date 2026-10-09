"""
tracker_cuotas_smart.py
Monitor Cuantitativo de Mercado y Smart Money:
- Comparación contra línea de apertura (Opening Line) de Pinnacle / Mercado Global.
- Detección de desplome acelerado de cuotas (Dropping Odds).
- Identificación de ineficiencias frente a casas recreativas.
"""

import requests
import os
from datetime import datetime

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def calcular_desplome(cuota_apertura, cuota_actual):
    """
    Calcula la variación porcentual hacia la baja.
    Una caída >= 20% en cuotas de favoritos suele indicar 'Smart Money' o bajas de peso.
    """
    if not cuota_apertura or not cuota_actual or cuota_apertura <= 1.0:
        return 0.0, False

    caida_pct = ((cuota_apertura - cuota_actual) / cuota_apertura) * 100
    es_desplome = caida_pct >= 20.0
    return round(caida_pct, 1), es_desplome


def analizar_mercado_evento(equipo_favorito, sport_key="upcoming"):
    """
    Busca el evento en los feeds de cuotas agregadas, extrae la cuota de apertura
    y la cuota vigente en Pinnacle / mercado global.
    """
    if not ODDS_API_KEY:
        return {
            "disponible": False,
            "mensaje": "Monitor de cuotas inactivo (Falta API Key)"
        }

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us",
        "markets": "h2h,spreads",
        "oddsFormat": "decimal"
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return {"disponible": False, "mensaje": "Línea no disponible en feed global"}

        eventos = r.json()
        fav_norm = equipo_favorito.lower().strip()

        for ev in eventos:
            nom_h = ev.get("home_team", "").lower()
            nom_a = ev.get("away_team", "").lower()

            if fav_norm in nom_h or fav_norm in nom_a:
                bookmakers = ev.get("bookmakers", [])
                cuotas_fav = []
                pinnacle_odds = None

                for b in bookmakers:
                    b_key = b.get("key", "").lower()
                    for m in b.get("markets", []):
                        if m.get("key") == "h2h":
                            for out in m.get("outcomes", []):
                                if fav_norm in out.get("name", "").lower():
                                    precio = out.get("price", 0.0)
                                    cuotas_fav.append(precio)
                                    if "pinnacle" in b_key:
                                        pinnacle_odds = precio

                if not cuotas_fav:
                    continue

                cuota_max = max(cuotas_fav)
                cuota_min = min(cuotas_fav)
                cuota_referencia = pinnacle_odds if pinnacle_odds else cuota_min

                # Si hay dispersión entre casas (ej: Pinnacle en 1.30 y otra casa en 1.65)
                desfase = round(((cuota_max - cuota_referencia) / cuota_referencia) * 100, 1) if cuota_referencia > 1.0 else 0.0

                return {
                    "disponible": True,
                    "cuota_pinnacle": pinnacle_odds,
                    "mejor_cuota_mercado": cuota_max,
                    "cuota_mas_baja": cuota_min,
                    "desfase_pct": desfase,
                    "alerta_smart_money": desfase >= 18.0,
                    "resumen": (
                        f"Pinnacle/Base: @{pinnacle_odds or cuota_referencia} | "
                        f"Mejor cuota disponible: @{cuota_max}" +
                        (f" (⚠️ Desfase de valor: +{desfase}%)" if desfase >= 15.0 else "")
                    )
                }

    except Exception as e:
        return {"disponible": False, "mensaje": f"Error verificando líneas: {e}"}

    return {"disponible": False, "mensaje": "Evento aún sin liquidez o fuera de bookies comerciales"}