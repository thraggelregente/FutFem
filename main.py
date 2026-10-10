"""
main.py
Radar Mismatch Multideporte Femenino 360° — Multi-fuente
- Servidor web fantasma prioritario (garantiza estado LIVE en Render).
- Importación segura de módulos para evitar cierres prematuros.
- Solo partidos vigentes (no empezados / en juego), hora en ARG real, try/except por evento,
  persistencia de partidos ya vistos y resumen por etapa en cada barrido.
- Fuentes: ESPN API, API-Football, TheSportsDB, FlashScore (scraping).
"""

import html
import os
import re
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import requests


# --- 1. SERVIDOR WEB FANTASMA ---
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
    try:
        servidor = HTTPServer(("0.0.0.0", puerto), SimpleHandler)
        servidor.serve_forever()
    except OSError as e:
        print(f"Servidor web no iniciado ({e}); el radar continúa sin él", flush=True)


Thread(target=iniciar_servidor_web, daemon=True).start()
# --------------------------------------------------------------------------

import utilidades as U  # noqa: E402

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
CHAT_ID_GRUPO = os.environ.get("CHAT_ID_GRUPO")


def _sin_html(texto):
    return html.unescape(re.sub(r"<[^>]+>", "", texto))


def enviar_telegram(mensaje_html):
    if not TELEGRAM_TOKEN:
        U.log("Telegram: falta TELEGRAM_TOKEN, no se envía")
        return False
    destinos = [c for c in (CHAT_ID, CHAT_ID_GRUPO) if c]
    if not destinos:
        U.log("Telegram: faltan CHAT_ID / CHAT_ID_GRUPO, no se envía")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    mensaje_html = mensaje_html[:4000]
    llego = False

    for destino in destinos:
        for modo in ("HTML", None):
            payload = {
                "chat_id": destino,
                "text": mensaje_html if modo else _sin_html(mensaje_html),
                "disable_web_page_preview": True,
            }
            if modo:
                payload["parse_mode"] = modo
            try:
                r = requests.post(url, json=payload, timeout=10)
            except requests.RequestException as e:
                U.log(f"Telegram: error de red ({type(e).__name__}) con chat {destino}")
                break

            if r.status_code == 200:
                llego = True
                break
            if r.status_code == 429:
                try:
                    espera = int(r.json().get("parameters", {}).get("retry_after", 3))
                except Exception:
                    espera = 3
                time.sleep(min(espera, 30))
                continue
            U.log(f"Telegram: HTTP {r.status_code} con chat {destino} (modo {modo}): {r.text[:150]}")
            if r.status_code != 400:
                break

    return llego


# --- 2. IMPORTACIÓN DEFENSIVA DE MÓDULOS ---
try:
    import motor_mismatches
except Exception as e:
    motor_mismatches = None
    U.log(f"ERROR cargando motor_mismatches: {e}")
    enviar_telegram(f"⚠️ Error cargando motor_mismatches: {html.escape(str(e))}")

try:
    import fuente_espn
except Exception as e:
    fuente_espn = None
    U.log(f"ERROR cargando fuente_espn: {e}")

try:
    import fuente_api_football
except Exception as e:
    fuente_api_football = None
    U.log(f"ERROR cargando fuente_api_football: {e}")

try:
    import fuente_thesportsdb
except Exception as e:
    fuente_thesportsdb = None
    U.log(f"ERROR cargando fuente_thesportsdb: {e}")

try:
    import fuente_flashscore
except Exception as e:
    fuente_flashscore = None
    U.log(f"ERROR cargando fuente_flashscore: {e}")

try:
    import tracker_cuotas_smart
except Exception as e:
    tracker_cuotas_smart = None
    U.log(f"Aviso: tracker_cuotas_smart no disponible: {e}")

try:
    import metricas_profundas
except Exception as e:
    metricas_profundas = None
    U.log(f"Aviso: metricas_profundas no disponible: {e}")

try:
    import monitor_noticias
except Exception as e:
    monitor_noticias = None
    U.log(f"Aviso: monitor_noticias no disponible: {e}")


INTERVALO_REVISION = int(os.environ.get("INTERVALO_REVISION", "1800"))
ARCHIVO_NOTIFICADOS = "notificados.json"
MAX_ANALISIS_POR_CICLO = int(os.environ.get("MAX_ANALISIS_POR_CICLO", "200"))
HORAS_VENTANA_PREVIA = 24

# Deportes a analizar (internos)
DEPORTES_RADAR = ["Soccer", "Basketball", "Tennis", "Ice Hockey", "Volleyball", "Handball"]

