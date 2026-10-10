"""
main.py
Radar Mismatch Multideporte Femenino 360° — Multi-fuente FINAL
- Servidor web fantasma.
- Fuentes: API-Football (principal) + Highlightly + OddsPapi + ESPN + FlashScore (opcional).
- Motor de 9 señales.
"""

import html
import os
import re
import time
import traceback
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import requests


class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Radar Mismatches Femenino 360 OK (multi-fuente)")
    def do_HEAD(self):
        self.send_response(200); self.end_headers()
    def log_message(self, format, *args): pass


def iniciar_servidor_web():
    try:
        HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), SimpleHandler).serve_forever()
    except OSError as e:
        print(f"Servidor web no iniciado ({e})", flush=True)


Thread(target=iniciar_servidor_web, daemon=True).start()

import utilidades as U

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
CHAT_ID_GRUPO = os.environ.get("CHAT_ID_GRUPO")


def _sin_html(texto):
    return html.unescape(re.sub(r"<[^>]+>", "", texto))


def enviar_telegram(mensaje_html):
    if not TELEGRAM_TOKEN:
        return False
    destinos = [c for c in (CHAT_ID, CHAT_ID_GRUPO) if c]
    if not destinos:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    mensaje_html = mensaje_html[:4000]
    llego = False
    for destino in destinos:
        for modo in ("HTML", None):
            payload = {"chat_id": destino,
                       "text": mensaje_html if modo else _sin_html(mensaje_html),
                       "disable_web_page_preview": True}
            if modo: payload["parse_mode"] = modo
            try:
                r = requests.post(url, json=payload, timeout=10)
            except requests.RequestException:
                break
            if r.status_code == 200:
                llego = True; break
            if r.status_code == 429:
                try: time.sleep(min(int(r.json().get("parameters", {}).get("retry_after", 3)), 30))
                except Exception: time.sleep(3)
                continue
            if r.status_code != 400: break
    return llego


# --- Imports defensivos ---
try: import motor_mismatches
except Exception as e:
    motor_mismatches = None
    U.log(f"ERROR motor_mismatches: {e}")

try: import fuente_api_football
except Exception as e:
    fuente_api_football = None
    U.log(f"Aviso fuente_api_football: {e}")

try: import fuente_highlightly
except Exception as e:
    fuente_highlightly = None
    U.log(f"Aviso fuente_highlightly: {e}")

try: import fuente_oddspapi
except Exception as e:
    fuente_oddspapi = None
    U.log(f"Aviso fuente_oddspapi: {e}")

try: import fuente_espn
except Exception as e:
    fuente_espn = None
    U.log(f"Aviso fuente_espn: {e}")

try: import tracker_cuotas_smart
except Exception as e:
    tracker_cuotas_smart = None

try: import metricas_profundas
except Exception as e:
    metricas_profundas = None

try: import monitor_noticias
except Exception as e:
    monitor_noticias = None


INTERVALO_REVISION = int(os.environ.get("INTERVALO_REVISION", "1800"))
ARCHIVO_NOTIFICADOS = "notificados.json"
MAX_ANALISIS_POR_CICLO = int(os.environ.get("MAX_ANALISIS_POR_CICLO", "100"))
HORAS_VENTANA_PREVIA = 24

DEPORTES_RADAR = ["Soccer", "Basketball", "Tennis", "Ice Hockey", "Handball", "Volleyball"]

registro = U.RegistroVistos(ARCHIVO_NOTIFICADOS)


# ---------------------------------------------------------------------------
# FILTRO FEMENINO ESTRICTO
# ---------------------------------------------------------------------------
_RE_MASCULINO = re.compile(
    r"\b(atp|challenger|davis cup|men|mens|men's|masculino|masculin|herren|hommes|maschile|"
    r"nba|nfl|nhl|mlb|mls|j1 league|j2 league|j3 league|bundesliga|serie a|premier league|"
    r"la liga|ligue 1|eredivisie|liga mx|superliga|allsvenskan|eliteserien|superligaen)\b"
)
_KEYWORDS_FEM = re.compile(
    r"\b(women|womens|women's|woman|fem|femenil|femenino|femenina|feminin|feminine|femminile|"
    r"dames|damen|frauen|ladies|wta|wnba|nwsl|wsl|kvinde|kvindeligaen|damallsvenskan|toppserien|"
    r"we league|liga f|serie a fem|division 1 fem|frauen-bundesliga|eredivisie vrouwen|"
    r"campeonato nacional feminino|primera division femenina|primera división femenina|"
    r"brasileirao feminino|brasileirão feminino|a-league women|liga mx femenil|ncaa women|"
    r"shebelieves|concacaf w|uefa women|fifa women|w gold cup|w champions)\b"
)


def es_deporte_femenino_valido(torneo, local, visita):
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
    try: return funcion(*args, **kwargs)
    except Exception as e:
        U.log(f"Aviso {getattr(funcion, '__name__', '?')}: {type(e).__name__}: {e}")
        return defecto


