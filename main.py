"""
main.py
Radar Mismatch Multideporte Femenino 360° — Resiliente
- Servidor Web Fantasma prioritario (Garantiza estado LIVE en Render).
- Importación segura de módulos para evitar cierres prematuros.
"""

import os
import sys
import time
import json
import re
import requests
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- 1. SERVIDOR WEB FANTASMA (SE INICIA ANTES QUE CUALQUIER OTRA COSA) ---
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
# --------------------------------------------------------------------------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
CHAT_ID_GRUPO = os.environ.get("CHAT_ID_GRUPO")

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

# --- 2. IMPORTACIÓN DEFENSIVA DE MÓDULOS ---
try:
    import motor_mismatches
except Exception as e:
    print(f"ERROR cargando motor_mismatches: {e}", flush=True)
    enviar_telegram(f"⚠️ Error cargando motor_mismatches: {e}")

try:
    import fuentes_alternativas
except Exception as e:
    fuentes_alternativas = None
    print(f"Aviso: fuentes_alternativas no disponible: {e}", flush=True)

try:
    import tracker_cuotas_smart
except Exception as e:
    tracker_cuotas_smart = None
    print(f"Aviso: tracker_cuotas_smart no disponible: {e}", flush=True)

try:
    import conector_besoccer
except Exception as e:
    conector_besoccer = None
    print(f"Aviso: conector_besoccer no disponible: {e}", flush=True)

try:
    import metricas_profundas
except Exception as e:
    metricas_profundas = None
    print(f"Aviso: metricas_profundas no disponible: {e}", flush=True)

try:
    import monitor_noticias
except Exception as e:
    monitor_noticias = None
    print(f"Aviso: monitor_noticias no disponible: {e}", flush=True)


INTERVALO_REVISION = 1800  # 30 minutos
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


def enriquecer_y_enviar_alerta(deporte, torneo, nom_loc, nom_vis, hora_arg, estado, alertas_base, pick_base):
    detalles = list(alertas_base)

    if metricas_profundas:
        if deporte == "Soccer":
            stats_p = metricas_profundas.obtener_presion_ofensiva_futbol(nom_loc)
            if stats_p.get("alta_presion"):
                detalles.append(
                    f"Presión ScoreBing: +{stats_p['prom_corners_favor']} córners a favor vs {stats_p['prom_corners_contra']} recibidos"
                )
        elif deporte == "Tennis":
            perfil_s = metricas_profundas.consultar_perfil_tenis_abstract(nom_loc)
            if perfil_s.get("es_vulnerable_superficie"):
                detalles.append(f"⚠️ Advertencia Superficie: Win rate bajo en {perfil_s['superficie']} ({perfil_s['efectividad_superficie']})")

    if monitor_noticias:
        novedades = monitor_noticias.buscar_novedades_partido(nom_loc, nom_vis)
        if novedades.get("alerta_novedad"):
            detalles.append(f"Último Momento: {novedades['fragmento']}")

    estado_mercado = "Línea abierta en bookies locales"
    if tracker_cuotas_smart:
        analisis_odds = tracker_cuotas_smart.analizar_mercado_evento(nom_loc)
        if analisis_odds.get("disponible"):
            estado_mercado = analisis_odds.get("resumen")

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
    print(f"[{datetime.now().strftime('%H:%M')}] Ejecutando barrido Radar Femenino 360°...", flush=True)

    # 1. ITF
    if fuentes_alternativas:
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

    # 2. BeSoccer
    if conector_besoccer:
        partidos_asc = conector_besoccer.obtener_partidos_ascenso_besoccer()
        for p_asc in partidos_asc:
            if p_asc["id"] in partidos_notificados:
                continue

            if p_asc.get("tiene_alineaciones"):
                rotacion = conector_besoccer.verificar_rotacion_plantel(p_asc["id"].replace("besoccer_", ""))
                if rotacion.get("alerta_rotacion"):
                    enriquecer_y_enviar_alerta(
                        deporte="Soccer",
                        torneo=p_asc["torneo"],
                        nom_loc=p_asc["local"],
                        nom_vis=p_asc["visita"],
                        hora_arg=p_asc["horario"],
                        estado="🟢 *PRE*",
                        alertas_base=["Rotación masiva detectada en alineación confirmada"],
                        pick_base="Hándicap / Doble Oportunidad Rival"
                    )
                    partidos_notificados.add(p_asc["id"])
                    guardar_notificados(partidos_notificados)

    # 3. Sofascore (14 Deportes)
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

            if not es_deporte_femenino_valido(competicion, nom_loc, nom_vis):
                continue

            start_ts = ev.get("startTimestamp", 0)
            hora_arg = (datetime.fromtimestamp(start_ts) - timedelta(hours=0)).strftime("%H:%M hs (ARG)")
            estado = "🔴 *EN VIVO (LIVE)*" if ev.get("status", {}).get("type") == "inprogress" else "🟢 *PRE*"

            if deporte_nombre == "Tennis":
                rank_loc = local_obj.get("ranking")
                rank_vis = visita_obj.get("ranking")
                hay_wc, detalle_wc = motor_mismatches.evaluar_mismatch_tenis(nom_loc, nom_vis, rank_loc, rank_vis)

                if hay_wc:
                    pick = motor_mismatches.sugerir_mercado("Tennis", [detalle_wc], es_favorito_local=True)
                    enriquecer_y_enviar_alerta(
                        deporte="Tennis",
                        torneo=competicion,
                        nom_loc=nom_loc,
                        nom_vis=nom_vis,
                        hora_arg=hora_arg,
                        estado=estado,
                        alertas_base=[detalle_wc],
                        pick_base=pick
                    )
                partidos_notificados.add(id_unico)
                guardar_notificados(partidos_notificados)
                continue

            # Deportes de equipo
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

            hay_mismatch, alertas, pick = motor_mismatches.evaluar_mismatch(
                deporte=deporte_nombre,
                perf_local=perf_loc,
                perf_visita=perf_vis,
                triangulaciones=triangs,
                h2h=h2h_eval,
                tabla_local_visita=tabla_eval
            )

            if hay_mismatch:
                enriquecer_y_enviar_alerta(
                    deporte=deporte_nombre,
                    torneo=competicion,
                    nom_loc=nom_loc,
                    nom_vis=nom_vis,
                    hora_arg=hora_arg,
                    estado=estado,
                    alertas_base=alertas,
                    pick_base=pick
                )

            partidos_notificados.add(id_unico)
            guardar_notificados(partidos_notificados)


if __name__ == "__main__":
    print("Radar Cuantitativo Multideporte Femenino 360° desplegado...", flush=True)
    enviar_telegram("🤖 *Radar Femenino 360° Activo:* Orquestador protegido contra cierres.")

    while True:
        try:
            ejecutar_barrido_radar()
        except Exception as e:
            print(f"Error en ciclo de barrido: {e}", flush=True)

        time.sleep(INTERVALO_REVISION)