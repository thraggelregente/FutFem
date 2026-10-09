import requests
import time
import re
import os
import json
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from google import genai
from google.genai import types

# --- SERVIDOR WEB FANTASMA (necesario para Render Web Service) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Radar Femenino 24/7 OK")

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
# -------------------------------------------------------------

# Lectura segura desde variables de entorno
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
CHAT_ID_GRUPO = os.environ.get("CHAT_ID_GRUPO")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
ODDSPAPI_API_KEY = os.environ.get("ODDSPAPI_API_KEY")
HIGHLIGHTLY_API_KEY = os.environ.get("HIGHLIGHTLY_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Inicialización de cliente Gemini
ai_client = None
if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)

INTERVALO_REVISION = 600  # 10 minutos
INTERVALO_ODDSPAPI = 4 * 3600  # 4 horas
INTERVALO_HIGHLIGHTLY = 30 * 60  # 30 minutos

ODDSPAPI_BASE = "https://api.oddspapi.io/v4"
HIGHLIGHTLY_SPORTS = {
    "Soccer": "https://soccer.highlightly.net",
    "Volleyball": "https://volleyball.highlightly.net",
    "Handball": "https://handball.highlightly.net",
}
HIGHLIGHTLY_ESTADOS_FINALIZADOS = {
    "Finished", "Finished after penalties", "Finished after extra time",
    "Cancelled", "Postponed", "Abandoned",
}

