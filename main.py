"""Radar de asimetrías deportivas exclusivamente femeninas.

El sistema no consulta, almacena ni muestra cuotas, bookmakers ni probabilidades
implícitas. Usa resultados recientes, rankings disponibles, H2H, tablas y calendario.

Fuentes de calendario: Highlightly, API-Sports, OpenLigaDB, TheSportsDB,
The Odds API (solo fixtures) y OddsPapi (solo fixtures). ESPN queda como respaldo de menor prioridad
y como única fuente de ranking WTA para tenis.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

import requests

import utilidades as U


# ---------------------------------------------------------------------------
# HTTP de salud para Render.
# ---------------------------------------------------------------------------
ESTADO = {
    "inicio": time.time(),
    "barridos": 0,
    "ultimo_barrido_utc": None,
    "ultimo_barrido_segundos": None,
    "eventos_unicos": 0,
    "fuentes": [],
    "libro_resultados": 0,
    "errores_ultimo_barrido": 0,
    "analizados": 0,
    "presupuestos": {},
}


def estado_salud():
    intervalo = globals().get("INTERVALO_REVISION", 900)
    ultimo = ESTADO["ultimo_barrido_utc"]
    if ultimo and globals().get("motor_mismatches") is not None:
        if time.time() - datetime.fromisoformat(ultimo).timestamp() < max(1800, intervalo * 3):
            return "ok"
    if ultimo is None and time.time() - ESTADO["inicio"] < max(300, intervalo * 3):
        return "starting"
    return "degraded"


class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        payload = {
            "service": "radar-femenino",
            "status": estado_salud(),
            "analysis_last_sweep": ESTADO["analizados"],
            "budgets": ESTADO["presupuestos"],
            "persistence": U.modo_persistencia(),
            "sports_scope": "women_only",
            "market_data": False,
            "uptime_seconds": int(time.time() - ESTADO["inicio"]),
            "sweeps": ESTADO["barridos"],
            "last_sweep_utc": ESTADO["ultimo_barrido_utc"],
            "last_sweep_seconds": ESTADO["ultimo_barrido_segundos"],
            "unique_events_last_sweep": ESTADO["eventos_unicos"],
            "sources": list(ESTADO["fuentes"]),
            "results_ledger": ESTADO["libro_resultados"],
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(503 if payload["status"] == "degraded" else 200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

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
ARCHIVO_ENFRIAMIENTO = "enfriamiento_sin_datos.json"

ENFRIAMIENTO_SIN_DATOS_MIN = max(0, int(os.environ.get("ENFRIAMIENTO_SIN_DATOS_MIN", "60")))
ENFRIAMIENTO_MAX_MIN = max(ENFRIAMIENTO_SIN_DATOS_MIN, int(os.environ.get("ENFRIAMIENTO_MAX_MIN", "360")))
MAX_BUSQUEDAS_POR_NOMBRE = max(0, int(os.environ.get("MAX_BUSQUEDAS_POR_NOMBRE", "15")))
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
fuente_theoddsapi = _importar("fuente_theoddsapi")
libro_resultados = _importar("libro_resultados")
tenis_contexto = _importar("tenis_contexto")
ranking_wta = _importar("ranking_wta")
_ultimo_intento = U.cargar_json("ultimo_intento_v2.json", {})
if not isinstance(_ultimo_intento, dict):
    _ultimo_intento = {}

registro = U.RegistroVistos(ARCHIVO_ALERTADOS, dias_retencion=3)
_ultimo_aviso_ciego = 0.0


def _cargar_enfriamiento() -> dict[str, tuple[float, int]]:
    crudo = U.cargar_json(ARCHIVO_ENFRIAMIENTO, {})
    if not isinstance(crudo, dict):
        return {}
    ahora_ts = time.time()
    limpio = {}
    for k, v in crudo.items():
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            try:
                t_exp, fallos = float(v[0]), int(v[1])
                if t_exp > ahora_ts:
                    limpio[str(k)] = (t_exp, fallos)
            except (ValueError, TypeError):
                continue
    return limpio


def _guardar_enfriamiento(enf: dict[str, tuple[float, int]]) -> None:
    ahora_ts = time.time()
    payload = {k: [round(v[0], 1), v[1]] for k, v in enf.items() if v[0] > ahora_ts}
    U.guardar_json(ARCHIVO_ENFRIAMIENTO, payload)


_enfriamiento: dict[str, tuple[float, int]] = _cargar_enfriamiento()
_FUENTES_CON_HISTORIAL_PROPIO = {"highlightly", "api_sports", "openligadb", "thesportsdb", "espn"}


# ---------------------------------------------------------------------------
# Telegram: salida estrictamente deportiva
# ---------------------------------------------------------------------------
def _sin_html(texto: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", texto))


def _recortar_html(texto: str, limite: int = 4000) -> str:
    if len(texto) <= limite:
        return texto
    corte = texto[:limite]
    ultimo_salto = corte.rfind("\n")
    return (corte[:ultimo_salto] if ultimo_salto > 0 else corte) + "\n…"


def _post_telegram(url: str, payload: dict[str, Any], destino: str):
    try:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        respuesta = requests.post(url, data=cuerpo, headers=headers, timeout=12)
    except requests.RequestException as exc:
        U.log(f"[telegram] error de red ({type(exc).__name__}) para chat {destino}")
        return None, 0
    espera = 0
    if respuesta.status_code == 429:
        try:
            espera = int(respuesta.json().get("parameters", {}).get("retry_after", 3))
        except (ValueError, TypeError, AttributeError):
            espera = 3
    return respuesta.status_code, espera


def enviar_telegram(mensaje_html: str) -> bool:
    if not TELEGRAM_TOKEN:
        U.log("[telegram] falta TELEGRAM_TOKEN; mensaje no enviado")
        return False
    destinos = [c for c in (CHAT_ID, CHAT_ID_GRUPO) if c]
    if not destinos:
        U.log("[telegram] faltan CHAT_ID y CHAT_ID_GRUPO; mensaje no enviado")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    mensaje_html = _recortar_html(mensaje_html)
    entregado = False
    for destino in destinos:
        entregado_destino = False
        for modo in ("HTML", None):
            payload = {
                "chat_id": destino,
                "disable_web_page_preview": True,
                "text": mensaje_html if modo else _sin_html(mensaje_html),
            }
            if modo:
                payload["parse_mode"] = modo
            status = None
            for _intento in range(3):
                status, espera = _post_telegram(url, payload, destino)
                if status == 429:
                    time.sleep(min(max(espera, 1), 30))
                    continue
                break
            if status == 200:
                entregado_destino = True
                break
            U.log(f"[telegram] HTTP {status} para chat {destino}; modo={modo}")
            if status != 400:
                break
        entregado = entregado or entregado_destino
    return entregado


def enviar_alerta(deporte, torneo, nom_loc, nom_vis, hora_txt, alertas_base, favorito, confianza="Media",
                  fuentes=None, tipo="MISMATCH DEPORTIVO FEMENINO — ASIMETRÍA"):
    if motor_mismatches is None:
        return False
    nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
    esc = html.escape
    detalles_txt = "\n".join(f"• {esc(str(d))}" for d in list(alertas_base)[:10])
    mensaje = (
        f"🚨 <b>{esc(tipo)}</b>\n\n"
        f"🏅 <b>Deporte:</b> {esc(str(deporte))}\n"
        f"🏆 <b>Competición:</b> {esc(str(torneo))}\n"
        f"⚔️ <b>Encuentro:</b> {esc(str(nom_loc))} vs {esc(str(nom_vis))}\n"
        f"📌 <b>Favorito:</b> {esc(str(nom_fav))} (ventaja deportiva)\n"
        f"🕒 <b>Horario:</b> {esc(str(hora_txt))}\n"
        f"📡 <b>Fuentes:</b> {esc(', '.join(str(f) for f in (fuentes or [])) or 'sin dato')}\n\n"
        f"📊 <b>Evidencia:</b>\n{detalles_txt or 'Sin detalle adicional.'}\n\n"
        f"🔎 <b>Evaluación de evidencia:</b> {esc(str(confianza))}\n"
        "<i>Estimación basada en datos deportivos; no se usan cuotas ni mercados.</i>"
    )
    entregado = enviar_telegram(mensaje)
    U.log(
        f"[alerta] {deporte}: {nom_loc} vs {nom_vis}; ventaja={nom_fav}; "
        f"telegram={'ok' if entregado else 'no entregado'}"
    )
    return entregado


# ---------------------------------------------------------------------------
# Deduplicación y control de enfriamiento
# ---------------------------------------------------------------------------
TOLERANCIA_FECHA_S = 6 * 3600


def _firma_evento(ev: dict[str, Any]) -> str:
    local = (ev.get("local") or {}).get("nombre") or ""
    visita = (ev.get("visita") or {}).get("nombre") or ""
    return f"{ev.get('deporte', '')}|{U.firma_partido(local, visita)}" if local and visita else ""


def _inicio_evento(ev: dict[str, Any]) -> int:
    try:
        return int(ev.get("startTimestamp") or 0)
    except (TypeError, ValueError):
        return 0


def _clave_canonica_evento(ev: dict[str, Any]) -> str:
    firma = _firma_evento(ev)
    inicio = _inicio_evento(ev)
    if not firma or not inicio:
        return str(ev.get("clave") or ev.get("id") or "").strip()
    dia_utc = datetime.fromtimestamp(inicio, timezone.utc).strftime("%Y%m%d")
    return f"{firma}|{dia_utc}"


def _claves_equivalentes(ev: dict[str, Any]) -> set[str]:
    firma = _firma_evento(ev)
    inicio = _inicio_evento(ev)
    if not firma or not inicio:
        return {_clave_canonica_evento(ev)}
    dias = {
        datetime.fromtimestamp(inicio + delta, timezone.utc).strftime("%Y%m%d")
        for delta in (-TOLERANCIA_FECHA_S, 0, TOLERANCIA_FECHA_S)
    }
    claves = {f"{firma}|{dia}" for dia in dias}
    # Compatibilidad con alertas previas de mayores; jamás heredar claves juveniles ambiguas.
    if all(U.categoria_equipo((ev.get(lado) or {}).get("nombre", "")) == ((), False)
           for lado in ("local", "visita")):
        legacy = U.firma_partido(ev["local"]["nombre"], ev["visita"]["nombre"])
        claves.update(f"{legacy}|{dia}" for dia in dias)
    return claves


def _ya_alertado(ev: dict[str, Any]) -> bool:
    return any(registro.visto(clave) for clave in _claves_equivalentes(ev) if clave)


def _registrar_sin_datos(clave: str, ev: dict[str, Any]) -> None:
    if not ENFRIAMIENTO_SIN_DATOS_MIN:
        return
    fallos = _enfriamiento.get(clave, (0, 0))[1] + 1
    minutos = min(ENFRIAMIENTO_MAX_MIN, ENFRIAMIENTO_SIN_DATOS_MIN * 2 ** (fallos - 1))
    _enfriamiento[clave] = (time.time() + minutos * 60, fallos)
    _guardar_enfriamiento(_enfriamiento)


def _en_enfriamiento(clave: str, ahora_ts: float) -> bool:
    item = _enfriamiento.get(clave)
    return bool(item and ahora_ts < item[0])


def _tiene_historial_propio(ev: dict[str, Any]) -> bool:
    if ev.get("deporte") == "Tennis":
        return True
    fuentes = set(ev.get("_fuentes_detectadas") or []) | {str(ev.get("fuente") or "")}
    if fuentes & _FUENTES_CON_HISTORIAL_PROPIO:
        return True
    return bool(libro_resultados and libro_resultados.tiene_historial(ev))


def _nuevo_stat():
    return {
        "enfriados": 0,
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


_COSTO_HISTORIAL = {
    "openligadb": 0, "espn": 1, "thesportsdb": 2, "oddspapi": 3, "theoddsapi": 4, "highlightly": 5, "api_sports": 6,
}


def _historial_equipo(ev, lado):
    principal = ev.get(lado) or {}
    id_evento = principal.get("id")
    observaciones = sorted(
        ev.get("_observaciones") or [ev],
        key=lambda o: _COSTO_HISTORIAL.get(str(o.get("fuente") or ""), 99),
    )
    mejor = []

    def suficiente(historial):
        nonlocal mejor
        historial = motor_mismatches.historial_valido(historial, id_evento)
        if historial and len(historial) > len(mejor):
            mejor = historial
        return len(mejor) >= U.MIN_HISTORIAL_UTIL

    probadas = set()
    for candidato in observaciones:
        fuente = str(candidato.get("fuente") or "")
        lado_candidato = next((l for l in ("local", "visita")
                               if U.firma_equipo((candidato.get(l) or {}).get("nombre", "")) ==
                               U.firma_equipo(principal.get("nombre", ""))), None)
        if lado_candidato is None:
            continue
        id_candidato = (candidato.get(lado_candidato) or {}).get("id")
        clave_obs = (fuente, str(id_candidato or ""))
        if clave_obs in probadas:
            continue
        probadas.add(clave_obs)
        try:
            historial = U.historial_desde_fuentes(
                candidato, lado_candidato, fuente_espn, fuente_highlightly, fuente_oddspapi, fuente_api_football,
                fuente_thesportsdb=fuente_thesportsdb, modo="propia",
            )
            # Remapea los dos participantes del evento, incluso con localía invertida.
            mapa_ids = {}
            for lado_actual in ("local", "visita"):
                equipo_actual = ev.get(lado_actual) or {}
                lado_obs = next((l for l in ("local", "visita")
                                 if U.firma_equipo((candidato.get(l) or {}).get("nombre", "")) ==
                                 U.firma_equipo(equipo_actual.get("nombre", ""))), None)
                if lado_obs:
                    id_original = candidato[lado_obs].get("id")
                    if id_original is not None and equipo_actual.get("id") is not None:
                        mapa_ids[str(id_original)] = str(equipo_actual["id"])
            historial = [dict(p, id_local=mapa_ids.get(str(p.get("id_local")), p.get("id_local")),
                              id_visita=mapa_ids.get(str(p.get("id_visita")), p.get("id_visita")))
                         for p in historial]
            if suficiente(historial):
                return mejor
        except Exception as exc:
            U.log(f"[historial] fuente {fuente or '?'} falló para {ev.get('id')}: {type(exc).__name__}")
        if fuente_openligadb and candidato.get("deporte") == "Soccer":
            try:
                equipo = candidato.get(lado_candidato) or {}
                forma = fuente_openligadb.obtener_forma_reciente(
                    equipo.get("nombre", ""), deporte="Soccer", limite=10,
                    id_interno=(principal.get("id") if id_evento is not None else equipo.get("id")),
                )
                if suficiente(_remapear_historial(forma, equipo.get("id"), id_evento)):
                    return mejor
            except Exception as exc:
                U.log(f"[historial/openligadb] {type(exc).__name__} para {ev.get('id')}")

    if libro_resultados:
        try:
            if suficiente(libro_resultados.historial_equipo(ev, lado, limite=10)):
                return mejor
        except Exception as exc:
            U.log(f"[historial/libro] {type(exc).__name__} para {ev.get('id')}")

    try:
        por_nombre = U.historial_desde_fuentes(
            ev, lado, fuente_espn, fuente_highlightly, fuente_oddspapi, fuente_api_football,
            fuente_thesportsdb=fuente_thesportsdb, modo="nombre",
        )
        suficiente(_remapear_historial(por_nombre, id_evento, id_evento))
    except Exception as exc:
        U.log(f"[historial] búsqueda por nombre falló para {ev.get('id')}: {type(exc).__name__}")
    return mejor


def _evaluar_plantel(ev, deporte, nom_loc, nom_vis):
    if not fuente_espn or not hasattr(fuente_espn, "lesiones_equipo"):
        return None
    try:
        obs_espn = next((o for o in ev.get("_observaciones") or [] if o.get("fuente") == "espn"), None)
        if obs_espn:
            nl, nv, inferir = obs_espn["local"]["nombre"], obs_espn["visita"]["nombre"], True
        else:
            nl, nv, inferir = nom_loc, nom_vis, False
        return motor_mismatches.evaluar_plantel(
            fuente_espn.lesiones_equipo(deporte, nl, inferir_cero=inferir),
            fuente_espn.lesiones_equipo(deporte, nv, inferir_cero=inferir),
            deporte,
        )
    except Exception as exc:
        U.log(f"[plantel] {type(exc).__name__} para {ev.get('id')}")
        return None


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

    femenino = bool(ev.get("femenino_seguro")) or U.es_femenino(torneo, nom_loc, nom_vis)
    if not femenino:
        U.log(f"[filtro] rechazo por falta de evidencia femenina: {torneo} | {nom_loc} vs {nom_vis}")
        return False
    st["femeninos"] += 1
    if not U.participante_definido(nom_loc) or not U.participante_definido(nom_vis) or U.firma_equipo(nom_loc) == U.firma_equipo(nom_vis):
        st["sin_datos"] += 1
        return False

    if not _fecha_evento_valida(ev, ahora_ts, st):
        return False

    if _ya_alertado(ev):
        st["ya_vistos"] += 1
        return False

    if deporte == "Tennis":
        local = ev.get("local") or {}
        visita = ev.get("visita") or {}
        sin_ranking = local.get("ranking") is None or visita.get("ranking") is None
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
            corte_ranking=local.get("ranking_corte") or visita.get("ranking_corte"),
        )
        U.log(f"[tenis] {nom_loc} (#{local.get('ranking') or 'desconocido'}) vs {nom_vis} "
              f"(#{visita.get('ranking') or 'desconocido'}) -> {pts} pts; fecha={local.get('ranking_fecha')}")
        detalles_tenis = [detalle]
        for jugador in (local, visita):
            detalles_tenis.append(f"Ranking: {jugador.get('ranking_fuente') or 'sin verificar'}; fecha {jugador.get('ranking_fecha') or 'desconocida'}")
        ctx = None
        if hay and tenis_contexto:
            nom_fav, nom_riv = (nom_loc, nom_vis) if favorito == motor_mismatches.LOCAL else (nom_vis, nom_loc)
            try:
                ctx = tenis_contexto.evaluar_contexto(nom_fav, nom_riv, torneo)
            except Exception as exc:
                U.log(f"[tenis] contexto no disponible: {type(exc).__name__}")
                ctx = None
            ajuste, extra = motor_mismatches.ajustar_tenis_por_contexto(favorito, ctx)
            pts += ajuste
            detalles_tenis.extend(extra)
        contexto_util = bool(ctx and ctx.get("disponible"))
        if not contexto_util:
            detalles_tenis.append("Forma y superficie recientes no disponibles: candidato basado solo en ranking.")
        if hay and pts >= 2:
            entregado = enviar_alerta(
                deporte,
                torneo,
                nom_loc,
                nom_vis,
                str(ev.get("horario") or "A confirmar"),
                detalles_tenis,
                favorito,
                "Magnitud: fuerte" if pts >= 3 else "Magnitud: moderada",
                fuentes=list(ev.get("_fuentes_detectadas") or []) + list({j.get("ranking_fuente") for j in (local, visita) if j.get("ranking_fuente")}),
                tipo="CANDIDATO TENIS FEMENINO — BRECHA DE RANKING" if not contexto_util else "ASIMETRÍA TENIS FEMENINO",
            )
            st["alertas"] += 1
            if entregado:
                registro.marcar(clave)
        return True

    id_loc = (ev.get("local") or {}).get("id")
    id_vis = (ev.get("visita") or {}).get("id")
    forma_loc = _historial_equipo(ev, "local")
    forma_vis = _historial_equipo(ev, "visita")
    forma_loc = motor_mismatches.historial_valido(forma_loc, id_loc)
    forma_vis = motor_mismatches.historial_valido(forma_vis, id_vis)
    if not forma_loc or not forma_vis:
        st["sin_datos"] += 1
        _registrar_sin_datos(clave, ev)
        U.log(f"[datos-parciales] {torneo}: {nom_loc} vs {nom_vis}; forma {len(forma_loc)}/{len(forma_vis)}; se evalúan otras señales disponibles")

    st["analizados"] += 1
    perf_loc = motor_mismatches.evaluar_rendimiento_reciente(forma_loc, id_loc, deporte)
    perf_vis = motor_mismatches.evaluar_rendimiento_reciente(forma_vis, id_vis, deporte)
    triangs = motor_mismatches.triangular_rivales(forma_loc, id_loc, forma_vis, id_vis)
    
    h2h_raw = U.h2h_desde_fuentes(
        ev, forma_loc, forma_vis, fuente_highlightly, fuente_oddspapi, id_vis, libro_resultados=libro_resultados
    )
    h2h = motor_mismatches.analizar_h2h_extendido(h2h_raw, id_loc, id_vis)
    datos_extra = {
        "descanso": motor_mismatches.evaluar_descanso(forma_loc, id_loc, forma_vis, id_vis),
        "congestion": motor_mismatches.evaluar_congestion(forma_loc, id_loc, forma_vis, id_vis),
        "racha_local": motor_mismatches.evaluar_momentum(forma_loc, id_loc),
        "racha_visita": motor_mismatches.evaluar_momentum(forma_vis, id_vis),
    }
    if libro_resultados:
        try:
            datos_extra["elo"] = motor_mismatches.evaluar_elo(libro_resultados.consulta_elo(deporte, nom_loc, nom_vis))
        except Exception as exc:
            U.log(f"[elo] {type(exc).__name__} para {ev.get('id')}")
    datos_extra["plantel"] = _evaluar_plantel(ev, deporte, nom_loc, nom_vis)

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

    tabla, cantidad_equipos = U.tabla_desde_fuentes(ev, fuente_highlightly)
    resultado = evaluar(
        motor_mismatches.evaluar_tabla_posiciones(tabla, id_loc, id_vis, cantidad_equipos) if tabla else None
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
            f"Magnitud: {resultado.get('magnitud', 'Moderada')}; calidad: {resultado.get('calidad_datos', 'Limitada')}; "
            f"{resultado.get('grupos_independientes', 1)} familia(s) de señales, sin independencia garantizada",
            fuentes=ev.get("_fuentes_detectadas"),
        )
        st["alertas"] += 1
        if entregado:
            registro.marcar(clave)
    elif resultado.get("puntaje", 0) > 0:
        U.log(f"[analisis] sin mismatch suficiente: {nom_loc} vs {nom_vis}: {resultado.get('motivo_descarte', '')}")

    return True


# ---------------------------------------------------------------------------
# Agregación multi-fuente
# ---------------------------------------------------------------------------
_PRIORIDAD_FUENTE = {
    "highlightly": 0,
    "api_sports": 1,
    "openligadb": 2,
    "thesportsdb": 3,
    "oddspapi": 4,
    "theoddsapi": 5,
    "espn": 6,
}


def _prioridad_evento(ev):
    fuente = str(ev.get("fuente") or "")
    if ev.get("deporte") == "Tennis" and fuente == "espn":
        return -1
    prioridad = _PRIORIDAD_FUENTE.get(fuente, 99)
    local = ev.get("local") or {}
    visita = ev.get("visita") or {}
    if ev.get("deporte") == "Tennis" and (local.get("ranking") or visita.get("ranking")):
        prioridad -= 2
    return prioridad


def _coincide_con_candidato(candidato, firma, inicio):
    if _firma_evento(candidato) != firma:
        return False
    inicio_c = _inicio_evento(candidato)
    if not inicio or not inicio_c:
        return False
    mismo_dia = _clave_canonica_evento(candidato).rsplit("|", 1)[-1] == datetime.fromtimestamp(
        inicio, timezone.utc).strftime("%Y%m%d")
    return mismo_dia or abs(inicio_c - inicio) <= TOLERANCIA_FECHA_S


def _recolectar_eventos(resumen):
    fuentes = [
        (fuente_highlightly, "highlightly"),
        (fuente_api_football, "api_sports"),
        (fuente_openligadb, "openligadb"),
        (fuente_thesportsdb, "thesportsdb"),
        (fuente_theoddsapi, "theoddsapi"),
        (fuente_oddspapi, "oddspapi"),
    ]
    if ESPN_ACTIVO:
        fuentes.append((fuente_espn, "espn"))

    candidatos = {}
    por_firma = defaultdict(list)
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
                firma = _firma_evento(ev)
                inicio = _inicio_evento(ev)
                observacion = dict(ev)
                observacion.pop("_observaciones", None)

                clave_actual = None
                if firma and inicio:
                    for clave_c in por_firma.get(firma, []):
                        if _coincide_con_candidato(candidatos[clave_c], firma, inicio):
                            clave_actual = clave_c
                            break
                if clave_actual is None:
                    clave = _clave_canonica_evento(ev)
                    if not clave:
                        U.log(f"[{nombre}] evento descartado por no tener id/clave")
                        continue
                    if clave in candidatos:
                        clave_actual = clave

                if clave_actual is None:
                    copia = dict(observacion)
                    copia["clave"] = clave
                    copia["_fuentes_detectadas"] = [nombre]
                    copia["_observaciones"] = [observacion]
                    candidatos[clave] = copia
                    if firma:
                        por_firma[firma].append(clave)
                    continue

                actual = candidatos[clave_actual]
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
                    copia["clave"] = actual.get("clave", clave_actual)
                    copia["_fuentes_detectadas"] = fuentes_detectadas
                    copia["_observaciones"] = observaciones
                    candidatos[clave_actual] = copia
                else:
                    actual["_fuentes_detectadas"] = fuentes_detectadas
                    actual["_observaciones"] = observaciones

    _log_aporte_por_fuente(candidatos)
    salida = list(candidatos.values())
    if ranking_wta and any(ev.get("deporte") == "Tennis" for ev in salida):
        ranking_wta.enriquecer(salida, fuente_espn)
    elif ranking_wta is None:
        for ev in salida:
            if ev.get("deporte") == "Tennis":
                for lado in ("local", "visita"):
                    (ev.get(lado) or {})["ranking"] = None
    return salida


def _log_aporte_por_fuente(candidatos):
    aportes = defaultdict(lambda: {"detectados": 0, "exclusivos": 0, "principal": 0})
    for ev in candidatos.values():
        detectadas = ev.get("_fuentes_detectadas", [])
        for nombre in detectadas:
            aportes[nombre]["detectados"] += 1
        if len(detectadas) == 1:
            aportes[detectadas[0]]["exclusivos"] += 1
        aportes[str(ev.get("fuente") or "?")]["principal"] += 1
    total_obs = sum(a["detectados"] for a in aportes.values())
    U.log(f"[agregador] {total_obs} observaciones de fuentes; {len(candidatos)} eventos únicos")
    if aportes:
        detalle = ", ".join(
            f"{n}={a['detectados']}/{a['exclusivos']}/{a['principal']}" for n, a in sorted(aportes.items())
        )
        U.log(f"[agregador] aporte por fuente (detectados/exclusivos/principal): {detalle}")


def _imprimir_resumen(resumen):
    U.log("--- Resumen del barrido ---")
    if not resumen:
        U.log("las fuentes no devolvieron eventos dentro de la ventana o sus planes no exponen calendario")
    for etapa, st in resumen.items():
        U.log(
            f"{etapa}: {st['eventos']} eventos capturados -> {st['femeninos']} femeninos validados -> "
            f"{st['analizados']} análisis completos -> {st['alertas']} alertas generadas "
            f"(alertas ya enviadas {st['ya_vistos']}, sin datos {st['sin_datos']}, en enfriamiento {st['enfriados']}, "
            f"no vigentes {st['no_vigentes']}, fuera de ventana {st['lejanos']}, errores {st['errores']})"
        )
    for fuente, codigos in U.ESTADISTICAS.items():
        U.log(f"HTTP {fuente}: {dict(codigos)}")


def _avisar_si_esta_ciego(resumen):
    global _ultimo_aviso_ciego
    hubo_200 = any(codigos.get(200, 0) for codigos in U.ESTADISTICAS.values())
    analizados = sum(st["analizados"] for st in resumen.values())
    capturados = sum(st["eventos"] for st in resumen.values())
    if hubo_200 or not any(sum(c.values()) for c in U.ESTADISTICAS.values()):
        if capturados and not analizados and time.time() - _ultimo_aviso_ciego >= 6 * 3600:
            _ultimo_aviso_ciego = time.time()
            enviar_telegram("⚠️ <b>Radar con calendario, pero sin análisis útiles en este barrido.</b>\n"
                            "Revisá disponibilidad de rankings, historial y presupuestos por deporte.")
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
    t_inicio = time.monotonic()
    eventos = _recolectar_eventos(resumen)
    # Los pendientes nunca procesados van primero; luego rota por último intento.
    eventos.sort(key=lambda ev: (_ultimo_intento.get(_clave_canonica_evento(ev), 0), ev.get("startTimestamp", 0)))

    intentos = 0
    busquedas_por_nombre = 0
    omitidos_busqueda = 0
    for ev in eventos:
        if intentos >= MAX_ANALISIS_POR_CICLO:
            U.log(f"[radar] alcanzado el límite de {MAX_ANALISIS_POR_CICLO} eventos por ciclo")
            break
        st = resumen.setdefault(f"{ev.get('fuente', 'ext')}:{ev.get('deporte', 'Multi')}", _nuevo_stat())
        clave_ev = _clave_canonica_evento(ev)
        if _en_enfriamiento(clave_ev, ahora_ts):
            st["enfriados"] += 1
            continue
        # Filtros baratos antes de gastar cupo. Tenis sin ranking no ocupa intentos.
        if not _fecha_evento_valida(ev, ahora_ts, st):
            continue
        if _ya_alertado(ev):
            st["ya_vistos"] += 1
            continue
        if not all(U.participante_definido((ev.get(lado) or {}).get("nombre")) for lado in ("local", "visita")):
            st["sin_datos"] += 1
            continue
        if ev.get("deporte") == "Tennis" and not all((ev.get(lado) or {}).get("ranking") for lado in ("local", "visita")):
            st["sin_datos"] += 1
            continue
        if not _tiene_historial_propio(ev):
            if busquedas_por_nombre >= MAX_BUSQUEDAS_POR_NOMBRE:
                omitidos_busqueda += 1
                continue
            busquedas_por_nombre += 1
        intentos += 1
        _ultimo_intento[clave_ev] = ahora_ts
        descartes_antes = st["lejanos"] + st["no_vigentes"] + st["ya_vistos"]
        try:
            _procesar_evento(ev, st, ahora_ts)
            if st["lejanos"] + st["no_vigentes"] + st["ya_vistos"] > descartes_antes:
                intentos -= 1
                if not _tiene_historial_propio(ev):
                    busquedas_por_nombre -= 1
        except Exception as exc:
            st["errores"] += 1
            U.log(f"[radar] error en evento {ev.get('id', '?')}: {type(exc).__name__}: {exc}")
        registro.guardar()

    registro.guardar()
    _guardar_enfriamiento(_enfriamiento)
    if libro_resultados:
        libro_resultados.guardar()
        ESTADO["libro_resultados"] = libro_resultados.total()
    if omitidos_busqueda:
        U.log(f"[radar] {omitidos_busqueda} eventos solo-calendario esperan al próximo ciclo "
              f"(tope de {MAX_BUSQUEDAS_POR_NOMBRE} búsquedas por nombre por ciclo)")
    claves_actuales = {_clave_canonica_evento(ev) for ev in eventos}
    for k in list(_ultimo_intento):
        if k not in claves_actuales:
            _ultimo_intento.pop(k, None)
    U.guardar_json("ultimo_intento_v2.json", _ultimo_intento)
    ESTADO["analizados"] = sum(st["analizados"] for st in resumen.values())
    ESTADO["errores_ultimo_barrido"] = sum(st["errores"] for st in resumen.values())
    ESTADO["presupuestos"] = _resumen_presupuestos()
    ESTADO["barridos"] += 1
    ESTADO["ultimo_barrido_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ESTADO["ultimo_barrido_segundos"] = round(time.monotonic() - t_inicio, 1)
    ESTADO["eventos_unicos"] = len(eventos)
    _imprimir_resumen(resumen)
    _avisar_si_esta_ciego(resumen)


def _resumen_presupuestos():
    salida = {}
    for modulo in (fuente_api_football, fuente_highlightly):
        for nombre, presupuesto in getattr(modulo, "_presupuestos", {}).items():
            restante = presupuesto.restantes()
            fila = {"fecha_utc": presupuesto.fecha, "usadas": presupuesto.usadas,
                    "limite": presupuesto.limite, "disponibles_bot": restante}
            salida[f"{modulo.FUENTE}:{nombre}"] = fila
            U.log(f"[presupuesto/{modulo.FUENTE}/{nombre}] {fila}")
    for modulo in (fuente_oddspapi, fuente_theoddsapi):
        if modulo and modulo.disponible():
            salida[modulo.FUENTE] = modulo.presupuesto.resumen()
            U.log(f"[presupuesto/{modulo.FUENTE}] {salida[modulo.FUENTE]}")
    return salida


def _fuentes_activas():
    fuentes = []
    if fuente_highlightly and fuente_highlightly.disponible():
        fuentes.append("Highlightly")
    if fuente_api_football and fuente_api_football.disponible():
        fuentes.append("API-Sports")
    if fuente_openligadb and fuente_openligadb.disponible():
        fuentes.append("OpenLigaDB sin clave")
    if fuente_thesportsdb and (fuente_thesportsdb.disponible() or fuente_thesportsdb.historial_disponible()):
        fuentes.append("TheSportsDB V1 (fixtures + historial)")
    if fuente_theoddsapi and fuente_theoddsapi.disponible():
        fuentes.append("The Odds API (solo fixtures, sin cuotas)")
    if fuente_oddspapi and fuente_oddspapi.disponible():
        fuentes.append("OddsPapi (solo fixtures, sin cuotas)")
    if ESPN_ACTIVO and fuente_espn:
        fuentes.append("ESPN (respaldo)")
    return fuentes


def main():
    U.log("Radar Femenino: servicio iniciado")
    U.log(f"Persistencia de estado: {U.modo_persistencia()}")
    U.log(f"Intervalo={INTERVALO_REVISION}s; máximo de eventos/ciclo={MAX_ANALISIS_POR_CICLO}")
    fuentes = _fuentes_activas()
    ESTADO["fuentes"] = fuentes
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