def enriquecer_y_enviar_alerta(deporte, torneo, nom_loc, nom_vis, hora_txt, estado,
                               alertas_base, pick_base, favorito, confianza="Media"):
    nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
    detalles = list(alertas_base)

    if monitor_noticias:
        nov = _seguro(monitor_noticias.buscar_novedades_partido, nom_loc, nom_vis, defecto={}) or {}
        if nov.get("alerta_novedad"):
            etiqueta = "⚠️ Último momento" if nov.get("equipo") == favorito else "Último momento (rival)"
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
          f"tg: {'ok' if enviado else 'NO'}")


# ---------------------------------------------------------------------------
# BARRIDO
# ---------------------------------------------------------------------------
def _nuevo_stat():
    return {"eventos": 0, "femeninos": 0, "ya_vistos": 0, "no_vigentes": 0, "lejanos": 0,
            "analizados": 0, "alertas": 0, "errores": 0}


def _procesar_evento(evento, st):
    """Procesa un evento normalizado con el motor de 9 señales."""
    id_unico = evento["id"]
    if registro.visto(id_unico):
        st["ya_vistos"] += 1; return False

    tipo_estado = evento.get("tipo_estado", "pre")
    if tipo_estado != "pre":
        st["no_vigentes"] += 1; return False

    ahora_ts = time.time()
    if evento.get("startTimestamp", 0) > ahora_ts + HORAS_VENTANA_PREVIA * 3600:
        st["lejanos"] += 1; return False

    nom_loc = evento["local"]["nombre"]
    nom_vis = evento["visita"]["nombre"]
    torneo = evento["torneo"]
    deporte = evento["deporte"]

    if not es_deporte_femenino_valido(torneo, nom_loc, nom_vis):
        return False
    st["femeninos"] += 1
    st["analizados"] += 1

    hora_txt = evento["horario"]
    estado = "🟢 <b>PRE</b>"

    # Tenis (señal 5)
    if deporte == "Tennis":
        hay, detalle, favorito, pts = motor_mismatches.evaluar_mismatch_tenis(
            nom_loc, nom_vis, evento["local"].get("ranking"), evento["visita"].get("ranking")
        )
        if hay and pts >= 2:
            nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
            confianza = "Alta" if pts >= 3 else "Media"
            enriquecer_y_enviar_alerta(
                deporte="Tennis", torneo=torneo, nom_loc=nom_loc, nom_vis=nom_vis,
                hora_txt=hora_txt, estado=estado, alertas_base=[detalle],
                pick_base=motor_mismatches.sugerir_mercado("Tennis", favorito, nom_fav),
                favorito=favorito, confianza=confianza,
            )
            st["alertas"] += 1
        registro.marcar(id_unico)
        return True

    # Deportes de equipo: motor de 9 señales
    id_loc = evento["local"].get("id")
    id_vis = evento["visita"].get("id")

    # Obtener datos profundos (H2H, forma, tabla)
    h2h_data = []
    tabla_data = None
    forma_loc = []
    forma_vis = []

    if fuente_api_football and id_loc and id_vis:
        h2h_raw = _seguro(fuente_api_football.obtener_h2h, id_loc, id_vis, deporte, defecto=[]) or []
        # Convertir H2H al formato interno
        h2h_data = []
        for p in h2h_raw:
            try:
                fix = p.get("fixture") or {}
                teams = p.get("teams") or {}
                goals = p.get("goals") or {}
                fecha = fix.get("date", "")
                h2h_data.append({
                    "fecha": fecha,
                    "id_local": (teams.get("home") or {}).get("id"),
                    "id_visita": (teams.get("away") or {}).get("id"),
                    "puntos_local": goals.get("home"),
                    "puntos_visita": goals.get("away"),
                })
            except Exception:
                continue

        # Forma reciente
        forma_loc_raw = _seguro(fuente_api_football.obtener_forma_reciente, id_loc, deporte, 6, defecto=[]) or []
        forma_vis_raw = _seguro(fuente_api_football.obtener_forma_reciente, id_vis, deporte, 6, defecto=[]) or []
        for lista_raw, lista_dest in ((forma_loc_raw, forma_loc), (forma_vis_raw, forma_vis)):
            for p in lista_raw:
                try:
                    fix = p.get("fixture") or {}
                    teams = p.get("teams") or {}
                    goals = p.get("goals") or {}
                    lista_dest.append({
                        "fecha": fix.get("date", ""),
                        "id_local": (teams.get("home") or {}).get("id"),
                        "id_visita": (teams.get("away") or {}).get("id"),
                        "nom_local": (teams.get("home") or {}).get("name"),
                        "nom_visita": (teams.get("away") or {}).get("name"),
                        "puntos_local": goals.get("home"),
                        "puntos_visita": goals.get("away"),
                    })
                except Exception:
                    continue

    # Si no hay datos de API-Football, usar Highlightly como fallback
    if not h2h_data and fuente_highlightly:
        h2h_data = _seguro(fuente_highlightly.obtener_h2h, id_loc, id_vis, deporte, defecto=[]) or []

    perf_loc = motor_mismatches.evaluar_rendimiento_reciente(forma_loc, id_loc)
    perf_vis = motor_mismatches.evaluar_rendimiento_reciente(forma_vis, id_vis)
    triangs = motor_mismatches.triangular_rivales(forma_loc, id_loc, forma_vis, id_vis)
    h2h_ext = motor_mismatches.analizar_h2h_extendido(h2h_data, id_loc, id_vis)

    # Señales extra
    descanso = motor_mismatches.evaluar_descanso(forma_loc, id_loc, forma_vis, id_vis)
    racha_loc = motor_mismatches.evaluar_momentum(forma_loc, id_loc)
    racha_vis = motor_mismatches.evaluar_momentum(forma_vis, id_vis)

    tabla_eval = motor_mismatches.evaluar_tabla_posiciones(tabla_data, id_loc, id_vis)

    res = motor_mismatches.evaluar_mismatch(
        deporte=deporte, perf_local=perf_loc, perf_visita=perf_vis,
        triangulaciones=triangs, h2h=h2h_ext, tabla_local_visita=tabla_eval,
        datos_extra={"descanso": descanso, "racha_local": racha_loc, "racha_visita": racha_vis},
    )

    if res["hay_mismatch"]:
        favorito = res["favorito"]
        nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
        enriquecer_y_enviar_alerta(
            deporte=deporte, torneo=torneo, nom_loc=nom_loc, nom_vis=nom_vis,
            hora_txt=hora_txt, estado=estado, alertas_base=res["alertas"],
            pick_base=motor_mismatches.sugerir_mercado(deporte, favorito, nom_fav),
            favorito=favorito, confianza=res["confianza"],
        )
        st["alertas"] += 1
    elif res["puntaje"] > 0:
        U.log(f"   descartado {nom_loc} vs {nom_vis}: {res['motivo_descarte']}")

    registro.marcar(id_unico)
    return True


