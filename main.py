"""
main.py
Radar Mismatch Multideporte Femenino 360° — Resiliente
- Servidor web fantasma prioritario (garantiza estado LIVE en Render).
- Importación segura de módulos para evitar cierres prematuros.
- Solo partidos vigentes (no empezados / en juego), hora en ARG real, try/except por evento,
  persistencia de partidos ya vistos y resumen por etapa en cada barrido.
- Proxy opcional para Sofascore (variable SOFASCORE_PROXY) y corte rápido si la IP está bloqueada.
"""

import html
import os
import re
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import requests


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
    try:
        servidor = HTTPServer(("0.0.0.0", puerto), SimpleHandler)
        servidor.serve_forever()
    except OSError as e:  # puerto ocupado (p. ej. corriendo en casa): el radar sigue igual
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
    """
    Envía en HTML (con los campos dinámicos escapados). Si Telegram rechaza el formato
    (400) reintenta en texto plano. Loguea cualquier fallo y devuelve True si llegó a algún chat.
    """
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
    import fuentes_alternativas
except Exception as e:
    fuentes_alternativas = None
    U.log(f"Aviso: fuentes_alternativas no disponible: {e}")

try:
    import tracker_cuotas_smart
except Exception as e:
    tracker_cuotas_smart = None
    U.log(f"Aviso: tracker_cuotas_smart no disponible: {e}")

try:
    import conector_besoccer
except Exception as e:
    conector_besoccer = None
    U.log(f"Aviso: conector_besoccer no disponible: {e}")

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
MAX_ANALISIS_POR_CICLO = int(os.environ.get("MAX_ANALISIS_POR_CICLO", "80"))
HORAS_VENTANA_PREVIA = 24
FUENTES_CON_AVISO = {"sofascore"}

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
    "cricket": "Cricket",
}

KEYWORDS_FEMENINAS = [
    "women", "womens", "wom", "fem", "femenil", "femenino", "femenina", "femení", "feminin",
    "féminin", "feminine", "femminile", "donne", "mulheres", "damas", "feminina", "ladies",
    "dames", "frauen", "damen", "kobiety", "zeny", "wta", "itf women", "wnba", "wsl", "nwsl",
    "liga f", "serie a fem", "frauen-bundesliga", "sdhl", "pwhl",
]

# Sin User-Agent a propósito: curl_cffi (impersonate chrome124) pone el de Chrome de escritorio
# y coherente con su huella TLS. Si caés al fallback "requests" se usa el UA por defecto de utilidades.
HEADERS_SOFASCORE = {
    "Accept": "*/*",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
}

# Proxy opcional (http://usuario:clave@host:puerto). Se define en las variables de entorno.
PROXIES_SOFASCORE = U.proxies_desde_env("SOFASCORE_PROXY")

registro = U.RegistroVistos(ARCHIVO_NOTIFICADOS)
_cache_tablas = U.CacheTTL(6 * 3600)
_cache_historial = U.CacheTTL(3 * 3600)
_ultimo_aviso_fuente = {}


# ---------------------------------------------------------------------------
# FILTRO FEMENINO
# ---------------------------------------------------------------------------
_RE_FEMENINO_FUERTE = re.compile(r"\b(wta|itf women|billie jean king)\b")
_RE_MASCULINO = re.compile(
    r"\b(atp|challenger|davis cup|men|mens|men's|masculino|masculin|herren|hommes|maschile)\b"
)
_RE_KEYWORDS_FEM = re.compile(r"\b(" + "|".join(re.escape(k) for k in KEYWORDS_FEMENINAS) + r")\b")
_RE_PATRONES_FEM = re.compile(r"\((w|f)\)|\bw\b|\bw\s?\d{2,3}\b")


def es_deporte_femenino_valido(torneo, local, visita):
    texto = f"{torneo} {local} {visita}".lower()
    if _RE_FEMENINO_FUERTE.search(texto):
        return True
    if _RE_MASCULINO.search(texto):
        return False
    if _RE_KEYWORDS_FEM.search(texto):
        return True
    return bool(_RE_PATRONES_FEM.search(texto))


