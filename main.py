"""
main.py
Radar Mismatch Multideporte Femenino 360°
- Servidor Web Fantasma activo para Render Web Service y UptimeRobot.
- Monitoreo de 14 deportes femeninos vía Sofascore.
- Evaluación cuantitativa mediante motor_mismatches (Costo $0, Cero límites de IA).
- Alertas automáticas estructuradas a Telegram.
"""

import requests
import time
import re
import os
import json
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
import motor_mismatches

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

INTERVALO_REVISION = 1800  # 30 minutos por barrido completo
ARCHIVO_NOTIFICADOS = "notificados.json"

# Los 14 deportes del Radar
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
    if re.search(r'\((w|f)\)', texto):
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


def ejecutar_barrido_radar():
    global partidos_notificados
    print(f"[{datetime.now().strftime('%H:%M')}] Iniciando barrido Radar Femenino 360°...", flush=True)

    for slug, deporte_nombre in DEPORTES_RADAR.items():
        eventos = obtener_partidos_sofascore(slug)
        if not eventos:
            continue

        for ev in eventos:
            event_id = ev.get("id")
            if not event_id:
                continue

            id_unico = f"sofa_{event_id}"
            if id_unico in partidos_notificados:
                continue

            torneo_obj = ev.get("tournament", {})
            torneo_nom = torneo_obj.get("name", "Torneo")
            cat_nom = torneo_obj.get("category", {}).get("name", "")
            competicion = f"{torneo_nom} ({cat_nom})" if cat_nom else torneo_nom

            local_obj = ev.get("homeTeam", {})
            visita_obj = ev.get("awayTeam", {})
            nom_loc = local_obj.get("name", "Local")
            nom_vis = visita_obj.get("name", "Visitante")
            id_loc = local_obj.get("id")
            id_vis = visita_obj.get("id")

            # 1. Filtro estricto femenino
            if not es_deporte_femenino_valido(competicion, nom_loc, nom_vis):
                continue

            start_ts = ev.get("startTimestamp", 0)
            hora_arg = (datetime.fromtimestamp(start_ts) - timedelta(hours=0)).strftime("%H:%M hs (ARG)")
            estado = "🔴 *EN VIVO (LIVE)*" if ev.get("status", {}).get("type") == "inprogress" else "🟢 *PRE*"

            # 2. Análisis Tenis vs Deportes de Conjunto
            if deporte_nombre == "Tennis":
                rank_loc = local_obj.get("ranking")
                rank_vis = visita_obj.get("ranking")
                hay_wc, detalle_wc = motor_mismatches.evaluar_mismatch_tenis(nom_loc, nom_vis, rank_loc, rank_vis)

                if hay_wc:
                    pick = motor_mismatches.sugerir_mercado("Tennis", [detalle_wc], es_favorito_local=True)
                    mensaje = (
                        f"🚨 *MISMATCH DETECTADO — RADAR FEMENINO*\n\n"
                        f"Status: {estado}\n"
                        f"🏅 *Deporte:* Tennis\n"
                        f"🏆 *Torneo:* {competicion}\n"
                        f"⚔️ *Partido:* {nom_loc} vs {nom_vis}\n"
                        f"🕒 *Horario:* {hora_arg}\n\n"
                        f"📊 *La Clave del Mismatch:*\n• {detalle_wc}\n\n"
                        f"🎯 *Mercado Sugerido:* {pick}\n"
                        f"🔥 *Confianza:* Muy Alta"
                    )
                    enviar_telegram(mensaje)
                    partidos_notificados.add(id_unico)
                    guardar_notificados(partidos_notificados)
                    print(f"-> Mismatch Notificado (Tenis): {nom_loc} vs {nom_vis}", flush=True)
                else:
                    partidos_notificados.add(id_unico)
                continue

            # Deportes de Equipo (Voley, Futbol, Basket, Handball, etc.)
            tourn_id = torneo_obj.get("uniqueTournament", {}).get("id")
            season_id = ev.get("season", {}).get("id")

            tabla = obtener_tabla_torneo(tourn_id, season_id)
            tabla_eval = motor_mismatches.evaluar_tabla_posiciones(tabla, id_loc, id_vis)

            hist_loc = obtener_ultimos_partidos(id_loc)
            hist_vis = obtener_ultimos_partidos(id_vis)

            perf_loc = motor_mismatches.evaluar_rendimiento_reciente(hist_loc, id_loc)
            perf_vis = motor_mismatches.evaluar_rendimiento_reciente(hist_vis, id_vis)

            triangs = motor_mismatches.triangular_rivales(hist_loc, id_loc, hist_vis, id_vis)
            h2h_raw = obtener_h2h_sofascore(event_id)
            h2h_eval = motor_mismatches.analizar_h2h_reciente(h2h_raw, id_loc, id_vis)

            # 3. Evaluación del Mismatch
            hay_mismatch, alertas, pick = motor_mismatches.evaluar_mismatch(
                deporte=deporte_nombre,
                perf_local=perf_loc,
                perf_visita=perf_vis,
                triangulaciones=triangs,
                h2h=h2h_eval,
                tabla_local_visita=tabla_eval
            )

            if hay_mismatch:
                detalles_txt = "\n".join([f"• {a}" for a in alertas])
                mensaje = (
                    f"🚨 *MISMATCH DETECTADO — RADAR FEMENINO*\n\n"
                    f"Status: {estado}\n"
                    f"🏅 *Deporte:* {deporte_nombre}\n"
                    f"🏆 *Competición:* {competicion}\n"
                    f"⚔️ *Encuentro:* {nom_loc} vs {nom_vis}\n"
                    f"🕒 *Horario:* {hora_arg}\n\n"
                    f"📊 *La Clave del Mismatch:*\n{detalles_txt}\n\n"
                    f"🎯 *Mercado Sugerido:* {pick}\n"
                    f"🔥 *Confianza:* Alta"
                )
                enviar_telegram(mensaje)
                print(f"-> ¡MISMATCH NOTIFICADO! ({deporte_nombre}): {nom_loc} vs {nom_vis}", flush=True)

            partidos_notificados.add(id_unico)
            guardar_notificados(partidos_notificados)


if __name__ == "__main__":
    print("Radar Cuantitativo Multideporte Femenino 360° desplegado...", flush=True)
    enviar_telegram("🤖 *Radar Femenino 360° Cuantitativo Activado:* Monitoreando 14 deportes con motor de triangulación, tablas y forma vigente.")

    while True:
        try:
            ejecutar_barrido_radar()
        except Exception as e:
            print(f"Error en ciclo de barrido: {e}", flush=True)

        time.sleep(INTERVALO_REVISION)