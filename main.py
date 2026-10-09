"""
main.py
Radar Mismatch Multideporte Femenino 360° — Grado Institucional
- 14 Deportes vía Sofascore
- Cuadros oficiales ITF World Tennis Tour
- Ascenso y formativas vía BeSoccer
- Análisis in-game (Tennis Abstract & ScoreBing)
- Smart Money y líneas institucionales de Pinnacle
- Monitor ligero de novedades de plantel (RSS / X)
"""

import requests
import time
import re
import os
import json
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# Módulos internos del sistema
import motor_mismatches
import fuentes_alternativas
import tracker_cuotas_smart
import conector_besoccer
import metricas_profundas
import monitor_noticias

# --- SERVIDOR WEB FANTASMA (Render Web Service) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Radar Mismatches Femenino 360 OK")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass

def iniciar_servidor_web():
    puerto = int(os.environ.get("PORT", 10000))
    servidor = HTTPServer(('0.0.0.0', puerto), SimpleHandler)
    servidor.serve_forever()

Thread(target=iniciar_servidor_web, daemon=True).start()
# --------------------------------------------------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
CHAT_ID_GRUPO = os.environ.get("CHAT_ID_GRUPO")

INTERVALO_REVISION = 1800  # 30 minutos por barrido
ARCHIVO_NOTIFICADOS = "notificados.json"

DEPORTES_RADAR = {
    "volleyball": "Volleyball",
    "football": "Soccer",
    "basketball": "Basketball",
    "handball": "Handball",
    "tennis": "Tennis",
    "futsal": "Futsal",
    "ice-hockey": "Ice Hockey",
    "floorball": "Floorball",
    "waterpolo": "Waterpolo",
    "table-tennis": "Table Tennis",
    "badminton": "Badminton",
    "rugby": "Rugby",
    "field-hockey": "Field Hockey",
    "cricket": "Cricket"
}

KEYWORDS_FEMENINAS = [
    "women", "womens", "wom", "fem", "femenil", "femenino", "femenina", 
    "donne", "mulheres", "damas", "feminina", "ladies", "dames", "frauen", 
    "damen", "kobiety", "zeny", "wta", "itf women", "wnba", "wsl", "nwsl",
    "liga f", "serie a fem", "frauen-bundesliga", "sdhl", "pwhl"
]

HEADERS_SOFASCORE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com"
}


# ---------- PERSISTENCIA ----------
def cargar_notificados():
    if os.path.exists(ARCHIVO_NOTIFICADOS):
        try:
            with open(ARCHIVO_NOTIFICADOS, "r") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def guardar_notificados(notificados):
    try:
        with open(ARCHIVO_NOTIFICADOS, "w") as f:
            json.dump(list(notificados), f)
    except Exception:
        pass

partidos_notificados = cargar_notificados()