def _barrido_api_football(resumen):
    if fuente_api_football is None:
        return
    analizados_total = 0
    for deporte in DEPORTES_RADAR:
        st = resumen.setdefault(f"apifootball_{deporte}", _nuevo_stat())
        try:
            eventos = fuente_api_football.obtener_eventos(deporte)
        except Exception as e:
            U.log(f"[apifootball] Error {deporte}: {type(e).__name__}: {e}")
            continue
        st["eventos"] = len(eventos)
        for ev in eventos:
            if analizados_total >= MAX_ANALISIS_POR_CICLO: break
            try:
                if _procesar_evento(ev, st): analizados_total += 1
            except Exception as e:
                st["errores"] += 1
                U.log(f"Error evento {ev.get('id')}: {type(e).__name__}: {e}")
                registro.marcar(ev.get("id"))
            registro.guardar()


def _imprimir_resumen(resumen):
    U.log("--- Resumen del barrido ---")
    for etapa, st in resumen.items():
        U.log(
            f"{etapa}: {st['eventos']} ev -> {st['femeninos']} fem -> "
            f"{st['analizados']} anal -> {st['alertas']} alertas "
            f"(vistos {st['ya_vistos']}, no vig {st['no_vigentes']}, "
            f"lejanos {st['lejanos']}, err {st['errores']})"
        )
    for fuente, codigos in U.ESTADISTICAS.items():
        U.log(f"fuente {fuente}: {dict(codigos)}")


def ejecutar_barrido_radar():
    U.reiniciar_estadisticas()
    U.log("=== Barrido Radar Femenino 360° (multi-fuente) ===")
    if motor_mismatches is None:
        U.log("motor_mismatches no disponible")
        return
    registro.podar()
    resumen = {}
    try:
        _barrido_api_football(resumen)
    except Exception as e:
        U.log(f"Error en barrido: {type(e).__name__}: {e}")
    registro.guardar()
    _imprimir_resumen(resumen)


if __name__ == "__main__":
    U.log("Radar Femenino 360° (multi-fuente FINAL) desplegado...")
    U.log(f"Persistencia: {U.modo_persistencia()}")

    aviso = ("🤖 <b>Radar Femenino 360° FINAL activo.</b>\n"
             f"Persistencia: {html.escape(U.modo_persistencia())}\n"
             f"Fuentes: API-Football + Highlightly + OddsPapi + ESPN")
    enviar_telegram(aviso)

    while True:
        try:
            ejecutar_barrido_radar()
        except Exception as e:
            U.log(f"Error ciclo: {type(e).__name__}: {e}")
        time.sleep(INTERVALO_REVISION)