# ---------------------------------------------------------------------------
# SOFASCORE
# ---------------------------------------------------------------------------
def _sofa_get(url):
    time.sleep(0.4)
    return U.get_json(url, "sofascore", headers=HEADERS_SOFASCORE, timeout=12, proxies=PROXIES_SOFASCORE)


def obtener_partidos_sofascore(slug):
    """Eventos de hoy y mañana (hora ARG), sin duplicados."""
    eventos = {}
    for dias in (0, 1):
        data = _sofa_get(
            f"https://api.sofascore.com/api/v1/sport/{slug}/scheduled-events/{U.fecha_arg(dias)}"
        )
        for ev in (data or {}).get("events", []) if isinstance(data, dict) else []:
            if ev.get("id"):
                eventos[ev["id"]] = ev
    return list(eventos.values())


def obtener_tablas_torneo(tourn_id, season_id):
    """Lista de tablas (una por grupo/zona). Cada tabla: {id_equipo: datos}."""
    if not tourn_id or not season_id:
        return []
    clave = (tourn_id, season_id)
    hit, valor = _cache_tablas.get(clave)
    if hit:
        return valor

    data = _sofa_get(
        f"https://api.sofascore.com/api/v1/unique-tournament/{tourn_id}/season/{season_id}/standings/total"
    )
    if not isinstance(data, dict):
        return []

    tablas = []
    for standing in data.get("standings", []) or []:
        tabla = {}
        for f in standing.get("rows", []) or []:
            tid = (f.get("team") or {}).get("id")
            if not tid:
                continue
            tabla[tid] = {
                "posicion": f.get("position", 0),
                "puntos": f.get("points", 0),
                "victorias": f.get("wins", 0) or 0,
                "empates": f.get("draws", 0) or 0,
                "derrotas": f.get("losses", 0) or 0,
                "partidos_jugados": f.get("matches", 0) or 0,
                "dif_neta": (f.get("scoresFor", 0) or 0) - (f.get("scoresAgainst", 0) or 0),
            }
        if tabla:
            tablas.append(tabla)

    _cache_tablas.set(clave, tablas)
    return tablas


def _convertir_evento_historico(ev):
    return {
        "fecha": U.ts_a_iso_utc(ev.get("startTimestamp", 0)),
        "id_local": (ev.get("homeTeam") or {}).get("id"),
        "nom_local": (ev.get("homeTeam") or {}).get("name"),
        "id_visita": (ev.get("awayTeam") or {}).get("id"),
        "nom_visita": (ev.get("awayTeam") or {}).get("name"),
        "puntos_local": (ev.get("homeScore") or {}).get("current"),
        "puntos_visita": (ev.get("awayScore") or {}).get("current"),
    }


def obtener_ultimos_partidos(team_id):
    """Últimos partidos TERMINADOS del equipo (cache 3 h)."""
    if not team_id:
        return []
    hit, valor = _cache_historial.get(team_id)
    if hit:
        return valor

    time.sleep(0.7)
    data = _sofa_get(f"https://api.sofascore.com/api/v1/team/{team_id}/events/last/0")
    if not isinstance(data, dict):
        return []

    eventos = [e for e in data.get("events", []) or [] if (e.get("status") or {}).get("type") == "finished"]
    eventos.sort(key=lambda e: e.get("startTimestamp", 0), reverse=True)
    partidos = [_convertir_evento_historico(e) for e in eventos[:8]]
    _cache_historial.set(team_id, partidos)
    return partidos