# Fuentes activas: cada una es un módulo con `obtener_eventos(deporte)` y `es_femenino(evento)`
FUENTES_ACTIVAS = {
    "espn": fuente_espn,
    "api_football": fuente_api_football,
    "thesportsdb": fuente_thesportsdb,
    "flashscore": fuente_flashscore,
}

registro = U.RegistroVistos(ARCHIVO_NOTIFICADOS)
_cache_historial = U.CacheTTL(3 * 3600)


# ---------------------------------------------------------------------------
# FILTRO FEMENINO ESTRICTO
# ---------------------------------------------------------------------------
_RE_MASCULINO = re.compile(
    r"\b("
    r"atp|challenger|davis cup|"
    r"men|mens|men's|masculino|masculin|herren|hommes|maschile|"
    r"nba|nfl|nhl|mlb|mls|"
    r"j1 league|j2 league|j3 league|"
    r"bundesliga|serie a|premier league|la liga|ligue 1|eredivisie|"
    r"liga mx|superliga|allsvenskan|eliteserien|superligaen"
    r")\b"
)

_KEYWORDS_FEM = re.compile(
    r"\b("
    r"women|womens|women's|woman|"
    r"fem|femenil|femenino|femenina|"
    r"feminin|feminine|femminile|"
    r"dames|damen|frauen|"
    r"ladies|"
    r"wta|wnba|nwsl|wsl|"
    r"kvinde|kvindeligaen|"
    r"damallsvenskan|toppserien|"
    r"we league|"
    r"liga f|"
    r"serie a fem|"
    r"division 1 fem|"
    r"frauen-bundesliga|"
    r"eredivisie vrouwen|"
    r"campeonato nacional feminino|"
    r"primera division femenina|"
    r"primera división femenina|"
    r"brasileirao feminino|"
    r"brasileirão feminino|"
    r"a-league women|"
    r"liga mx femenil|"
    r"ncaa women|"
    r"shebelieves|"
    r"concacaf w|"
    r"uefa women|"
    r"fifa women|"
    r"w gold cup|"
    r"w champions"
    r")\b"
)


def es_deporte_femenino_valido(torneo, local, visita):
    """
    Filtro femenino estricto: acepta solo si el torneo contiene palabras clave femeninas.
    """
    texto = f"{torneo} {local} {visita}".lower()
    if _RE_MASCULINO.search(texto):
        return False
    if not _KEYWORDS_FEM.search(texto):
        return False
    return True


# ---------------------------------------------------------------------------
# ALERTA
# ---------------------------------------------------------------------------
def _seguro(funcion, *args, defecto=None, **kwargs):
    try:
        return funcion(*args, **kwargs)
    except Exception as e:
        U.log(f"Aviso: falló {getattr(funcion, '__name__', '?')}: {type(e).__name__}: {e}")
        return defecto


def enriquecer_y_enviar_alerta(deporte, torneo, nom_loc, nom_vis, hora_txt, estado,
                               alertas_base, pick_base, favorito, confianza="Media", superficie=None):
    nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
    detalles = list(alertas_base)

    if metricas_profundas:
        if deporte == "Soccer":
            p = _seguro(metricas_profundas.obtener_presion_ofensiva_futbol, nom_fav, defecto={}) or {}
            if p.get("alta_presion"):
                detalles.append(
                    f"Presión ScoreBing: {p['prom_corners_favor']} córners a favor vs "
                    f"{p['prom_corners_contra']} recibidos"
                )
        elif deporte == "Tennis":
            perfil = _seguro(metricas_profundas.consultar_perfil_tenis_abstract,
                             nom_fav, superficie or "", defecto={}) or {}
            if perfil.get("es_vulnerable_superficie"):
                detalles.append(
                    f"⚠️ Advertencia superficie: la favorita tiene win rate bajo en "
                    f"{perfil['superficie']} ({perfil['efectividad_superficie']})"
                )

    if monitor_noticias:
        nov = _seguro(monitor_noticias.buscar_novedades_partido, nom_loc, nom_vis, defecto={}) or {}
        if nov.get("alerta_novedad"):
            etiqueta = "⚠️ Último momento (afecta al favorito)" if nov.get("equipo") == favorito else "Último momento"
            detalles.append(f"{etiqueta}: {nov['fragmento']}")

    estado_mercado = "Línea abierta en bookies locales"
    if tracker_cuotas_smart:
        odds = _seguro(tracker_cuotas_smart.analizar_mercado_evento,
                       nom_loc, nom_vis, favorito, deporte, defecto={}) or {}
        if odds.get("disponible"):
            estado_mercado = odds.get("resumen", estado_mercado)

    esc = html.escape
    detalles_txt = "\n".join(f"• {esc(str(d))}" for d in detalles)
    mensaje = (
        "🚨 <b>MISMATCH DETECTADO — RADAR FEMENINO</b>\n\n"
        f"Status: {estado}\n"
        f"🏅 <b>Deporte:</b> {esc(deporte)}\n"
        f"🏆 <b>Competición:</b> {esc(torneo)}\n"
        f"⚔️ <b>Encuentro:</b> {esc(nom_loc)} vs {esc(nom_vis)}\n"
        f"⭐ <b>Favorito:</b> {esc(nom_fav)} ({esc(favorito)})\n"
        f"🕒 <b>Horario:</b> {esc(hora_txt)}\n\n"
        f"📊 <b>La clave del mismatch:</b>\n{detalles_txt}\n\n"
        f"🎯 <b>Mercado sugerido:</b> {esc(pick_base)}\n"
        f"📈 <b>Estado del mercado:</b> {esc(estado_mercado)}\n"
        f"🔥 <b>Confianza:</b> {esc(confianza)}"
    )
    enviado = enviar_telegram(mensaje)
    U.log(f"-> MISMATCH ({deporte}): {nom_loc} vs {nom_vis} | favorito: {nom_fav} | "
          f"telegram: {'ok' if enviado else 'NO ENVIADO'}")


