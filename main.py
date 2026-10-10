"""Radar de asimetrías deportivas exclusivamente femeninas.

El sistema no consulta, almacena ni muestra cuotas, bookmakers ni probabilidades
implícitas. Usa resultados recientes, rankings disponibles, H2H, tablas y calendario.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

import requests

import utilidades as U


# ---------------------------------------------------------------------------
# HTTP de salud para Render. Un ping entrante no ejecuta ni fuerza un barrido.
# ---------------------------------------------------------------------------
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        payload = {
            "service": "radar-femenino",
            "status": "ok",
            "persistence": U.modo_persistencia(),
            "sports_scope": "women_only",
            "market_data": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):
        return


def iniciar_servidor_web():
    try:
        puerto = int(os.environ.get("PORT", "10000"))
        servidor = ThreadingHTTPServer(("0.0.0.0", puerto), SimpleHandler)
        servidor.daemon_threads = True
        U.log(f"[health] servidor HTTP escuchando en puerto {puerto}")
        servidor.serve_forever(poll_interval=0.5)
    except OSError as exc:
        U.log(f"[health] no se pudo iniciar el endpoint HTTP: {type(exc).__name__}: {exc}")


Thread(target=iniciar_servidor_web, daemon=True, name="health-server").start()


# ---------------------------------------------------------------------------
# Configuración e importación defensiva de fuentes
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
CHAT_ID_GRUPO = os.environ.get("CHAT_ID_GRUPO", "").strip()
INTERVALO_REVISION = max(60, int(os.environ.get("INTERVALO_REVISION", "900")))
MAX_ANALISIS_POR_CICLO = max(1, int(os.environ.get("MAX_ANALISIS_POR_CICLO", "100")))
HORAS_VENTANA_PREVIA = max(1, int(os.environ.get("HORAS_VENTANA_PREVIA", "24")))
ESPN_ACTIVO = os.environ.get("ESPN_ACTIVO", "1").strip().lower() not in {"0", "false", "no", "off"}
ARCHIVO_ALERTADOS = "alertas_enviadas.json"
DEPORTES_RADAR = ["Soccer", "Basketball", "Tennis", "Ice Hockey", "Handball", "Volleyball", "Rugby"]


def _importar(nombre: str, critico: bool = False):
    try:
        return __import__(nombre)
    except Exception as exc:
        nivel = "ERROR" if critico else "Aviso"
        U.log(f"[{nivel}] no se pudo importar {nombre}: {type(exc).__name__}: {exc}")
        return None


motor_mismatches = _importar("motor_mismatches", critico=True)
fuente_espn = _importar("fuente_espn")
fuente_thesportsdb = _importar("fuente_thesportsdb")
fuente_api_football = _importar("fuente_api_football")
fuente_highlightly = _importar("fuente_highlightly")
fuente_oddspapi = _importar("fuente_oddspapi")
fuente_openligadb = _importar("fuente_openligadb")

# Solo se conserva el estado de alertas efectivamente enviadas. Las detecciones
# sin evidencia suficiente o sin mismatch NO quedan bloqueadas para ciclos futuros.
registro = U.RegistroVistos(ARCHIVO_ALERTADOS, dias_retencion=3)
_ultimo_aviso_ciego = 0.0


# ---------------------------------------------------------------------------
# Telegram: salida estrictamente deportiva; nunca incluye líneas de mercado.
# ---------------------------------------------------------------------------
def _sin_html(texto: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", texto))


def enviar_telegram(mensaje_html: str) -> bool:
    if not TELEGRAM_TOKEN:
        U.log("[telegram] falta TELEGRAM_TOKEN; mensaje no enviado")
        return False
    destinos = [c for c in (CHAT_ID, CHAT_ID_GRUPO) if c]
    if not destinos:
        U.log("[telegram] faltan CHAT_ID y CHAT_ID_GRUPO; mensaje no enviado")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    mensaje_html = mensaje_html[:4000]
    entregado = False
    for destino in destinos:
        for modo in ("HTML", None):
            payload = {
                "chat_id": destino,
                "disable_web_page_preview": True,
                "text": mensaje_html if modo else _sin_html(mensaje_html),
            }
            if modo:
                payload["parse_mode"] = modo
            try:
                respuesta = requests.post(url, json=payload, timeout=12)
            except requests.RequestException as exc:
                U.log(f"[telegram] error de red ({type(exc).__name__}) para chat {destino}")
                break

            if respuesta.status_code == 200:
                entregado = True
                break
            if respuesta.status_code == 429:
                try:
                    espera = int(respuesta.json().get("parameters", {}).get("retry_after", 3))
                except (ValueError, TypeError, AttributeError):
                    espera = 3
                time.sleep(min(max(espera, 1), 30))
                continue
            U.log(f"[telegram] HTTP {respuesta.status_code} para chat {destino}; modo={modo}")
            if respuesta.status_code != 400:
                break
    return entregado


def enviar_alerta(deporte, torneo, nom_loc, nom_vis, hora_txt, alertas_base, favorito, confianza="Media"):
    """Envía una alerta basada únicamente en datos y contexto deportivo."""
    if motor_mismatches is None:
        return False
    nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
    esc = html.escape
    detalles_txt = "\n".join(f"• {esc(str(d))}" for d in list(alertas_base)[:10])
    mensaje = (
        "🚨 <b>MISMATCH DEPORTIVO FEMENINO — ASIMETRÍA</b>\n\n"
        f"🏅 <b>Deporte:</b> {esc(str(deporte))}\n"
        f"🏆 <b>Competición:</b> {esc(str(torneo))}\n"
        f"⚔️ <b>Encuentro:</b> {esc(str(nom_loc))} vs {esc(str(nom_vis))}\n"
        f"📌 <b>Favorito:</b> {esc(str(nom_fav))} (ventaja deportiva)\n"
        f"🕒 <b>Horario:</b> {esc(str(hora_txt))}\n\n"
        f"📊 <b>Evidencia:</b>\n{detalles_txt or 'Sin detalle adicional.'}\n\n"
        f"🔎 <b>Confianza del análisis:</b> {esc(str(confianza))}\n"
        "<i>Estimación basada en datos deportivos; no se usan cuotas ni mercados.</i>"
    )
    entregado = enviar_telegram(mensaje)
    U.log(
        f"[alerta] {deporte}: {nom_loc} vs {nom_vis}; ventaja={nom_fav}; "
        f"telegram={'ok' if entregado else 'no entregado'}"
    )
    return entregado


# ---------------------------------------------------------------------------
# Deduplicación de alertas, no de análisis. Un evento sin mismatch se reevalúa.
# ---------------------------------------------------------------------------
def _firma_equipo(nombre: str) -> str:
    tokens = sorted(U.tokens_significativos(str(nombre or "")))
    return "-".join(tokens) if tokens else U.normalizar(str(nombre or "")).replace(" ", "-")


def _clave_canonica_evento(ev: dict[str, Any]) -> str:
    """Firma estable entre proveedores aunque cambien ids, orden o sufijos Women/W."""
    local = (ev.get("local") or {}).get("nombre") or ""
    visita = (ev.get("visita") or {}).get("nombre") or ""
    try:
        inicio = int(ev.get("startTimestamp") or 0)
    except (TypeError, ValueError):
        inicio = 0
    if not local or not visita or not inicio:
        return str(ev.get("clave") or ev.get("id") or "").strip()
    dia_utc = datetime.fromtimestamp(inicio, timezone.utc).strftime("%Y%m%d")
    lados = sorted((_firma_equipo(local), _firma_equipo(visita)))
    return f"{lados[0]}|{lados[1]}|{dia_utc}"


def _nuevo_stat():
    return {
        "eventos": 0,
        "femeninos": 0,
        "ya_vistos": 0,
        "no_vigentes": 0,
        "lejanos": 0,
        "sin_datos": 0,
        "analizados": 0,
        "alertas": 0,
        "errores": 0,
    }


def _fecha_evento_valida(ev: dict[str, Any], ahora_ts: float, st: dict[str, int]) -> bool:
    if ev.get("tipo_estado") != "pre":
        st["no_vigentes"] += 1
        return False
    try:
        inicio = int(ev.get("startTimestamp") or 0)
    except (TypeError, ValueError):
        inicio = 0
    if not inicio:
        st["sin_datos"] += 1
        U.log(f"[calendario] se pospone evento sin timestamp fiable: {ev.get('id', '?')}")
        return False
    if inicio <= ahora_ts:
        st["no_vigentes"] += 1
        return False
    if inicio > ahora_ts + HORAS_VENTANA_PREVIA * 3600:
        st["lejanos"] += 1
        return False
    return True


def _remapear_historial(historial, id_fuente, id_evento):
    """Reescribe el ID del equipo evaluado; conserva los IDs de sus rivales para triangulación."""
    if id_fuente is None or id_evento is None or str(id_fuente) == str(id_evento):
        return historial
    copia = []
    for partido in historial:
        p = dict(partido)
        if str(p.get("id_local")) == str(id_fuente):
            p["id_local"] = str(id_evento)
        if str(p.get("id_visita")) == str(id_fuente):
            p["id_visita"] = str(id_evento)
        copia.append(p)
    return copia


def _historial_equipo(ev, lado):
    """Prueba historial en todas las fuentes que observaron el evento antes de declararlo sin datos."""
    principal = ev.get(lado) or {}
    id_evento = principal.get("id")
    observaciones = ev.get("_observaciones") or [ev]
    observaciones = sorted(observaciones, key=_prioridad_evento)
    probadas = set()
    for candidato in observaciones:
        fuente = str(candidato.get("fuente") or "")
        clave_obs = (fuente, str((candidato.get(lado) or {}).get("id") or ""))
        if clave_obs in probadas:
            continue
        probadas.add(clave_obs)
        try:
            historial = U.historial_desde_fuentes(
                candidato, lado, fuente_espn, fuente_highlightly, fuente_oddspapi, fuente_api_football
            )
            if historial:
                return _remapear_historial(historial, (candidato.get(lado) or {}).get("id"), id_evento)
        except Exception as exc:
            U.log(f"[historial] fuente {fuente or '?'} falló para {ev.get('id')}: {type(exc).__name__}")
        if fuente_openligadb and candidato.get("deporte") == "Soccer":
            try:
                equipo = candidato.get(lado) or {}
                forma = fuente_openligadb.obtener_forma_reciente(
                    equipo.get("nombre", ""), deporte="Soccer", limite=10,
                    id_interno=(principal.get("id") if id_evento is not None else equipo.get("id")),
                )
                if forma:
                    return _remapear_historial(forma, equipo.get("id"), id_evento)
            except Exception as exc:
                U.log(f"[historial/openligadb] {type(exc).__name__} para {ev.get('id')}")
    return []


def _procesar_evento(ev, st, ahora_ts):
    clave = _clave_canonica_evento(ev)
    if not clave:
        st["errores"] += 1
        U.log("[radar] evento ignorado: no tiene clave de deduplicación")
        return False

    nom_loc = str((ev.get("local") or {}).get("nombre") or "").strip()
    nom_vis = str((ev.get("visita") or {}).get("nombre") or "").strip()
    torneo = str(ev.get("torneo") or "Competición sin nombre")
    deporte = str(ev.get("deporte") or "")

    # Cada fuente declara femenino_seguro solo después de aplicar evidencia positiva
    # (nombre explícito o competición incluida en una allowlist de ligas femeninas).
    femenino = bool(ev.get("femenino_seguro")) or U.es_femenino(torneo, nom_loc, nom_vis)
    if not femenino:
        U.log(f"[filtro] rechazo por falta de evidencia femenina: {torneo} | {nom_loc} vs {nom_vis}")
        return False
    st["femeninos"] += 1

    if not _fecha_evento_valida(ev, ahora_ts, st):
        return False

    # Se suprimen solo alertas que ya llegaron a Telegram. No se descartan los
    # partidos previamente analizados sin mismatch: sus datos pueden cambiar.
    if registro.visto(clave):
        st["ya_vistos"] += 1
        return False

    estado = "PRE"

    if deporte == "Tennis":
        local = ev.get("local") or {}
        visita = ev.get("visita") or {}
        sin_ranking = (
            local.get("ranking") is None
            and visita.get("ranking") is None
            and not local.get("fuera_ranking")
            and not visita.get("fuera_ranking")
        )
        if sin_ranking:
            st["sin_datos"] += 1
            return False
        st["analizados"] += 1
        hay, detalle, favorito, pts = motor_mismatches.evaluar_mismatch_tenis(
            nom_loc,
            nom_vis,
            local.get("ranking"),
            visita.get("ranking"),
            fuera_local=bool(local.get("fuera_ranking", False)),
            fuera_visita=bool(visita.get("fuera_ranking", False)),
        )
        if hay and pts >= 2:
            entregado = enviar_alerta(
                deporte,
                torneo,
                nom_loc,
                nom_vis,
                str(ev.get("horario") or "A confirmar"),
                [detalle],
                favorito,
                "Alta" if pts >= 3 else "Media",
            )
            st["alertas"] += 1
            if entregado:
                registro.marcar(clave)
        return True

    id_loc = (ev.get("local") or {}).get("id")
    id_vis = (ev.get("visita") or {}).get("id")
    forma_loc = _historial_equipo(ev, "local")
    forma_vis = _historial_equipo(ev, "visita")
    if not forma_loc or not forma_vis:
        st["sin_datos"] += 1
        U.log(
            f"[sin-datos] {torneo}: {nom_loc} vs {nom_vis}; "
            "no se marca como procesado y se volverá a intentar en el próximo ciclo"
        )
        return False

    st["analizados"] += 1
    perf_loc = motor_mismatches.evaluar_rendimiento_reciente(forma_loc, id_loc)
    perf_vis = motor_mismatches.evaluar_rendimiento_reciente(forma_vis, id_vis)
    triangs = motor_mismatches.triangular_rivales(forma_loc, id_loc, forma_vis, id_vis)
    h2h_raw = U.h2h_desde_fuentes(
        ev, forma_loc, forma_vis, fuente_highlightly, fuente_oddspapi, id_vis
    )
    h2h = motor_mismatches.analizar_h2h_extendido(h2h_raw, id_loc, id_vis)
    datos_extra = {
        "descanso": motor_mismatches.evaluar_descanso(forma_loc, id_loc, forma_vis, id_vis),
        "racha_local": motor_mismatches.evaluar_momentum(forma_loc, id_loc),
        "racha_visita": motor_mismatches.evaluar_momentum(forma_vis, id_vis),
    }

    def evaluar(tabla_eval):
        return motor_mismatches.evaluar_mismatch(
            deporte=deporte,
            perf_local=perf_loc,
            perf_visita=perf_vis,
            triangulaciones=triangs,
            h2h=h2h,
            tabla_local_visita=tabla_eval,
            datos_extra=datos_extra,
        )

    resultado = evaluar(None)
    if (
        not resultado["hay_mismatch"]
        and resultado["puntaje"] >= 2
        and resultado["puntaje_contrario"] <= 1
    ):
        tabla, cantidad_equipos = U.tabla_desde_fuentes(ev, fuente_highlightly)
        if tabla:
            resultado = evaluar(
                motor_mismatches.evaluar_tabla_posiciones(
                    tabla, id_loc, id_vis, n_equipos=cantidad_equipos
                )
            )

    if resultado["hay_mismatch"]:
        favorito = resultado["favorito"]
        entregado = enviar_alerta(
            deporte,
            torneo,
            nom_loc,
            nom_vis,
            str(ev.get("horario") or "A confirmar"),
            resultado.get("alertas") or [],
            favorito,
            resultado.get("confianza", "Media"),
        )
        st["alertas"] += 1
        if entregado:
            registro.marcar(clave)
    elif resultado.get("puntaje", 0) > 0:
        U.log(f"[analisis] sin mismatch suficiente: {nom_loc} vs {nom_vis}: {resultado.get('motivo_descarte', '')}")

    # IMPORTANTE: no registrar aquí los casos sin mismatch. Se vuelven a evaluar
    # hasta que empiece el evento, salga de la ventana o se envíe una alerta.
    return True


# ---------------------------------------------------------------------------
# Agregación multi-fuente: selección por profundidad, no por orden de respuesta.
# ---------------------------------------------------------------------------
_PRIORIDAD_FUENTE = {
    "highlightly": 0,
    "api_sports": 1,
    "openligadb": 2,
    "espn": 3,
    "oddspapi": 4,
    "thesportsdb": 5,
}


def _prioridad_evento(ev):
    fuente = str(ev.get("fuente") or "")
    if ev.get("deporte") == "Tennis" and fuente == "espn":
        return -1
    prioridad = _PRIORIDAD_FUENTE.get(fuente, 99)
    local = ev.get("local") or {}
    visita = ev.get("visita") or {}
    # Se prefieren datos de ranking cuando la comparación es individual.
    if ev.get("deporte") == "Tennis" and (local.get("ranking") or visita.get("ranking")):
        prioridad -= 2
    return prioridad


def _recolectar_eventos(resumen):
    fuentes = [
        (fuente_highlightly, "highlightly"),
        (fuente_api_football, "api_sports"),
        (fuente_openligadb, "openligadb"),
        (fuente_oddspapi, "oddspapi"),
        (fuente_thesportsdb, "thesportsdb"),
    ]
    if ESPN_ACTIVO:
        fuentes.append((fuente_espn, "espn"))

    candidatos = {}
    for modulo, nombre in fuentes:
        if modulo is None:
            continue
        try:
            if hasattr(modulo, "disponible") and not modulo.disponible():
                U.log(f"[{nombre}] omitida: falta clave o la fuente está deshabilitada")
                continue
        except Exception as exc:
            U.log(f"[{nombre}] error comprobando disponibilidad: {type(exc).__name__}")
            continue

        for deporte in DEPORTES_RADAR:
            try:
                eventos = modulo.obtener_eventos(deporte) or []
            except Exception as exc:
                U.log(f"[{nombre}] error listando {deporte}: {type(exc).__name__}: {exc}")
                continue

            st = resumen.setdefault(f"{nombre}:{deporte}", _nuevo_stat())
            st["eventos"] += len(eventos)
            for ev in eventos:
                clave = _clave_canonica_evento(ev)
                if not clave:
                    U.log(f"[{nombre}] evento descartado por no tener id/clave")
                    continue
                actual = candidatos.get(clave)
                observacion = dict(ev)
                observacion.pop("_observaciones", None)
                if actual is None:
                    copia = dict(observacion)
                    copia["clave"] = clave
                    copia["_fuentes_detectadas"] = [nombre]
                    copia["_observaciones"] = [observacion]
                    candidatos[clave] = copia
                    continue

                observaciones = list(actual.get("_observaciones", []))
                fuente_obs = str(observacion.get("fuente") or nombre)
                ids_existentes = {(str(o.get("fuente") or ""), str(o.get("id") or "")) for o in observaciones}
                if (fuente_obs, str(observacion.get("id") or "")) not in ids_existentes:
                    observaciones.append(observacion)
                fuentes_detectadas = list(actual.get("_fuentes_detectadas", []))
                if nombre not in fuentes_detectadas:
                    fuentes_detectadas.append(nombre)

                if _prioridad_evento(observacion) < _prioridad_evento(actual):
                    copia = dict(observacion)
                    copia["clave"] = clave
                    copia["_fuentes_detectadas"] = fuentes_detectadas
                    copia["_observaciones"] = observaciones
                    candidatos[clave] = copia
                else:
                    actual["_fuentes_detectadas"] = fuentes_detectadas
                    actual["_observaciones"] = observaciones

    U.log(f"[agregador] {sum(len(v.get('_fuentes_detectadas', [])) for v in candidatos.values())} observaciones de fuentes; {len(candidatos)} eventos únicos")
    return list(candidatos.values())


def _imprimir_resumen(resumen):
    U.log("--- Resumen del barrido ---")
    if not resumen:
        U.log("las fuentes no devolvieron eventos dentro de la ventana o sus planes no exponen calendario")
    for etapa, st in resumen.items():
        U.log(
            f"{etapa}: {st['eventos']} eventos capturados -> {st['femeninos']} femeninos validados -> "
            f"{st['analizados']} análisis completos -> {st['alertas']} alertas generadas "
            f"(alertas ya enviadas {st['ya_vistos']}, sin datos {st['sin_datos']}, "
            f"no vigentes {st['no_vigentes']}, fuera de ventana {st['lejanos']}, errores {st['errores']})"
        )
    for fuente, codigos in U.ESTADISTICAS.items():
        U.log(f"HTTP {fuente}: {dict(codigos)}")


def _avisar_si_esta_ciego(resumen):
    global _ultimo_aviso_ciego
    hubo_200 = any(codigos.get(200, 0) for codigos in U.ESTADISTICAS.values())
    if hubo_200:
        return
    hay_pedidos = any(sum(codigos.values()) for codigos in U.ESTADISTICAS.values())
    if not hay_pedidos or time.time() - _ultimo_aviso_ciego < 6 * 3600:
        return
    _ultimo_aviso_ciego = time.time()
    detalle = ", ".join(f"{fuente}: {dict(codigos)}" for fuente, codigos in U.ESTADISTICAS.items())
    enviar_telegram(
        "⚠️ <b>El radar no pudo obtener ninguna respuesta HTTP 200.</b>\n"
        f"Respuestas por fuente: {html.escape(detalle[:700])}\n"
        "Revisá claves, restricciones del plan o disponibilidad del proveedor."
    )


def ejecutar_barrido_radar():
    U.reiniciar_estadisticas()
    U.log("=== Barrido de asimetrías deportivas femeninas ===")
    if motor_mismatches is None:
        U.log("[fatal] motor_mismatches no está disponible; se omite este barrido")
        return

    registro.podar()
    resumen = {}
    ahora_ts = time.time()
    eventos = _recolectar_eventos(resumen)
    eventos.sort(key=lambda ev: ev.get("startTimestamp", 0))

    intentos = 0
    for ev in eventos:
        if intentos >= MAX_ANALISIS_POR_CICLO:
            U.log(f"[radar] alcanzado el límite de {MAX_ANALISIS_POR_CICLO} eventos por ciclo")
            break
        st = resumen.setdefault(f"{ev.get('fuente', 'ext')}:{ev.get('deporte', 'Multi')}", _nuevo_stat())
        intentos += 1
        try:
            _procesar_evento(ev, st, ahora_ts)
        except Exception as exc:
            st["errores"] += 1
            U.log(f"[radar] error en evento {ev.get('id', '?')}: {type(exc).__name__}: {exc}")
        registro.guardar()

    registro.guardar()
    _imprimir_resumen(resumen)
    _avisar_si_esta_ciego(resumen)


def _fuentes_activas():
    fuentes = []
    if fuente_highlightly and fuente_highlightly.disponible():
        fuentes.append("Highlightly")
    if fuente_api_football and fuente_api_football.disponible():
        fuentes.append("API-Sports")
    if fuente_openligadb:
        fuentes.append("OpenLigaDB sin clave")
    if fuente_oddspapi and fuente_oddspapi.disponible():
        fuentes.append("OddsPapi (solo fixtures, sin cuotas)")
    if fuente_thesportsdb:
        fuentes.append("TheSportsDB V1")
    if ESPN_ACTIVO and fuente_espn:
        fuentes.append("ESPN (respaldo)")
    return fuentes


def main():
    U.log("Radar Femenino: servicio iniciado")
    U.log(f"Persistencia de estado: {U.modo_persistencia()}")
    U.log(f"Intervalo={INTERVALO_REVISION}s; máximo de eventos/ciclo={MAX_ANALISIS_POR_CICLO}")
    fuentes = _fuentes_activas()
    U.log(f"Fuentes configuradas: {', '.join(fuentes) or 'ninguna'}")
    if not U.persistencia_es_duradera():
        U.log("[persistencia] ADVERTENCIA: el filesystem local de Render es efímero; configurá Upstash para estado duradero")
    enviar_telegram(
        "🤖 <b>Radar femenino activo.</b>\n"
        f"Fuentes: {html.escape(', '.join(fuentes) or 'ninguna')}\n"
        f"Persistencia: {html.escape(U.modo_persistencia())}\n"
        "Modo: datos deportivos y calendario; cuotas deshabilitadas."
    )
    while True:
        inicio = time.monotonic()
        try:
            ejecutar_barrido_radar()
        except Exception as exc:
            U.log(f"[radar] error no controlado del ciclo: {type(exc).__name__}: {exc}")
        duracion = time.monotonic() - inicio
        time.sleep(max(1, INTERVALO_REVISION - int(duracion)))


if __name__ == "__main__":
    main()
