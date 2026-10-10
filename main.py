"""
main.py
Radar Mismatch Multideporte Femenino 360°

Flujo de cada barrido:
  1. Junta los partidos femeninos de las próximas 24 h:
       ESPN (principal, sin clave ni cuota)  +  API-Sports (secundaria, con presupuesto diario).
  2. Descarta duplicados entre fuentes y partidos ya avisados.
  3. Tenis: ranking (WTA). Deportes de equipo: historial de resultados -> motor de señales.
  4. Si hay mismatch, enriquece con noticias/cuotas y avisa por Telegram.
  5. Imprime un resumen por etapa y avisa por Telegram si una fuente quedó ciega.
"""

import html
import os
import re
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import requests


# --- 1. SERVIDOR WEB FANTASMA (arranca primero: Render exige un puerto abierto) ---
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
    try:
        HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), SimpleHandler).serve_forever()
    except OSError as e:
        print(f"Servidor web no iniciado ({e}); el radar continúa sin él", flush=True)


Thread(target=iniciar_servidor_web, daemon=True).start()
# ---------------------------------------------------------------------------------

import utilidades as U  # noqa: E402

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
CHAT_ID_GRUPO = os.environ.get("CHAT_ID_GRUPO")


def _sin_html(texto):
    return html.unescape(re.sub(r"<[^>]+>", "", texto))


def enviar_telegram(mensaje_html):
    """HTML con los campos escapados; si Telegram rechaza el formato (400) reintenta en texto plano.
    Loguea cada fallo (antes un token o chat_id mal cargado fallaba sin dejar rastro)."""
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
            payload = {"chat_id": destino, "disable_web_page_preview": True,
                       "text": mensaje_html if modo else _sin_html(mensaje_html)}
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
def _importar(nombre, critico=False):
    try:
        return __import__(nombre)
    except Exception as e:
        U.log(f"{'ERROR' if critico else 'Aviso'}: no pude cargar {nombre}: {type(e).__name__}: {e}")
        return None


motor_mismatches = _importar("motor_mismatches", critico=True)
fuente_espn = _importar("fuente_espn")
fuente_api_football = _importar("fuente_api_football")
tracker_cuotas_smart = _importar("tracker_cuotas_smart")
monitor_noticias = _importar("monitor_noticias")

INTERVALO_REVISION = int(os.environ.get("INTERVALO_REVISION", "1800"))
ARCHIVO_NOTIFICADOS = "notificados.json"
MAX_ANALISIS_POR_CICLO = int(os.environ.get("MAX_ANALISIS_POR_CICLO", "100"))
HORAS_VENTANA_PREVIA = 24
DEPORTES_RADAR = ["Soccer", "Basketball", "Tennis", "Ice Hockey", "Handball", "Volleyball", "Rugby"]

registro = U.RegistroVistos(ARCHIVO_NOTIFICADOS)
_ultimo_aviso_ciego = 0.0


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
                               alertas_base, pick_base, favorito, confianza="Media"):
    nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
    detalles = list(alertas_base)

    if monitor_noticias:
        nov = _seguro(monitor_noticias.buscar_novedades_partido, nom_loc, nom_vis, defecto={}) or {}
        if nov.get("alerta_novedad"):
            etiqueta = "⚠️ Último momento (afecta al favorito)" if nov.get("equipo") == favorito else "Último momento (rival)"
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
    return enviado


# ---------------------------------------------------------------------------
# ANÁLISIS DE UN EVENTO
# ---------------------------------------------------------------------------
def _nuevo_stat():
    return {"eventos": 0, "femeninos": 0, "ya_vistos": 0, "no_vigentes": 0, "lejanos": 0,
            "sin_datos": 0, "analizados": 0, "alertas": 0, "errores": 0}


def _historial(evento, lado):
    fuente = fuente_espn if evento["fuente"] == "espn" else fuente_api_football
    if fuente is None:
        return []
    return _seguro(fuente.historial_equipo, evento, lado, defecto=[]) or []


def _h2h_desde_historial(hist_local, id_visita):
    """Cruces directos que aparecen en el historial del local (solo lo que cubre la fuente)."""
    return [p for p in hist_local if id_visita in (p.get("id_local"), p.get("id_visita"))]