# ---------------------------------------------------------------------------
# BARRIDO MULTI-FUENTE
# ---------------------------------------------------------------------------
def _nuevo_stat():
    return {"eventos": 0, "femeninos": 0, "ya_vistos": 0, "no_vigentes": 0, "lejanos": 0,
            "analizados": 0, "alertas": 0, "errores": 0}


def _parsear_record(rec):
    if not rec:
        return None, None
    try:
        partes = re.split(r"[-–]", str(rec).strip())
        wins = int(partes[0])
        losses = int(partes[1]) if len(partes) > 1 else 0
        return wins, losses
    except Exception:
        return None, None


def _procesar_evento(evento, st):
    """Procesa un evento normalizado (venga de la fuente que venga)."""
    id_unico = evento["id"]

    if registro.visto(id_unico):
        st["ya_vistos"] += 1
        return False

    tipo_estado = evento.get("tipo_estado", "pre")
    if tipo_estado not in ("pre", "in"):
        st["no_vigentes"] += 1
        return False

    ahora_ts = time.time()
    if tipo_estado == "pre" and evento.get("startTimestamp", 0) > ahora_ts + HORAS_VENTANA_PREVIA * 3600:
        st["lejanos"] += 1
        return False

    nom_loc = evento["local"]["nombre"]
    nom_vis = evento["visita"]["nombre"]
    torneo = evento["torneo"]
    deporte = evento["deporte"]

    if not es_deporte_femenino_valido(torneo, nom_loc, nom_vis):
        return False
    st["femeninos"] += 1

    hora_txt = evento["horario"]
    estado = "🔴 <b>EN VIVO (LIVE)</b>" if tipo_estado == "in" else "🟢 <b>PRE</b>"
    st["analizados"] += 1

    # Tenis
    if deporte == "Tennis":
        ranking_loc = evento["local"].get("ranking")
        ranking_vis = evento["visita"].get("ranking")
        hay, detalle, favorito = motor_mismatches.evaluar_mismatch_tenis(
            nom_loc, nom_vis, ranking_loc, ranking_vis
        )
        if hay:
            nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
            enriquecer_y_enviar_alerta(
                deporte="Tennis", torneo=torneo, nom_loc=nom_loc, nom_vis=nom_vis,
                hora_txt=hora_txt, estado=estado, alertas_base=[detalle],
                pick_base=motor_mismatches.sugerir_mercado("Tennis", favorito, nom_fav),
                favorito=favorito, confianza="Media",
            )
            st["alertas"] += 1
        registro.marcar(id_unico)
        return True

    # Deportes de equipo
    record_loc = evento["local"].get("record") or ""
    record_vis = evento["visita"].get("record") or ""
    ranking_loc = evento["local"].get("ranking")
    ranking_vis = evento["visita"].get("ranking")

    wl, ll = _parsear_record(record_loc)
    wv, lv = _parsear_record(record_vis)

    favorito = None
    detalle = ""

    if wl is not None and wv is not None:
        total_l = wl + ll
        total_v = wv + lv
        if total_l >= 3 and total_v >= 3:
            tasa_l = wl / total_l
            tasa_v = wv / total_v
            if tasa_l >= 0.60 and tasa_v <= 0.35 and (wl - wv) >= 3:
                favorito = motor_mismatches.LOCAL
                detalle = (f"Récord: {nom_loc} {record_loc} ({round(tasa_l*100)}%) "
                           f"vs {nom_vis} {record_vis} ({round(tasa_v*100)}%)")
            elif tasa_v >= 0.60 and tasa_l <= 0.35 and (wv - wl) >= 3:
                favorito = motor_mismatches.VISITA
                detalle = (f"Récord: {nom_vis} {record_vis} ({round(tasa_v*100)}%) "
                           f"vs {nom_loc} {record_loc} ({round(tasa_l*100)}%)")

    if favorito is None and ranking_loc and ranking_vis:
        try:
            rl, rv = int(ranking_loc), int(ranking_vis)
            if rl > 0 and rv > 0:
                if rl <= 15 and rv >= 50:
                    favorito = motor_mismatches.LOCAL
                    detalle = f"Ranking: {nom_loc} #{rl} vs {nom_vis} #{rv}"
                elif rv <= 15 and rl >= 50:
                    favorito = motor_mismatches.VISITA
                    detalle = f"Ranking: {nom_vis} #{rv} vs {nom_loc} #{rl}"
        except (ValueError, TypeError):
            pass

    if favorito:
        nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
        enriquecer_y_enviar_alerta(
            deporte=deporte, torneo=torneo, nom_loc=nom_loc, nom_vis=nom_vis,
            hora_txt=hora_txt, estado=estado, alertas_base=[detalle],
            pick_base=motor_mismatches.sugerir_mercado(deporte, favorito, nom_fav),
            favorito=favorito, confianza="Media",
        )
        st["alertas"] += 1

    registro.marcar(id_unico)
    return True


