import requests
import time
import re
import os
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- SERVIDOR WEB FANTASMA PARA ENGAÑAR A RENDER ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Radar Femenino 24/7 OK")

def iniciar_servidor_web():
    puerto = int(os.environ.get("PORT", 10000))
    servidor = HTTPServer(('0.0.0.0', puerto), SimpleHandler)
    servidor.serve_forever()

# Arranca el servidor web en segundo plano
Thread(target=iniciar_servidor_web, daemon=True).start()
# ---------------------------------------------------

TELEGRAM_TOKEN = "8848140762:AAHZhzNMqo5Fm7Be0JIdZgMfYE2v1h9cdzE"
CHAT_ID = "5039163388"
ODDS_API_KEY = "8414fdfc89da67c274eaa7afcd5c6023"

# 5400 segundos = 1 hora y media
INTERVALO_REVISION = 5400 

partidos_notificados = set()

def enviar_telegram(mensaje):
    """Envía un mensaje a Telegram directamente."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error enviando mensaje a Telegram: {e}")

def es_partido_femenino_valido(nombre_torneo, equipo1, equipo2):
    texto_completo = f"{nombre_torneo} {equipo1} {equipo2}".lower()
    
    palabras_tenis = ["tennis", "wta", "itf"]
    if any(t in texto_completo for t in palabras_tenis):
        return False

    patrones_femeninos = [
        r'\bwomen\b', r'\bwom\b', r'\bfemenino\b', r'\bfemenina\b', 
        r'\bfem\b', r'\bladies\b', r'\bnwsl\b', r'\bwsl\b', r'\bwnba\b',
        r'\b\(w\)\b', r'\b\(f\)\b', r'\b-w\b', r'\b_w\b'
    ]
    
    return any(re.search(patron, texto_completo) for patron in patrones_femeninos)

def revisar_partidos_nuevos():
    url = "https://api.the-odds-api.com/v4/sports/upcoming/events"
    params = {
        "apiKey": ODDS_API_KEY,
        "dateFormat": "iso"
    }

    try:
        respuesta = requests.get(url, params=params, timeout=10)
        if respuesta.status_code != 200:
            print(f"Error en la API ({respuesta.status_code}): {respuesta.text}")
            return

        partidos = respuesta.json()

        for partido in partidos:
            partido_id = partido.get("id")
            torneo = partido.get("sport_title", "Torneo Desconocido")
            local = partido.get("home_team", "Local")
            visitante = partido.get("away_team", "Visitante")

            fecha_str = partido.get("commence_time", "")
            if fecha_str:
                fecha_utc = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
                fecha_arg = fecha_utc - timedelta(hours=3)
                horario_formateado = fecha_arg.strftime("%d/%m/%Y %H:%M hs (ARG)")
            else:
                horario_formateado = "A confirmar"

            ahora_arg = datetime.now()
            estado = "🔴 *EN VIVO / EN JUEGO*" if (fecha_str and fecha_arg <= ahora_arg) else "📅 *PRÓXIMO PARTIDO*"

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
                    print(f"[{datetime.now().strftime('%H:%M')}] Notificado: {local} vs {visitante}", flush=True)

    except Exception as e:
        print(f"Error de conexión: {e}", flush=True)

if __name__ == "__main__":
    print("Radar Femenino desplegado en Render...", flush=True)
    enviar_telegram("🤖 *Radar Femenino 24/7 Activado en Render:* Escuchando partidos sin interrupciones.")
    
    while True:
        revisar_partidos_nuevos()
        time.sleep(INTERVALO_REVISION)