def obtener_h2h_sofascore(ev):
    """Cruces directos (terminados). Prueba con customId y, si falla, con el id numérico."""
    time.sleep(0.5)
    for ident in (ev.get("customId"), ev.get("id")):
        if not ident:
            continue
        data = _sofa_get(f"https://api.sofascore.com/api/v1/event/{ident}/h2h/events")
        if isinstance(data, dict):
            eventos = [e for e in data.get("events", []) or [] if (e.get("status") or {}).get("type") == "finished"]
            return [_convertir_evento_historico(e) for e in eventos[:8]]
    return []


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
# BARRIDO
# ---------------------------------------------------------------------------
def _nuevo_stat():
    return {"eventos": 0, "femeninos": 0, "ya_vistos": 0, "no_vigentes": 0, "lejanos": 0,
            "analizados": 0, "alertas": 0, "errores": 0}


def _barrido_itf(resumen):
    st = resumen.setdefault("itf", _nuevo_stat())
    partidos = fuentes_alternativas.obtener_mismatches_itf()
    st["eventos"] = len(partidos)
    for m in partidos:
        if registro.visto(m["id"]):
            st["ya_vistos"] += 1
            continue
        st["analizados"] += 1
        enriquecer_y_enviar_alerta(
            deporte="Tennis", torneo=m["torneo"], nom_loc=m["local"], nom_vis=m["visita"],
            hora_txt=m["horario"], estado="🟢 <b>PRE</b>", alertas_base=[m["detalle"]],
            pick_base=motor_mismatches.sugerir_mercado(
                "Tennis", m["favorito"], m["local"] if m["favorito"] == motor_mismatches.LOCAL else m["visita"]),
            favorito=m["favorito"], confianza="Media",
        )
        registro.marcar(m["id"])
        registro.guardar()
        st["alertas"] += 1


def _barrido_besoccer(resumen):
    st = resumen.setdefault("besoccer", _nuevo_stat())
    partidos = conector_besoccer.obtener_partidos_ascenso_besoccer()
    st["eventos"] = st["femeninos"] = len(partidos)
    for p in partidos:
        if registro.visto(p["id"]):
            st["ya_vistos"] += 1
            continue
        if not p.get("tiene_alineaciones"):
            continue

        st["analizados"] += 1
        rot = conector_besoccer.verificar_rotacion_plantel(p["id"].replace("besoccer_", ""))
        if not rot.get("alineaciones_disponibles"):
            continue

        if rot.get("alerta_rotacion"):
            rota = rot["lado_rota"]
            favorito = motor_mismatches._otro(rota)
            nom_rota = p["local"] if rota == motor_mismatches.LOCAL else p["visita"]
            nom_fav = p["local"] if favorito == motor_mismatches.LOCAL else p["visita"]
            n_altos = rot["dorsales_reserva_local"] if rota == motor_mismatches.LOCAL else rot["dorsales_reserva_visita"]
            enriquecer_y_enviar_alerta(
                deporte="Soccer", torneo=p["torneo"], nom_loc=p["local"], nom_vis=p["visita"],
                hora_txt=p["horario"], estado="🟢 <b>PRE</b>",
                alertas_base=[f"Rotación masiva en {nom_rota}: {n_altos} titulares con dorsal de reserva/juvenil"],
                pick_base=motor_mismatches.sugerir_mercado("Soccer", favorito, nom_fav),
                favorito=favorito, confianza="Media",
            )
            st["alertas"] += 1
        registro.marcar(p["id"])
        registro.guardar()