ARCHIVO_NOTIFICADOS = "notificados.json"
ultimo_check_oddspapi = 0
ultimo_check_highlightly = 0


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
    if not TELEGRAM_TOKEN:
        print("Falta TELEGRAM_TOKEN", flush=True)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    destinos = [chat_id for chat_id in (CHAT_ID, CHAT_ID_GRUPO) if chat_id]

    for destino in destinos:
        payload = {
            "chat_id": destino,
            "text": mensaje,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Error enviando a Telegram (chat {destino}): {e}", flush=True)


def es_partido_femenino_valido(nombre_torneo, equipo1, equipo2):
    """Filtra y asegura que sea 100% deporte femenino (incluye tenis, voley, basket, futbol, etc.)."""
    texto_completo = f"{nombre_torneo} {equipo1} {equipo2}".lower()

    # Si es tenis femenino
    if any(t in texto_completo for t in ["wta", "itf women", "billie jean king"]):
        return True

    # Descartar tenis masculino de plano
    if any(t in texto_completo for t in ["atp", "challenger", "davis cup"]):
        return False

    patrones_femeninos = [
        r'\bwomen\b', r'\bwomens\b', r'\bwom\b', r'\bfemenino\b', r'\bfemenina\b',
        r'\bfem\b', r'\bladies\b', r'\bnwsl\b', r'\bwsl\b', r'\bwnba\b',
    ]
    if any(re.search(patron, texto_completo) for patron in patrones_femeninos):
        return True

    if re.search(r'\((w|f)\)', texto_completo):
        return True

    for campo in (nombre_torneo, equipo1, equipo2):
        campo_l = (campo or "").lower().strip()
        if re.search(r'(^|\s)-?[wf]$', campo_l):
            return True

    return False


def analizar_mismatch_ia(deporte, torneo, local, visitante):
    """
    Analiza con Gemini y búsqueda web si hay un desbalance deportivo real.
    """
    if not ai_client:
        return None

    ahora_str = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""
    Eres un Analista de Mismatches Multideporte de Élite especializado EXCLUSIVAMENTE en Deporte Femenino.
    Fecha actual: {ahora_str}.

    OBJETIVO:
    Determina si existe un DESEQUILIBRIO EXTREMO / ASIMETRÍA CLARA entre:
    - Deporte: {deporte}
    - Competición: {torneo}
    - Encuentro: {local} vs {visitante}

    JERARQUÍA DE ANÁLISIS:
    1. FORMA ACTUAL (MANDATORIO): Racha vigente y nivel en la temporada actual. Si un dato es viejo, descártalo.
    2. CONTEXTO RECIENTE: H2H de los últimos 12 meses.
    3. FACTORES DETERMINANTES:
       - Tenis: Wild Card (WC) sin ranking / amateur vs jugadora profesional activa.
       - Vóley/Basket/Handball/Fútbol: Puntero vs Colista hundido, diferencia de categoría en copas, o brechas técnicas abismales.

    REGLA DE SALIDA:
    - Si el partido es parejo, disputado o sin mismatch evidente, responde EXACTAMENTE: NO_MISMATCH
    - Si HAY mismatch claro, responde ÚNICAMENTE en JSON con esta estructura:
    {{
      "hay_mismatch": true,
      "resumen_clave": "Explicación concreta de 2 líneas sobre la asimetría y forma actual",
      "mercado_sugerido": "Pick recomendado (ej: Handicap -2.5 sets, Under X goles/puntos, Sets 2-0, etc.)",
      "confianza": "Alta / Muy Alta"
    }}
    """

    try:
        response = ai_client.models.generate_content(
            model='gemini-3.8-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )
        texto = (response.text or "").strip()
        if "NO_MISMATCH" in texto:
            return None

        if "```json" in texto:
            texto = texto.split("```json")[1].split("```")[0].strip()
        elif "```" in texto:
            texto = texto.split("```")[1].split("```")[0].strip()

        return json.loads(texto)
    except Exception as e:
        print(f"Error en análisis IA ({local} vs {visitante}): {e}", flush=True)
        return None


def evaluar_y_notificar(fuente, id_externo, deporte, torneo, local, visitante, horario_formateado, estado):
    global partidos_notificados
    id_unico = f"{fuente}_{id_externo}"

    if id_unico in partidos_notificados:
        return False

    if not es_partido_femenino_valido(torneo, local, visitante):
        return False

    print(f"[{datetime.now().strftime('%H:%M')}] Evaluando ({deporte}): {local} vs {visitante}...", flush=True)

    analisis = analizar_mismatch_ia(deporte, torneo, local, visitante)

    # Si es parejo, se marca en persistencia para no volver a gastar llamada
    if not analisis or not analisis.get("hay_mismatch"):
        partidos_notificados.add(id_unico)
        guardar_notificados(partidos_notificados)
        print(f"-> Descartado (parejo / sin mismatch): {local} vs {visitante}", flush=True)
        return False

    mensaje = (
        f"🚨 *MISMATCH DETECTADO — RADAR FEMENINO*\n\n"
        f"Status: {estado}\n"
        f"🏅 *Deporte:* {deporte}\n"
        f"🏆 *Competición:* {torneo}\n"
        f"⚔️ *Encuentro:* {local} vs {visitante}\n"
        f"🕒 *Horario:* {horario_formateado}\n\n"
        f"📊 *Clave del Desbalance:*\n{analisis.get('resumen_clave')}\n\n"
        f"🎯 *Mercado Sugerido:* {analisis.get('mercado_sugerido')}\n"
        f"🔥 *Confianza:* {analisis.get('confianza', 'Alta')}\n"
        f"📡 *Fuente:* {fuente}"
    )

    enviar_telegram(mensaje)
    partidos_notificados.add(id_unico)
    guardar_notificados(partidos_notificados)
    print(f"[{datetime.now().strftime('%H:%M')}] ¡MISMATCH NOTIFICADO! {local} vs {visitante}", flush=True)
    return True


def obtener_deportes_activos():
    url = "https://api.the-odds-api.com/v4/sports"
    params = {"apiKey": ODDS_API_KEY}
    try:
        respuesta = requests.get(url, params=params, timeout=10)
        if respuesta.status_code != 200:
            return []
        return respuesta.json()
    except Exception as e:
        print(f"Error al listar The Odds API: {e}", flush=True)
        return []


def revisar_partidos_nuevos():
    if not ODDS_API_KEY:
        return

    deportes = obtener_deportes_activos()
    if not deportes:
        return

    ahora_arg = datetime.utcnow() - timedelta(hours=3)

    for deporte in deportes:
        sport_key = deporte.get("key")
        if not sport_key:
            continue
        deporte_grupo = deporte.get("group", "Deporte")

        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events"
        params = {"apiKey": ODDS_API_KEY, "dateFormat": "iso"}

        try:
            respuesta = requests.get(url, params=params, timeout=10)
            if respuesta.status_code != 200:
                continue
            partidos = respuesta.json()
        except Exception:
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

            evaluar_y_notificar(
                fuente="theoddsapi",
                id_externo=partido_id,
                deporte=deporte_grupo,
                torneo=torneo,
                local=local,
                visitante=visitante,
                horario_formateado=horario_formateado,
                estado=estado,
            )


def revisar_oddspapi():
    if not ODDSPAPI_API_KEY:
        return

    hoy = datetime.utcnow().date()
    desde = hoy.isoformat()
    hasta = (hoy + timedelta(days=1)).isoformat()

    sports_de_interes = {10: "Soccer", 22: "Handball", 23: "Volleyball"}
    url = f"{ODDSPAPI_BASE}/fixtures"
    params = {"apiKey": ODDSPAPI_API_KEY, "from": desde, "to": hasta}

    try:
        respuesta = requests.get(url, params=params, timeout=20)
        if respuesta.status_code != 200:
            return
        fixtures = respuesta.json()
    except Exception as e:
        print(f"Error de conexión con OddsPapi: {e}", flush=True)
        return

    for fixture in fixtures:
        sport_id = fixture.get("sportId")
        if sport_id not in sports_de_interes:
            continue

        fixture_id = fixture.get("fixtureId")
        torneo = fixture.get("tournamentName", "Torneo Desconocido")
        local = fixture.get("participant1Name", "Local")
        visitante = fixture.get("participant2Name", "Visitante")
        status_name = fixture.get("statusName", "")

        fecha_str = fixture.get("startTime", "")
        if fecha_str:
            fecha_utc = datetime.fromisoformat(fecha_str.replace("Z", "+00:00")).replace(tzinfo=None)
            fecha_arg = fecha_utc - timedelta(hours=3)
            horario_formateado = fecha_arg.strftime("%d/%m/%Y %H:%M hs (ARG)")
        else:
            horario_formateado = "A confirmar"

        if status_name == "Live":
            estado = "🔴 *EN VIVO / EN JUEGO*"
        elif status_name == "Cancelled":
            continue
        else:
            estado = "📅 *PRÓXIMO PARTIDO*"

        evaluar_y_notificar(
            fuente="oddspapi",
            id_externo=fixture_id,
            deporte=sports_de_interes[sport_id],
            torneo=torneo,
            local=local,
            visitante=visitante,
            horario_formateado=horario_formateado,
            estado=estado,
        )


def revisar_highlightly():
    if not HIGHLIGHTLY_API_KEY:
        return

    headers = {"x-rapidapi-key": HIGHLIGHTLY_API_KEY}
    hoy = datetime.utcnow().date()
    fechas = [hoy.isoformat(), (hoy + timedelta(days=1)).isoformat()]

    for nombre_deporte, base_url in HIGHLIGHTLY_SPORTS.items():
        for fecha in fechas:
            url = f"{base_url}/matches"
            params = {"date": fecha, "timezone": "America/Argentina/Buenos_Aires"}

            try:
                respuesta = requests.get(url, headers=headers, params=params, timeout=20)
                if respuesta.status_code != 200:
                    continue
                data = respuesta.json().get("data", [])
            except Exception as e:
                print(f"Error de conexión con Highlightly ({nombre_deporte}): {e}", flush=True)
                continue

            for partido in data:
                match_id = partido.get("id")
                torneo = partido.get("league", {}).get("name", "Torneo Desconocido")
                local = partido.get("homeTeam", {}).get("name", "Local")
                visitante = partido.get("awayTeam", {}).get("name", "Visitante")
                descripcion_estado = partido.get("state", {}).get("description", "")

                if descripcion_estado in HIGHLIGHTLY_ESTADOS_FINALIZADOS:
                    continue

                fecha_str = partido.get("date", "")
                if fecha_str:
                    fecha_utc = datetime.fromisoformat(fecha_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    fecha_arg = fecha_utc - timedelta(hours=3)
                    horario_formateado = fecha_arg.strftime("%d/%m/%Y %H:%M hs (ARG)")
                else:
                    horario_formateado = "A confirmar"

                estado = "📅 *PRÓXIMO PARTIDO*" if descripcion_estado == "Not started" else "🔴 *EN VIVO / EN JUEGO*"

                evaluar_y_notificar(
                    fuente="highlightly",
                    id_externo=match_id,
                    deporte=nombre_deporte,
                    torneo=torneo,
                    local=local,
                    visitante=visitante,
                    horario_formateado=horario_formateado,
                    estado=estado,
                )


if __name__ == "__main__":
    print("Radar Femenino Inteligente (Sniper Mismatches) desplegado en Render...", flush=True)
    enviar_telegram("🤖 *Radar Analista Femenino Activado:* Filtrando exclusivamente mismatches reales.")

    while True:
        ahora_ts = time.time()

        if ahora_ts - ultimo_check_oddspapi >= INTERVALO_ODDSPAPI:
            revisar_oddspapi()
            ultimo_check_oddspapi = ahora_ts

        if ahora_ts - ultimo_check_highlightly >= INTERVALO_HIGHLIGHTLY:
            revisar_highlightly()
            ultimo_check_highlightly = ahora_ts

        revisar_partidos_nuevos()

        time.sleep(INTERVALO_REVISION)