def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    destinos = [c for c in (CHAT_ID, CHAT_ID_GRUPO) if c]

    for d in destinos:
        payload = {"chat_id": d, "text": mensaje, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception:
            pass


def es_deporte_femenino_valido(torneo, local, visita):
    texto = f"{torneo} {local} {visita}".lower()
    if any(k in texto for k in ["wta", "itf women", "billie jean king"]):
        return True
    if any(k in texto for k in ["atp", "challenger", "davis cup"]):
        return False
    if any(re.search(rf"\b{kw}\b", texto) for kw in KEYWORDS_FEMENINAS):
        return True
    if re.search(r'\((w\vert{}f)\)', texto):
        return True
    return False


def obtener_partidos_sofascore(slug):
    hoy = datetime.now().strftime("%Y-%m-%d")
    url = f"https://api.sofascore.com/api/v1/sport/{slug}/scheduled-events/{hoy}"
    try:
        r = requests.get(url, headers=HEADERS_SOFASCORE, timeout=12)
        if r.status_code == 200:
            return r.json().get("events", [])
    except Exception:
        pass
    return []


def obtener_tabla_torneo(tourn_id, season_id):
    if not tourn_id or not season_id:
        return {}
    url = f"https://api.sofascore.com/api/v1/tournament/{tourn_id}/season/{season_id}/standings/total"
    try:
        r = requests.get(url, headers=HEADERS_SOFASCORE, timeout=10)
        if r.status_code != 200:
            return {}
        standings = r.json().get("standings", [])
        if not standings:
            return {}
        tabla = {}
        for f in standings[0].get("rows", []):
            tid = f.get("team", {}).get("id")
            if tid:
                tabla[tid] = {
                    "posicion": f.get("position", 0),
                    "puntos": f.get("points", 0),
                    "partidos_jugados": f.get("matches", 0),
                    "dif_neta": f.get("scoresFor", 0) - f.get("scoresAgainst", 0)
                }
        return tabla
    except Exception:
        return {}


def obtener_ultimos_partidos(team_id):
    if not team_id:
        return []
    url = f"https://api.sofascore.com/api/v1/team/{team_id}/events/last/0"
    try:
        time.sleep(1)
        r = requests.get(url, headers=HEADERS_SOFASCORE, timeout=10)
        if r.status_code != 200:
            return []
        partidos = []
        for ev in r.json().get("events", [])[:8]:
            dt = datetime.fromtimestamp(ev.get("startTimestamp", 0))
            partidos.append({
                "fecha": dt.isoformat(),
                "id_local": ev.get("homeTeam", {}).get("id"),
                "nom_local": ev.get("homeTeam", {}).get("name"),
                "id_visita": ev.get("awayTeam", {}).get("id"),
                "nom_visita": ev.get("awayTeam", {}).get("name"),
                "puntos_local": ev.get("homeScore", {}).get("current"),
                "puntos_visita": ev.get("awayScore", {}).get("current")
            })
        return partidos
    except Exception:
        return []


def obtener_h2h_sofascore(event_id):
    url = f"https://api.sofascore.com/api/v1/event/{event_id}/h2h"
    try:
        time.sleep(0.5)
        r = requests.get(url, headers=HEADERS_SOFASCORE, timeout=10)
        if r.status_code != 200:
            return []
        h2h_data = []
        for ev in r.json().get("events", [])[:5]:
            dt = datetime.fromtimestamp(ev.get("startTimestamp", 0))
            h2h_data.append({
                "fecha": dt.isoformat(),
                "id_local": ev.get("homeTeam", {}).get("id"),
                "id_visita": ev.get("awayTeam", {}).get("id"),
                "puntos_local": ev.get("homeScore", {}).get("current"),
                "puntos_visita": ev.get("awayScore", {}).get("current")
            })
        return h2h_data
    except Exception:
        return []


def enriquecer_y_enviar_alerta(deporte, torneo, nom_loc, nom_vis, hora_arg, estado, alertas_base, pick_base):
    """
    Agrega capas institucionales antes de enviar a Telegram:
    - Verificación contra Pinnacle y Smart Money
    - Presión táctica / Superficie
    - Novedades de plantel en redes
    """
    detalles = list(alertas_base)

    # 1. Presión ofensiva (Fútbol) o Superficie (Tenis)
    if deporte == "Soccer":
        stats_presion = metricas_profundas.obtener_presion_ofensiva_futbol(nom_loc)
        if stats_presion.get("alta_presion"):
            detalles.append(
                f"Presión Ofensiva ScoreBing: +{stats_presion['prom_corners_favor']} córners a favor vs {stats_presion['prom_corners_contra']} concedidos"
            )
    elif deporte == "Tennis":
        perfil_sup = metricas_profundas.consultar_perfil_tenis_abstract(nom_loc)
        if perfil_sup.get("es_vulnerable_superficie"):
            detalles.append(f"⚠️ Advertencia Superficie: Win rate bajo en {perfil_sup['superficie']} ({perfil_sup['efectividad_superficie']})")

    # 2. Búsqueda de novedades de plantel de última hora
    novedades = monitor_noticias.buscar_novedades_partido(nom_loc, nom_vis)
    if novedades.get("alerta_novedad"):
        detalles.append(f"Último Momento: {novedades['fragmento']}")

    # 3. Verificación de Cuota / Smart Money en Pinnacle
    analisis_odds = tracker_cuotas_smart.analizar_mercado_evento(nom_loc)
    estado_mercado = analisis_odds.get("resumen") if analisis_odds.get("disponible") else "Línea abierta en bookies locales"

    detalles_txt = "\n".join([f"• {d}" for d in detalles])

    mensaje = (
        f"🚨 *MISMATCH DETECTADO — RADAR FEMENINO*\n\n"
        f"Status: {estado}\n"
        f"🏅 *Deporte:* {deporte}\n"
        f"🏆 *Competición:* {torneo}\n"
        f"⚔️ *Encuentro:* {nom_loc} vs {nom_vis}\n"
        f"🕒 *Horario:* {hora_arg}\n\n"
        f"📊 *La Clave del Mismatch:*\n{detalles_txt}\n\n"
        f"🎯 *Mercado Sugerido:* {pick_base}\n"
        f"📈 *Estado del Mercado:* {estado_mercado}\n"
        f"🔥 *Confianza:* Alta"
    )
    enviar_telegram(mensaje)
    print(f"-> ¡MISMATCH NOTIFICADO! ({deporte}): {nom_loc} vs {nom_vis}", flush=True)


def ejecutar_barrido_radar():
    global partidos_notificados
    print(f"[{datetime.now().strftime('%H:%M')}] Iniciando barrido Radar Femenino 360°...", flush=True)

    # 1. BARRIDO ITF WORLD TENNIS TOUR (Draws Oficiales)
    mismatches_itf = fuentes_alternativas.obtener_mismatches_itf()
    for m in mismatches_itf:
        if m["id"] in partidos_notificados:
            continue

        enriquecer_y_enviar_alerta(
            deporte="Tennis",
            torneo=m["torneo"],
            nom_loc=m["local"],
            nom_vis=m["visita"],
            hora_arg=m["horario"],
            estado="🟢 *PRE*",
            alertas_base=[m["detalle"]],
            pick_base="Under Games / Hándicap de Juegos"
        )
        partidos_notificados.add(m["id"])
        guardar_notificados(partidos_notificados)

    # 2. BARRIDO ASCENSO Y FORMATIVAS (BeSoccer)
    partidos_ascenso = conector_besoccer.obtener_partidos_ascenso_besoccer()
    for p_asc in partidos_ascenso:
        if p_asc["id"] in partidos_notificados:
            continue

        if p_asc.get("tiene_alineaciones"):
            rotacion = conector_besoccer.verificar_rotacion_plantel(p_asc["id"].replace("besoccer_", ""))
            if rotacion.get("alerta_rotacion"):
                alerta_txt = f"Rotación masiva confirmada en BeSoccer (presencia de dorsales de reserva/juveniles)"
                enriquecer_y_enviar_