def _procesar_evento_sofascore(ev, deporte_nombre, ahora_ts, st):
    event_id = ev["id"]
    id_unico = f"sofa_{event_id}"

    torneo_obj = ev.get("tournament") or {}
    torneo_nom = torneo_obj.get("name", "Torneo")
    cat_nom = (torneo_obj.get("category") or {}).get("name", "")
    competicion = f"{torneo_nom} ({cat_nom})" if cat_nom else torneo_nom

    local_obj = ev.get("homeTeam") or {}
    visita_obj = ev.get("awayTeam") or {}
    nom_loc = local_obj.get("name", "Local")
    nom_vis = visita_obj.get("name", "Visitante")
    id_loc, id_vis = local_obj.get("id"), visita_obj.get("id")

    if not es_deporte_femenino_valido(competicion, nom_loc, nom_vis):
        return False
    st["femeninos"] += 1

    if registro.visto(id_unico):
        st["ya_vistos"] += 1
        return False

    tipo_estado = (ev.get("status") or {}).get("type")
    if tipo_estado not in ("notstarted", "inprogress"):
        st["no_vigentes"] += 1
        return False

    start_ts = ev.get("startTimestamp", 0)
    if tipo_estado == "notstarted" and start_ts > ahora_ts + HORAS_VENTANA_PREVIA * 3600:
        st["lejanos"] += 1
        return False

    hora_txt = U.formatear_hora_arg(start_ts)
    estado = "🔴 <b>EN VIVO (LIVE)</b>" if tipo_estado == "inprogress" else "🟢 <b>PRE</b>"
    st["analizados"] += 1

    # Tenis
    if deporte_nombre == "Tennis":
        hay, detalle, favorito = motor_mismatches.evaluar_mismatch_tenis(
            nom_loc, nom_vis, local_obj.get("ranking"), visita_obj.get("ranking")
        )
        if hay:
            nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
            enriquecer_y_enviar_alerta(
                deporte="Tennis", torneo=competicion, nom_loc=nom_loc, nom_vis=nom_vis,
                hora_txt=hora_txt, estado=estado, alertas_base=[detalle],
                pick_base=motor_mismatches.sugerir_mercado("Tennis", favorito, nom_fav),
                favorito=favorito, confianza="Media", superficie=ev.get("groundType"),
            )
            st["alertas"] += 1
        registro.marcar(id_unico)
        return True

    # Deportes de equipo
    tourn_id = (torneo_obj.get("uniqueTournament") or {}).get("id")
    season_id = (ev.get("season") or {}).get("id")

    tablas = obtener_tablas_torneo(tourn_id, season_id)
    tabla = next((t for t in tablas if id_loc in t and id_vis in t), None)
    tabla_eval = motor_mismatches.evaluar_tabla_posiciones(tabla, id_loc, id_vis)

    hist_loc = obtener_ultimos_partidos(id_loc)
    hist_vis = obtener_ultimos_partidos(id_vis)
    perf_loc = motor_mismatches.evaluar_rendimiento_reciente(hist_loc, id_loc)
    perf_vis = motor_mismatches.evaluar_rendimiento_reciente(hist_vis, id_vis)
    triangs = motor_mismatches.triangular_rivales(hist_loc, id_loc, hist_vis, id_vis)
    h2h_eval = motor_mismatches.analizar_h2h_reciente(obtener_h2h_sofascore(ev), id_loc, id_vis)

    res = motor_mismatches.evaluar_mismatch(
        deporte=deporte_nombre, perf_local=perf_loc, perf_visita=perf_vis,
        triangulaciones=triangs, h2h=h2h_eval, tabla_local_visita=tabla_eval,
    )

    if res["hay_mismatch"]:
        favorito = res["favorito"]
        nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
        enriquecer_y_enviar_alerta(
            deporte=deporte_nombre, torneo=competicion, nom_loc=nom_loc, nom_vis=nom_vis,
            hora_txt=hora_txt, estado=estado, alertas_base=res["alertas"],
            pick_base=motor_mismatches.sugerir_mercado(deporte_nombre, favorito, nom_fav),
            favorito=favorito, confianza=res["confianza"],
        )
        st["alertas"] += 1
    elif res["puntaje"] > 0:
        U.log(f"   descartado {nom_loc} vs {nom_vis}: {res['motivo_descarte']}")

    registro.marcar(id_unico)
    return True


