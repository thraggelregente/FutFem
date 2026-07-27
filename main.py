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

    def do_HEAD(self):
        # UptimeRobot y otros monitores suelen chequear con HEAD, no GET.
        # Sin este método, el servidor respondía 501 y el monitor marcaba "Down".
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        # Evita inundar los logs de Render con una línea por cada ping del monitor
        pass

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
ODDSPAPI_API_KEY = os.environ.get("ODDSPAPI_API_KEY")

INTERVALO_REVISION = 600  # 10 minutos - ciclo principal (The Odds API, /events no gasta cuota)
INTERVALO_ODDSPAPI = 4 * 3600  # 4 horas - OddsPapi especializado solo en fútbol (250/mes total)
INTERVALO_HIGHLIGHTLY = 30 * 60  # 30 minutos - Highlightly tiene 100/día POR sub-API (vóley y handball por separado)

ODDSPAPI_BASE = "https://api.oddspapi.io/v4"

HIGHLIGHTLY_API_KEY = os.environ.get("HIGHLIGHTLY_API_KEY")
# Bases confirmadas contra la documentación real de cada sub-API
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

# Timestamps del último chequeo de cada fuente de intervalo largo (arrancan en 0 para chequear ya al iniciar)
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


def notificar_si_nuevo(fuente, id_externo, deporte, torneo, local, visitante, horario_formateado, estado):
    """Función compartida por las 3 fuentes: arma el mensaje, evita duplicados (con ID prefijado
    por fuente para que no choquen entre sí) y persiste. Devuelve True si notificó."""
    global partidos_notificados
    id_unico = f"{fuente}_{id_externo}"

    if id_unico in partidos_notificados:
        return False

    mensaje = (
        f"🚨 *¡NUEVO PARTIDO FEMENINO DETECTADO!*\n\n"
        f"Status: {estado}\n"
        f"🏅 *Deporte:* {deporte}\n"
        f"🏆 *Torneo:* {torneo}\n"
        f"⚔️ *Encuentro:* {local} vs {visitante}\n"
        f"🕒 *Horario:* {horario_formateado}\n"
        f"📡 *Fuente:* {fuente}\n"
    )
    enviar_telegram(mensaje)
    partidos_notificados.add(id_unico)
    guardar_notificados(partidos_notificados)
    print(f"[{datetime.now().strftime('%H:%M')}] Notificado ({fuente}): {local} vs {visitante}", flush=True)
    return True


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
        deporte_grupo = deporte.get("group", "Deporte")

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
                notificar_si_nuevo(
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
    """Fútbol, vóley y handball femenino vía OddsPapi — UNA sola llamada cubre los 3 (y todo lo
    demás que soporta OddsPapi) porque al omitir sportId trae todo mezclado. Corre en paralelo a
    Highlightly sin coordinarse entre sí — puede repetir partidos que Highlightly ya avisó, y
    está bien así (cada fuente tiene su propio prefijo de ID, no se pisan en la persistencia)."""
    if not ODDSPAPI_API_KEY:
        return

    hoy = datetime.utcnow().date()
    desde = hoy.isoformat()
    hasta = (hoy + timedelta(days=1)).isoformat()  # <2 días de rango, requisito sin sportId

    sports_de_interes = {10: "Soccer", 22: "Handball", 23: "Volleyball"}
    url = f"{ODDSPAPI_BASE}/fixtures"
    params = {"apiKey": ODDSPAPI_API_KEY, "from": desde, "to": hasta}

    try:
        respuesta = requests.get(url, params=params, timeout=20)
        if respuesta.status_code != 200:
            print(f"Error en OddsPapi ({respuesta.status_code}): {respuesta.text}", flush=True)
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

        if fixture_id and es_partido_femenino_valido(torneo, local, visitante):
            notificar_si_nuevo(
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
    """Fútbol, vóley y handball femenino vía Highlightly. Cada deporte es una sub-API
    independiente con su propia cuota de 100 requests/día. Consulta hoy y mañana (2 llamadas
    por deporte por ciclo). Corre en paralelo a OddsPapi sin problema si se solapan partidos."""
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
                    print(f"Error en Highlightly ({nombre_deporte}, {fecha}) ({respuesta.status_code}): {respuesta.text}", flush=True)
                    continue
                data = respuesta.json().get("data", [])
            except Exception as e:
                print(f"Error de conexión con Highlightly ({nombre_deporte}, {fecha}): {e}", flush=True)
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

                if match_id and es_partido_femenino_valido(torneo, local, visitante):
                    notificar_si_nuevo(
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
    print("Radar Femenino desplegado en Render...", flush=True)
    enviar_telegram("🤖 *Radar Femenino 24/7 Activado en Render:* Escuchando partidos de forma segura.")

    while True:
        revisar_partidos_nuevos()  # The Odds API - básquet, cada ciclo (10 min)

        ahora_ts = time.time()

        if ahora_ts - ultimo_check_oddspapi >= INTERVALO_ODDSPAPI:
            revisar_oddspapi()  # fútbol + vóley + handball (1 llamada), cada 4 horas
            ultimo_check_oddspapi = ahora_ts

        if ahora_ts - ultimo_check_highlightly >= INTERVALO_HIGHLIGHTLY:
            revisar_highlightly()  # fútbol + vóley + handball (3 sub-APIs), cada 30 min
            ultimo_check_highlightly = ahora_ts

        time.sleep(INTERVALO_REVISION)