def _procesar_evento(ev, st, ahora_ts):
    clave = ev["clave"]
    if registro.visto(clave):
        st["ya_vistos"] += 1
        return False
    if ev.get("tipo_estado") != "pre":
        st["no_vigentes"] += 1
        return False
    if ev.get("startTimestamp", 0) > ahora_ts + HORAS_VENTANA_PREVIA * 3600:
        st["lejanos"] += 1
        return False

    nom_loc, nom_vis = ev["local"]["nombre"], ev["visita"]["nombre"]
    if not (ev.get("femenino_seguro") or U.es_femenino(ev["torneo"], nom_loc, nom_vis)):
        return False
    st["femeninos"] += 1

    deporte, estado = ev["deporte"], "🟢 <b>PRE</b>"

    # --- Tenis: ranking ---
    if deporte == "Tennis":
        sin_ranking = (ev["local"].get("ranking") is None and ev["visita"].get("ranking") is None
                       and not ev["local"].get("fuera_ranking") and not ev["visita"].get("fuera_ranking"))
        if sin_ranking:
            # El ranking WTA no cargó: no se marca como visto para reintentar en el próximo barrido.
            st["sin_datos"] += 1
            return False
        st["analizados"] += 1
        hay, detalle, favorito, pts = motor_mismatches.evaluar_mismatch_tenis(
            nom_loc, nom_vis, ev["local"].get("ranking"), ev["visita"].get("ranking"),
            fuera_local=ev["local"].get("fuera_ranking", False),
            fuera_visita=ev["visita"].get("fuera_ranking", False),
        )
        if hay and pts >= 2:
            nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
            enriquecer_y_enviar_alerta(
                deporte, ev["torneo"], nom_loc, nom_vis, ev["horario"], estado, [detalle],
                motor_mismatches.sugerir_mercado("Tennis", favorito, nom_fav),
                favorito, "Alta" if pts >= 3 else "Media",
            )
            st["alertas"] += 1
        registro.marcar(clave)
        return True

    # --- Deportes de equipo ---
    id_loc, id_vis = ev["local"]["id"], ev["visita"]["id"]
    forma_loc, forma_vis = _historial(ev, "local"), _historial(ev, "visita")
    if not forma_loc or not forma_vis:
        # Sin historial no hay análisis posible. No se marca como visto: se reintenta en el
        # próximo barrido (por ejemplo, cuando se renueva la cuota de la API).
        st["sin_datos"] += 1
        return False
    st["analizados"] += 1

    perf_loc = motor_mismatches.evaluar_rendimiento_reciente(forma_loc, id_loc)
    perf_vis = motor_mismatches.evaluar_rendimiento_reciente(forma_vis, id_vis)
    triangs = motor_mismatches.triangular_rivales(forma_loc, id_loc, forma_vis, id_vis)
    h2h = motor_mismatches.analizar_h2h_extendido(_h2h_desde_historial(forma_loc, id_vis), id_loc, id_vis)

    res = motor_mismatches.evaluar_mismatch(
        deporte=deporte, perf_local=perf_loc, perf_visita=perf_vis,
        triangulaciones=triangs, h2h=h2h, tabla_local_visita=None,
        datos_extra={
            "descanso": motor_mismatches.evaluar_descanso(forma_loc, id_loc, forma_vis, id_vis),
            "racha_local": motor_mismatches.evaluar_momentum(forma_loc, id_loc),
            "racha_visita": motor_mismatches.evaluar_momentum(forma_vis, id_vis),
        },
    )

    if res["hay_mismatch"]:
        favorito = res["favorito"]
        nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
        enriquecer_y_enviar_alerta(
            deporte, ev["torneo"], nom_loc, nom_vis, ev["horario"], estado, res["alertas"],
            motor_mismatches.sugerir_mercado(deporte, favorito, nom_fav),
            favorito, res["confianza"],
        )
        st["alertas"] += 1
    elif res["puntaje"] > 0:
        U.log(f"   descartado {nom_loc} vs {nom_vis}: {res['motivo_descarte']}")

    registro.marcar(clave)
    return True


# ---------------------------------------------------------------------------
# BARRIDO
# ---------------------------------------------------------------------------
def _recolectar_eventos(resumen):
    """Lista única de eventos de todas las fuentes (sin duplicados entre fuentes)."""
    por_clave = {}
    for modulo, nombre in ((fuente_espn, "espn"), (fuente_api_football, "api_sports")):
        if modulo is None:
            continue
        for deporte in DEPORTES_RADAR:
            try:
                eventos = modulo.obtener_eventos(deporte)
            except Exception as e:
                U.log(f"[{nombre}] error listando {deporte}: {type(e).__name__}: {e}")
                continue
            if not eventos:
                continue
            st = resumen.setdefault(f"{nombre}:{deporte}", _nuevo_stat())
            st["eventos"] = len(eventos)
            for ev in eventos:
                por_clave.setdefault(ev["clave"], ev)  # ESPN va primero: gana ante un duplicado
    return list(por_clave.values())