def _barrido_sofascore(resumen):
    ahora_ts = time.time()
    analizados_total = 0

    for slug, deporte_nombre in DEPORTES_RADAR.items():
        # Corte rápido: si ya hubo 3+ pedidos y ninguno fue 200, la IP está bloqueada.
        # Seguir pegándole 25 veces más solo empeora la reputación de la IP.
        if U.hay_bloqueo("sofascore"):
            U.log("[sofascore] bloqueado (sin ninguna respuesta 200): corto el barrido de Sofascore")
            break

        st = resumen.setdefault(slug, _nuevo_stat())
        eventos = obtener_partidos_sofascore(slug)
        st["eventos"] = len(eventos)

        for ev in eventos:
            if analizados_total >= MAX_ANALISIS_POR_CICLO:
                break
            try:
                if _procesar_evento_sofascore(ev, deporte_nombre, ahora_ts, st):
                    analizados_total += 1
            except Exception as e:
                st["errores"] += 1
                U.log(f"Error en evento {ev.get('id')} ({deporte_nombre}): {type(e).__name__}: {e}")
                U.log(traceback.format_exc().strip().splitlines()[-3])
                registro.marcar(f"sofa_{ev.get('id')}")

            registro.guardar()

    if analizados_total >= MAX_ANALISIS_POR_CICLO:
        U.log(f"Tope de {MAX_ANALISIS_POR_CICLO} análisis por ciclo alcanzado; el resto sigue en el próximo barrido")


def _imprimir_resumen(resumen):
    U.log("--- Resumen del barrido ---")
    for etapa, st in resumen.items():
        U.log(
            f"{etapa}: {st['eventos']} eventos -> {st['femeninos']} femeninos -> "
            f"{st['analizados']} analizados -> {st['alertas']} alertas "
            f"(ya vistos {st['ya_vistos']}, terminados/no vigentes {st['no_vigentes']}, "
            f"lejanos {st['lejanos']}, errores {st['errores']})"
        )
    for fuente, codigos in U.ESTADISTICAS.items():
        U.log(f"fuente {fuente}: respuestas {dict(codigos)}")


def _avisar_fuentes_caidas():
    for fuente in FUENTES_CON_AVISO:
        if U.hay_bloqueo(fuente):
            codigos = U.ESTADISTICAS.get(fuente, {})
            ultimo = _ultimo_aviso_fuente.get(fuente, 0)
            if time.time() - ultimo > 6 * 3600:
                _ultimo_aviso_fuente[fuente] = time.time()
                usa_proxy = "con proxy configurado" if PROXIES_SOFASCORE else "sin proxy"
                enviar_telegram(
                    f"⚠️ <b>Fuente caída:</b> {html.escape(fuente)} no devolvió ninguna respuesta válida "
                    f"en este barrido ({html.escape(str(dict(codigos)))}, {usa_proxy}). "
                    "Si ves 403, la IP del servidor está bloqueada: corré el radar desde una IP "
                    "residencial (PC/celu en casa) o definí la variable SOFASCORE_PROXY."
                )


def ejecutar_barrido_radar():
    U.reiniciar_estadisticas()
    U.log("Ejecutando barrido Radar Femenino 360°...")
    if motor_mismatches is None:
        U.log("motor_mismatches no está disponible: se omite el barrido")
        return

    registro.podar()
    resumen = {}

    etapas = []
    if fuentes_alternativas:
        etapas.append(("itf", _barrido_itf))
    if conector_besoccer:
        etapas.append(("besoccer", _barrido_besoccer))
    etapas.append(("sofascore", _barrido_sofascore))

    for nombre, funcion in etapas:
        try:
            funcion(resumen)
        except Exception as e:
            U.log(f"Error en etapa {nombre}: {type(e).__name__}: {e}")

    registro.guardar()
    _imprimir_resumen(resumen)
    _avisar_fuentes_caidas()


if __name__ == "__main__":
    U.log("Radar Cuantitativo Multideporte Femenino 360° desplegado...")
    U.log(f"Persistencia: {U.modo_persistencia()}")
    U.log(f"Proxy Sofascore: {'sí' if PROXIES_SOFASCORE else 'no'}")

    aviso = "🤖 <b>Radar Femenino 360° activo.</b>\n" + f"Persistencia: {html.escape(U.modo_persistencia())}"
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