def _barrido_fuente(nombre_fuente, modulo, resumen):
    """Ejecuta el barrido para una fuente concreta."""
    if modulo is None:
        U.log(f"[{nombre_fuente}] módulo no disponible, se omite")
        return

    for deporte in DEPORTES_RADAR:
        clave_stat = f"{nombre_fuente}_{deporte}"
        st = resumen.setdefault(clave_stat, _nuevo_stat())

        try:
            eventos = modulo.obtener_eventos(deporte)
        except Exception as e:
            U.log(f"[{nombre_fuente}] Error obteniendo {deporte}: {type(e).__name__}: {e}")
            continue

        st["eventos"] = len(eventos)
        U.log(f"[{nombre_fuente}] {deporte}: {len(eventos)} eventos")

        for ev in eventos:
            try:
                if _procesar_evento(ev, st):
                    pass
            except Exception as e:
                st["errores"] += 1
                U.log(f"Error en evento {ev.get('id')} ({nombre_fuente}/{deporte}): {type(e).__name__}: {e}")
                registro.marcar(ev.get("id"))

            registro.guardar()


def _imprimir_resumen(resumen):
    U.log("--- Resumen del barrido ---")
    for etapa, st in resumen.items():
        U.log(
            f"{etapa}: {st['eventos']} eventos -> {st['femeninos']} femeninos -> "
            f"{st['analizados']} analizados -> {st['alertas']} alertas "
            f"(ya vistos {st['ya_vistos']}, no vigentes {st['no_vigentes']}, "
            f"lejanos {st['lejanos']}, errores {st['errores']})"
        )
    for fuente, codigos in U.ESTADISTICAS.items():
        U.log(f"fuente {fuente}: respuestas {dict(codigos)}")


def ejecutar_barrido_radar():
    U.reiniciar_estadisticas()
    U.log("Ejecutando barrido Radar Femenino 360° (multi-fuente)...")
    if motor_mismatches is None:
        U.log("motor_mismatches no está disponible: se omite el barrido")
        return

    registro.podar()
    resumen = {}

    for nombre, modulo in FUENTES_ACTIVAS.items():
        try:
            _barrido_fuente(nombre, modulo, resumen)
        except Exception as e:
            U.log(f"Error en fuente {nombre}: {type(e).__name__}: {e}")

    registro.guardar()
    _imprimir_resumen(resumen)


if __name__ == "__main__":
    U.log("Radar Cuantitativo Multideporte Femenino 360° (multi-fuente) desplegado...")
    U.log(f"Persistencia: {U.modo_persistencia()}")
    U.log(f"Fuentes activas: {list(FUENTES_ACTIVAS.keys())}")

    aviso = ("🤖 <b>Radar Femenino 360° (multi-fuente) activo.</b>\n"
             f"Persistencia: {html.escape(U.modo_persistencia())}\n"
             f"Fuentes: {', '.join(FUENTES_ACTIVAS.keys())}")
    if not U.persistencia_es_duradera():
        aviso += ("\n⚠️ Sin disco persistente: tras un deploy puede repetir alertas de partidos ya "
                  "avisados. Configurá UPSTASH_REDIS_REST_URL/TOKEN o DATA_DIR.")
    enviar_telegram(aviso)

    while True:
        try:
            ejecutar_barrido_radar()
        except Exception as e:
            U.log(f"Error en ciclo de barrido: {type(e).__name__}: {e}")

        time.sleep(INTERVALO_REVISION)