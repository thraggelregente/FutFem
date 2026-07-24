import requests
import time
import re
import os
import json
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- SERVIDOR WEB FANTASMA (necesario para Render Web Service) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Radar Femenino 24/7 OK")

def iniciar_servidor_web():
    puerto = int(os.environ.get("PORT", 10000))
    servidor = HTTPServer(('0.0.0.0', puerto), SimpleHandler)
    servidor.serve_forever()

Thread(target=iniciar_servidor_web, daemon=True).start()
# -------------------------------------------------------------

# Lectura segura desde las variables de entorno
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

INTERVALO_REVISION = 600  # 10 minutos (antes 90 min). /events no gasta cuota de la API.
ARCHIVO_NOTIFICADOS = "notificados.json"


# ---------- PERSISTENCIA DE PARTIDOS YA NOTIFICADOS ----------
def cargar_notificados():
    if os.path.exists(ARCHIVO_NOTIFICADOS):
        try:
            with open(ARCHIVO_NOTIFICADOS, "r") as f:
                return set(json.load(f))
        except Exception as e:
            print(f"Error leyendo {ARCHIVO_NOTIFICADOS}: {e}", flush=True)
    return set()

def guardar_notificados(notificados):
    try:
        with open(ARCHIVO_NOTIFICADOS, "w") as f:
            json.dump(list(notificados), f)
    except Exception as e:
        print(f"Error guardando {ARCHIVO_NOTIFICADOS}: {e}", flush=True)

partidos_notificados = cargar_notificados()
# ---------------------------------------------------------------


def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error enviando mensaje a Telegram: {e}", flush=True)


def es_partido_femenino_valido(nombre_torneo, equipo1, equipo2):
    texto_completo = f"{nombre_torneo} {equipo1} {equipo2}".lower()

    palabras_tenis = ["tennis", "wta", "itf"]
    if any(t in texto_completo for t in palabras_tenis):
        return False

    # Patrones de palabra completa (funcionan con o sin espacio antes del paréntesis)
    patrones_femeninos = [
        r'\bwomen\b', r'\bwomens\b', r'\bwom\b', r'\bfemenino\b', r'\bfemenina\b',
        r'\bfem\b', r'\bladies\b', r'\bnwsl\b', r'\bwsl\b', r'\bwnba\b',
    ]
    if any(re.search(patron, texto_completo) for patron in patrones_femeninos):
        return True

    # Marcador suelto de una sola letra: (w), (f) -- con o sin espacio antes del paréntesis.
    # Sin \b pegado al paréntesis, porque el espacio rompe el límite de palabra ahí.
    if re.search(r'\((w|f)\)', texto_completo):
        return True

    # Marcador de una sola letra SIN paréntesis (ej. "Twente W", "PSG F"), chequeado
    # campo por campo (no en el texto concatenado) para evitar falsos positivos
    # cruzados entre torneo/equipos.
    for campo in (nombre_torneo, equipo1, equipo2):
        campo_l = (campo or "").lower().strip()
        if re.search(r'(^|\s)-?[wf]$', campo_l):
            return True

    return False


def obtener_deportes_activos():
    """Lista de deportes/ligas activos. No consume cuota de la API."""
    url = "https://api.the-odds-api.com/v4/sports"
    params = {"apiKey": ODDS_API_KEY}
    try:
        respuesta = requests.get(url, params=params, timeout=10)
        if respuesta.status_code != 200:
            print(f"Error obteniendo lista de deportes ({respuesta.status_code}): {respuesta.text}", flush=True)
            return []
        return respuesta.json()
    except Exception as e:
        print(f"Error de conexión al listar deportes: {e}", flush=True)
        return []


def revisar_partidos_nuevos():
    global partidos_notificados

    deportes = obtener_deportes_activos()
    if not deportes:
        print("No se pudo obtener la lista de deportes, se reintenta en el próximo ciclo.", flush=True)
        return

    ahora_arg = datetime.utcnow() - timedelta(hours=3)

    for deporte in deportes:
        sport_key = deporte.get("key")
        if not sport_key:
            continue

        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events"
        params = {
            "apiKey": ODDS_API_KEY,
            "dateFormat": "iso"
        }

        try:
            respuesta = requests.get(url, params=params, timeout=10)
            if respuesta.status_code != 200:
                # Si falla un deporte puntual, seguimos con el resto sin cortar el ciclo
                print(f"Error en /{sport_key}/events ({respuesta.status_code}): {respuesta.text}", flush=True)
                continue
            partidos = respuesta.json()
        except Exception as e:
            print(f"Error de conexión revisando {sport_key}: {e}", flush=True)
            continue

        for partido in partidos:
            partido_id = partido.get("id")
            torneo = partido.get("sport_title", "Torneo Desconocido")
            local = partido.get("home_team", "Local")
            visitante = partido.get("away_team", "Visitante")

            fecha_str = partido.get("commence_time", "")
            if fecha_str:
                fecha_utc = datetime.fromisoformat(fecha_str.replace("Z", "+00:00")).replace(tzinfo=None)
                fecha_arg = fecha_utc - timedelta(hours=3)
                horario_formateado = fecha_arg.strftime("%d/%m/%Y %H:%M hs (ARG)")
            else:
                fecha_arg = None
                horario_formateado = "A confirmar"

            estado = "🔴 *EN VIVO / EN JUEGO*" if (fecha_arg and fecha_arg <= ahora_arg) else "📅 *PRÓXIMO PARTIDO*"

            if es_partido_femenino_valido(torneo, local, visitante):
                if partido_id not in partidos_notificados:
                    mensaje = (
                        f"🚨 *¡NUEVO PARTIDO FEMENINO DETECTADO!*\n\n"
                        f"Status: {estado}\n"
                        f"🏆 *Torneo:* {torneo}\n"
                        f"⚔️ *Encuentro:* {local} vs {visitante}\n"
                        f"🕒 *Horario:* {horario_formateado}\n"
                    )

                    enviar_telegram(mensaje)
                    partidos_notificados.add(partido_id)
                    guardar_notificados(partidos_notificados)
                    print(f"[{datetime.now().strftime('%H:%M')}] Notificado: {local} vs {visitante} ({sport_key})", flush=True)


if __name__ == "__main__":
    print("Radar Femenino desplegado en Render...", flush=True)
    enviar_telegram("🤖 *Radar Femenino 24/7 Activado en Render:* Escuchando partidos de forma segura.")

    while True:
        revisar_partidos_nuevos()
        time.sleep(INTERVALO_REVISION)