def _imprimir_resumen(resumen):
    U.log("--- Resumen del barrido ---")
    if not resumen:
        U.log("ninguna fuente devolvió partidos femeninos para las próximas 24 h")
    for etapa, st in resumen.items():
        U.log(
            f"{etapa}: {st['eventos']} eventos -> {st['femeninos']} femeninos -> "
            f"{st['analizados']} analizados -> {st['alertas']} alertas "
            f"(ya vistos {st['ya_vistos']}, sin datos {st['sin_datos']}, no vigentes {st['no_vigentes']}, "
            f"lejanos {st['lejanos']}, errores {st['errores']})"
        )
    for fuente, codigos in U.ESTADISTICAS.items():
        U.log(f"fuente {fuente}: respuestas {dict(codigos)}")


def _avisar_si_esta_ciego(resumen):
    """Avisa por Telegram (máx. 1 vez cada 6 h) si ninguna fuente respondió bien en este barrido."""
    global _ultimo_aviso_ciego
    hubo_200 = any(codigos.get(200, 0) for codigos in U.ESTADISTICAS.values())
    hay_pedidos = any(sum(c.values()) for c in U.ESTADISTICAS.values())
    if (hubo_200 and resumen) or not hay_pedidos:
        return
    if time.time() - _ultimo_aviso_ciego < 6 * 3600:
        return
    _ultimo_aviso_ciego = time.time()
    detalle = ", ".join(f"{f}: {dict(c)}" for f, c in U.ESTADISTICAS.items())
    enviar_telegram(
        "⚠️ <b>El radar no pudo obtener datos en este barrido.</b>\n"
        f"Respuestas por fuente: {html.escape(detalle[:600])}\n"
        "Revisá los logs: puede ser bloqueo de IP, clave inválida o cuota agotada."
    )


def ejecutar_barrido_radar():
    U.reiniciar_estadisticas()
    U.log("=== Barrido Radar Femenino 360° ===")
    if motor_mismatches is None:
        U.log("motor_mismatches no está disponible: se omite el barrido")
        return

    registro.podar()
    resumen = {}
    ahora_ts = time.time()
    analizados = 0

    eventos = _recolectar_eventos(resumen)
    eventos.sort(key=lambda e: e.get("startTimestamp", 0))  # primero los que empiezan antes

    for ev in eventos:
        if analizados >= MAX_ANALISIS_POR_CICLO:
            U.log(f"Tope de {MAX_ANALISIS_POR_CICLO} análisis por ciclo: el resto sigue en el próximo barrido")
            break
        st = resumen.setdefault(f"{ev['fuente']}:{ev['deporte']}", _nuevo_stat())
        try:
            if _procesar_evento(ev, st, ahora_ts):
                analizados += 1
        except Exception as e:
            st["errores"] += 1
            U.log(f"Error en evento {ev.get('id')}: {type(e).__name__}: {e}")
            registro.marcar(ev.get("clave", ev.get("id", "?")))
        registro.guardar()

    registro.guardar()
    _imprimir_resumen(resumen)
    _avisar_si_esta_ciego(resumen)


if __name__ == "__main__":
    U.log("Radar Cuantitativo Multideporte Femenino 360° desplegado...")
    U.log(f"Persistencia: {U.modo_persistencia()}")
    fuentes = []
    if fuente_espn:
        fuentes.append("ESPN")
    if fuente_api_football and fuente_api_football.API_KEY:
        fuentes.append("API-Sports")
    U.log(f"Fuentes activas: {', '.join(fuentes) or 'NINGUNA'}")

    aviso = (
        "🤖 <b>Radar Femenino 360° activo.</b>\n"
        f"Fuentes: {html.escape(', '.join(fuentes) or 'ninguna')}\n"
        f"Persistencia: {html.escape(U.modo_persistencia())}"
    )
    if not U.persistencia_es_duradera():
        aviso += (
            "\n⚠️ Sin disco persistente: tras un deploy puede repetir alertas de partidos ya "
            "avisados (solo los que sigan vigentes). Configurá UPSTASH_REDIS_REST_URL/TOKEN o DATA_DIR."
        )
    enviar_telegram(aviso)

    while True:
        try:
            ejecutar_barrido_radar()
        except Exception as e:
            U.log(f"Error en ciclo de barrido: {type(e).__name__}: {e}")
        time.sleep(INTERVALO_REVISION)
