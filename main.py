"""Radar de asimetrías deportivas exclusivamente femeninas.

El sistema no consulta, almacena ni muestra cuotas, bookmakers ni probabilidades
implícitas. Usa resultados recientes, rankings disponibles, H2H, tablas y calendario.

Calendarios y contexto femeninos de fuentes oficiales y proveedores configurados.
El ranking principal es WTA oficial, con ESPN como respaldo de alcance limitado.
La auditoría y evaluación prospectiva usan namespaces separados del historial anterior.
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
import mensajes
import analisis_deportivo
import motor_voley
import auditoria_decisiones as auditoria
import cobertura_radar as cobertura
import resultados_evaluacion as resultados
import planificador_datos as planificador
import mapa_fuentes


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
            "revision": "sportsapi-app-v1",
            "coverage": ESTADO.get("coverage", {}),
            "audit": ESTADO.get("audit", {}),
            "outcome_evaluation": ESTADO.get("outcome_evaluation", {}),
            "data_planner": ESTADO.get("data_planner", {}),
            "source_capabilities": ESTADO.get("source_capabilities", {}),
            "status": estado_salud(),
            "analysis_last_sweep": ESTADO["analizados"],
            "budgets": ESTADO["presupuestos"],
            "http_last_sweep": ESTADO.get("http_last_sweep", {}),
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
        cricsheet = globals().get("fuente_cricsheet")
        if cricsheet and "cricsheet" in payload["budgets"]:
            payload["budgets"] = dict(payload["budgets"])
            payload["budgets"]["cricsheet"] = dict(payload["budgets"]["cricsheet"], **cricsheet.estado())
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
DEPORTES_RADAR = ["Soccer", "Basketball", "Tennis", "Ice Hockey", "Handball", "Volleyball", "Rugby",
                  "Softball", "Lacrosse", "Field Hockey", "Cricket"]
DEPORTES_SIN_CUPO_COMERCIAL = {"Softball", "Lacrosse", "Field Hockey"}


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
ranking_wta = _importar("ranking_wta")
fuente_wta = _importar("fuente_wta")
fuente_pwhl = _importar("fuente_pwhl")
fuente_fivb = _importar("fuente_fivb")
fuente_cev = _importar("fuente_cev")
fuente_bbs = _importar("fuente_bbs")
fuente_sportscore = _importar("fuente_sportscore")
fuente_worldrugby = _importar("fuente_worldrugby")
fuente_sportapi = _importar("fuente_sportapi")
fuente_sportsapi_app = _importar("fuente_sportsapi_app")
motor_tenis = _importar("motor_tenis")
motor_cricket = _importar("motor_cricket")
fuente_cricsheet = _importar("fuente_cricsheet")
fuente_balldontlie = _importar("fuente_balldontlie")
fuente_tennis_api = _importar("fuente_tennis_api")
fuente_lvf = _importar("fuente_lvf")
fuente_lnv = _importar("fuente_lnv")
fuente_tauron = _importar("fuente_tauron")
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
_FUENTES_CON_HISTORIAL_PROPIO = {"highlightly", "api_sports", "openligadb", "thesportsdb", "espn", "pwhl", "fivb", "cev", "bbs", "sportscore", "worldrugby", "sportapi", "balldontlie", "tauron", "sportsapi_app"}


# ---------------------------------------------------------------------------
# Telegram: salida estrictamente deportiva
# ---------------------------------------------------------------------------
def _sin_html(texto: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", texto))


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
    enviar_telegram.ultima_entrega = {}
    if not TELEGRAM_TOKEN:
        U.log("[telegram] falta TELEGRAM_TOKEN; mensaje no enviado")
        return False
    destinos = [c for c in (CHAT_ID, CHAT_ID_GRUPO) if c]
    if not destinos:
        U.log("[telegram] faltan CHAT_ID y CHAT_ID_GRUPO; mensaje no enviado")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        partes = mensajes.dividir_html(mensaje_html)
    except ValueError:
        U.log("[telegram] formato inválido; no se envía una alerta incompleta")
        return False
    entregado = False
    enviar_telegram.ultima_entrega = {}
    for destino in destinos:
        entregado_destino = True
        for parte in partes:
            parte_ok = False
            for modo in ("HTML", None):
                payload = {
                    "chat_id": destino,
                    "disable_web_page_preview": True,
                    "text": parte if modo else _sin_html(parte),
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
                    parte_ok = True
                    break
                U.log(f"[telegram] HTTP {status} para chat {destino}; modo={modo}")
                if status != 400:
                    break
            if not parte_ok:
                entregado_destino = False
                break
        role = "personal" if destino == CHAT_ID else "group"
        enviar_telegram.ultima_entrega[role] = entregado_destino
        cobertura.actual.entrega(role, entregado_destino)
        entregado = entregado or entregado_destino
    return entregado


def enviar_alerta(deporte, torneo, nom_loc, nom_vis, hora_txt, alertas_base, favorito, confianza="Media",
                  fuentes=None, tipo="MISMATCH DEPORTIVO FEMENINO — ASIMETRÍA", analisis=None):
    if motor_mismatches is None:
        return False
    nom_fav = nom_loc if favorito == motor_mismatches.LOCAL else nom_vis
    mensaje = mensajes.alerta(deporte, torneo, nom_loc, nom_vis, hora_txt, alertas_base,
                              nom_fav, confianza, fuentes, tipo, analisis=analisis)
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
    # Unificar únicamente aliases confirmados por un catálogo nacional que
    # también validó ambos participantes y la competición del encuentro.
    if ev.get("deporte") == "Volleyball":
        contextos = _contextos_oficiales(ev)
        if contextos:
            tabla, _ = contextos[0].tabla_partido(ev)
            local = tabla[ev["local"]["id"]].get("nombre", local)
            visita = tabla[ev["visita"]["id"]].get("nombre", visita)
    firma = f"{ev.get('deporte', '')}|{U.firma_partido(local, visita)}" if local and visita else ""
    if firma and ev.get("deporte") == "Cricket":
        firma += "|" + str(ev.get("formato_cricket", ""))
    return firma


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
    if ev.get("deporte") == "Softball":
        return f"{firma}|{dia_utc}|{ev.get('id') or inicio}"  # permite doble jornada
    if ev.get("deporte") == "Cricket":
        return f"{firma}|{dia_utc}|{inicio}"  # separar formatos y doble jornada
    return f"{firma}|{dia_utc}"


def _claves_equivalentes(ev: dict[str, Any]) -> set[str]:
    if ev.get("deporte") in ("Softball", "Cricket"):
        return {_clave_canonica_evento(ev)}
    firma = _firma_evento(ev)
    inicio = _inicio_evento(ev)
    if not firma or not inicio:
        return {_clave_canonica_evento(ev)}
    dias = {
        datetime.fromtimestamp(inicio + delta, timezone.utc).strftime("%Y%m%d")
        for delta in (-TOLERANCIA_FECHA_S, 0, TOLERANCIA_FECHA_S)
    }
    claves = {f"{firma}|{dia}" for dia in dias}
    original = f"{ev.get('deporte', '')}|" + U.firma_partido(ev["local"]["nombre"], ev["visita"]["nombre"])
    claves.update(f"{original}|{dia}" for dia in dias)
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
    if _contextos_oficiales(ev):
        return True  # identidad resuelta sin búsquedas comerciales por nombre
    return bool(libro_resultados and libro_resultados.tiene_historial(ev))


def _contextos_oficiales(ev):
    if ev.get("deporte") != "Volleyball":
        return []
    return [m for m in (fuente_lvf, fuente_lnv, fuente_tauron)
            if m and m.disponible() and m.tabla_partido(ev)[0]]


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
    "sportsapi_app": 3,
}


def _historial_equipo(ev, lado):
    oficiales = _contextos_oficiales(ev)
    if ev.get("historial_aislado"):
        modulo = {"fivb": fuente_fivb, "cev": fuente_cev, "bbs": fuente_bbs, "sportscore": fuente_sportscore, "worldrugby": fuente_worldrugby, "sportapi": fuente_sportapi, "balldontlie": fuente_balldontlie, "tauron": fuente_tauron, "sportsapi_app": fuente_sportsapi_app}.get(ev.get("fuente"))
        mejor = modulo.historial_equipo(ev, lado) if modulo else []
        # Sólo respaldos nacionales que validaron ambos nombres y competición.
        # CEV internacional no se mezcla con resultados de una liga doméstica.
        for oficial in oficiales:
            if len(mejor) >= U.MIN_HISTORIAL_UTIL:
                break
            extra = oficial.historial_equipo(ev, lado)
            if len(extra) > len(mejor):
                mejor = extra
        return mejor
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
    for modulo in oficiales:
        if suficiente(modulo.historial_equipo(ev, lado)):
            return mejor
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
                candidato, lado_candidato, fuente_espn,
                None if ev.get("deporte") in DEPORTES_SIN_CUPO_COMERCIAL else fuente_highlightly,
                None if ev.get("deporte") in DEPORTES_SIN_CUPO_COMERCIAL else fuente_oddspapi,
                None if ev.get("deporte") in DEPORTES_SIN_CUPO_COMERCIAL else fuente_api_football,
                fuente_thesportsdb=fuente_thesportsdb, modo="propia",
            )
            if fuente == "bbs" and fuente_bbs:
                historial = fuente_bbs.historial_equipo(candidato, lado_candidato)
            elif fuente == "sportscore" and fuente_sportscore:
                historial = fuente_sportscore.historial_equipo(candidato, lado_candidato)
            elif fuente == "balldontlie" and fuente_balldontlie:
                historial = fuente_balldontlie.historial_equipo(candidato, lado_candidato)
            elif fuente == "worldrugby" and fuente_worldrugby:
                historial = fuente_worldrugby.historial_equipo(candidato, lado_candidato)
            elif fuente == "sportapi" and fuente_sportapi:
                historial = fuente_sportapi.historial_equipo(candidato, lado_candidato)
            elif fuente == "sportsapi_app" and fuente_sportsapi_app:
                historial = fuente_sportsapi_app.historial_equipo(candidato,lado_candidato)
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

    if ev.get("deporte") in DEPORTES_SIN_CUPO_COMERCIAL:
        return mejor  # solo historial de su liga/temporada; ningún respaldo medido por nombre
    if libro_resultados:
        try:
            if suficiente(libro_resultados.historial_equipo(ev, lado, limite=10)):
                return mejor
        except Exception as exc:
            U.log(f"[historial/libro] {type(exc).__name__} para {ev.get('id')}")

    if oficiales:
        return mejor  # contexto resuelto; no gastar búsquedas por nombre de respaldo
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


def _tabla_evento(ev):
    """Primero tablas sin cupo comercial; luego API propia, finalmente búsquedas HL."""
    if ev.get("deporte") == "Volleyball":
        for modulo in (fuente_lvf,fuente_lnv,fuente_tauron):
            if modulo and modulo.disponible():
                tabla,cantidad=modulo.tabla_partido(ev)
                if tabla:
                    return tabla,cantidad
    if ev.get("fuente") == "fivb" and fuente_fivb:
        tabla,cantidad=fuente_fivb.tabla_partido(ev)
        if tabla:
            return tabla,cantidad
    observaciones = sorted(ev.get("_observaciones") or [ev],
                           key=lambda o: {"openligadb": 0, "espn": 1, "api_sports": 2, "highlightly": 3}.get(o.get("fuente"), 9))
    for obs in observaciones:
        modulo = {"openligadb": fuente_openligadb, "espn": fuente_espn, "api_sports": fuente_api_football,
                  "cev": fuente_cev, "fivb": fuente_fivb, "tauron": fuente_tauron, "sportsapi_app": fuente_sportsapi_app}.get(obs.get("fuente"))
        if not modulo or not hasattr(modulo, "tabla_partido"):
            continue
        try:
            raw, cantidad = modulo.tabla_partido(obs)
        except (KeyError, ValueError, TypeError) as exc:
            U.log(f"[tabla/{obs.get('fuente')}] formato rechazado: {type(exc).__name__}")
            continue
        if not raw:
            continue
        tabla = {}
        for lado in ("local", "visita"):
            id_obs = str((obs.get(lado) or {}).get("id"))
            nombre = (obs.get(lado) or {}).get("nombre", "")
            lado_ev = next((l for l in ("local", "visita") if U.firma_equipo(ev[l]["nombre"]) == U.firma_equipo(nombre)), None)
            if lado_ev and id_obs in raw:
                tabla[ev[lado_ev]["id"]] = raw[id_obs]
        if len(tabla) == 2:
            return tabla, cantidad
    if ev.get("historial_aislado") or ev.get("deporte") in DEPORTES_SIN_CUPO_COMERCIAL:
        return None, 0
    hl = next((o for o in observaciones if o.get("fuente") == "highlightly"), ev)
    raw, cantidad = U.tabla_desde_fuentes(hl, fuente_highlightly)
    if not raw:
        return None, 0
    tabla = {}
    for lado in ("local", "visita"):
        id_obs = (hl.get(lado) or {}).get("id")
        nombre = (hl.get(lado) or {}).get("nombre", "")
        lado_ev = next((l for l in ("local", "visita") if U.firma_equipo(ev[l]["nombre"]) == U.firma_equipo(nombre)), None)
        if lado_ev and id_obs in raw:
            tabla[ev[lado_ev]["id"]] = raw[id_obs]
    return (tabla, cantidad) if len(tabla) == 2 else (None, 0)


def _decision(ev, state, reason, inputs=None, result=None, delivery=None):
    key = _clave_canonica_evento(ev) or auditoria.digest([ev.get('fuente'), ev.get('id'), ev.get('torneo')])
    cobertura.actual.decision(key, state, reason, result)
    sid = auditoria.registrar(ev, key, state, reason, inputs, result, delivery)
    if inputs is not None and result is not None:
        try:
            resultados.actual().seguir(ev, key, sid, state, result)
        except Exception as exc:
            U.log("[outcomes] seguimiento omitido: " + type(exc).__name__)
    return sid


def _procesar_evento(ev, st, ahora_ts):
    clave = _clave_canonica_evento(ev)
    if not clave:
        st["errores"] += 1
        U.log("[radar] evento ignorado: no tiene clave de deduplicación")
        _decision(ev, "discard", "missing_identity")
        return False

    nom_loc = str((ev.get("local") or {}).get("nombre") or "").strip()
    nom_vis = str((ev.get("visita") or {}).get("nombre") or "").strip()
    torneo = str(ev.get("torneo") or "Competición sin nombre")
    deporte = str(ev.get("deporte") or "")

    femenino = bool(ev.get("femenino_seguro")) or U.es_femenino(torneo, nom_loc, nom_vis)
    if not femenino:
        U.log(f"[filtro] rechazo por falta de evidencia femenina: {torneo} | {nom_loc} vs {nom_vis}")
        _decision(ev, "discard", "gender_unverified")
        return False
    st["femeninos"] += 1
    if not U.participante_definido(nom_loc) or not U.participante_definido(nom_vis) or U.firma_equipo(nom_loc) == U.firma_equipo(nom_vis):
        st["sin_datos"] += 1
        _decision(ev,"unevaluable","undefined_participant")
        return False

    if not _fecha_evento_valida(ev, ahora_ts, st):
        _decision(ev,"pending","outside_pre_match_window")
        return False

    if _ya_alertado(ev):
        st["ya_vistos"] += 1
        _decision(ev,"pending","already_delivered")
        return False

    if deporte == "Cricket":
        # No pasar runs/wickets por el motor de diferencias de goles/puntos.
        if not motor_cricket or not fuente_cricsheet:
            st["sin_datos"] += 1
            _decision(ev,"unevaluable","missing_cricket_module")
            return False
        registros_c = fuente_cricsheet.historial(ev)
        inputs_c = {"registros": registros_c, "evaluation_at_utc": ahora_ts}
        resultado_c = motor_cricket.evaluar(ev, registros_c, ahora_ts)
        _decision(ev, "alert" if resultado_c["alertar"] else "discard", resultado_c.get("motivo", "threshold"), inputs_c, resultado_c)
        st["analizados"] += 1
        if resultado_c["alertar"]:
            if time.time() >= ev["startTimestamp"]:
                _decision(ev, "discard", "started_during_evaluation", inputs_c, resultado_c)
                return True
            if fuente_sportscore and not fuente_sportscore.permite_alerta(ev):
                U.log("[cricket] detalle del mismo partido contradice el calendario; alerta omitida")
                _decision(ev, "discard", "provider_contradiction", inputs_c, resultado_c)
                return True
            entregado = enviar_alerta(deporte, torneo, nom_loc, nom_vis,
                str(ev.get("horario") or "A confirmar"), resultado_c["evidencia"], resultado_c["favorito"],
                "Evaluación experimental; historial parcial y señales relacionadas",
                fuentes=list(ev.get("_fuentes_detectadas") or [ev.get("fuente")]) + resultado_c["fuentes"],
                tipo="CANDIDATO CRICKET — EXPERIMENTAL")
            st["alertas"] += 1
            _decision(ev, "alert", "threshold_met", inputs_c, resultado_c, {"any_complete": entregado, "roles": getattr(enviar_telegram, "ultima_entrega", {})})
            if entregado:
                registro.marcar(clave)
        else:
            U.log(f"[cricket] {nom_loc} vs {nom_vis}: {resultado_c['motivo']}")
        return True

    if deporte == "Tennis":
        local, visita = ev.get("local") or {}, ev.get("visita") or {}
        if not motor_tenis:
            st["sin_datos"] += 1
            _decision(ev,"unevaluable","missing_tennis_module")
            return False
        # El ranking selecciona candidatos; WC puede abrir la evaluación de experiencia.
        base = motor_mismatches.evaluar_mismatch_tenis(nom_loc, nom_vis, local.get("ranking"), visita.get("ranking"))
        wc = any(j.get("entry") == "WC" and j.get("entry_fuente") == "WTA cuadro oficial" for j in (local, visita))
        if not base[0] and not wc:
            _decision(ev, "discard", "tennis_candidate_filter", {}, {"puntaje":0})
            st["analizados"] += 1
            return True
        if any(j.get("ranking_conflicto") for j in (local,visita)):
            _decision(ev,"unevaluable","ranking_sources_conflict")
            return False
        perfiles = {}
        if fuente_wta:
            for lado, j in ((motor_mismatches.LOCAL, local), (motor_mismatches.VISITA, visita)):
                perfiles[lado] = fuente_wta.perfil(j)
        if fuente_tennis_api and fuente_tennis_api.disponible():
            for lado,j in ((motor_mismatches.LOCAL,local),(motor_mismatches.VISITA,visita)):
                oficial=perfiles.get(lado)
                if not oficial or not oficial.get("recientes") or j.get("entry") == "WC":
                    perfiles[lado]=fuente_tennis_api.complementar(oficial,fuente_tennis_api.perfil(j))
        if fuente_sportsapi_app and fuente_sportsapi_app.disponible():
            obs_app=next((o for o in ev.get('_observaciones') or [ev] if o.get('fuente')=='sportsapi_app'),None)
            if obs_app:
                for lado,j in ((motor_mismatches.LOCAL,local),(motor_mismatches.VISITA,visita)):
                    if not (perfiles.get(lado) or {}).get('recientes'):
                        side=next((s for s in ('local','visita') if U.firma_equipo(obs_app[s]['nombre'])==U.firma_equipo(j['nombre'])),None)
                        perfil=fuente_sportsapi_app.perfil_tenis(obs_app,side) if side else None
                        if perfil:perfiles[lado]=perfil
        if any(j.get("ranking_conflicto") for j in (local,visita)):
            _decision(ev,"unevaluable","ranking_sources_conflict")
            return False
        inputs_t = {"perfiles": perfiles, "evaluation_at_utc": ahora_ts}
        resultado_t = motor_tenis.evaluar(ev, perfiles, ahora=ahora_ts)
        _decision(ev, "alert" if resultado_t["alertar"] else "discard", resultado_t.get("motivo", "threshold_met"), inputs_t, resultado_t)
        st["analizados"] += 1
        if resultado_t["alertar"]:
            if time.time() >= ev["startTimestamp"]:
                _decision(ev, "discard", "started_during_evaluation", inputs_t, resultado_t)
                return True
            entregado = enviar_alerta(deporte, torneo, nom_loc, nom_vis,
                str(ev.get("horario") or "A confirmar"), resultado_t["evidencia"], resultado_t["favorito"],
                f"Magnitud: {'fuerte' if resultado_t['puntaje'] >= 4 else 'moderada'}; calidad: {resultado_t['calidad']}",
                fuentes=list(ev.get("_fuentes_detectadas") or []) + resultado_t["fuentes"] +
                        list({j.get("ranking_fuente") for j in (local, visita) if j.get("ranking_fuente")}),
                tipo=resultado_t["tipo"], analisis=resultado_t.get('analisis_deportivo'))
            st["alertas"] += 1
            _decision(ev, "alert", "threshold_met", inputs_t, resultado_t, {"any_complete": entregado, "roles": getattr(enviar_telegram, "ultima_entrega", {})})
            if entregado:
                registro.marcar(clave)
        else:
            U.log(f"[tenis] {nom_loc} vs {nom_vis}: {resultado_t.get('motivo', 'sin evidencia suficiente')}")
        return True

    id_loc = (ev.get("local") or {}).get("id")
    id_vis = (ev.get("visita") or {}).get("id")
    if ev.get("fuente") == "pwhl" and fuente_pwhl:
        forma_loc = fuente_pwhl.historial_equipo(ev, "local")
        forma_vis = fuente_pwhl.historial_equipo(ev, "visita")
    else:
        forma_loc = _historial_equipo(ev, "local")
        forma_vis = _historial_equipo(ev, "visita")
    if deporte == 'Volleyball':
        forma_loc, forma_vis = (motor_voley.historial_sets(rows) for rows in (forma_loc,forma_vis))
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
        ev, forma_loc, forma_vis,
        None if ev.get("historial_aislado") or deporte in DEPORTES_SIN_CUPO_COMERCIAL else fuente_highlightly,
        None if ev.get("historial_aislado") or deporte in DEPORTES_SIN_CUPO_COMERCIAL else fuente_oddspapi,
        id_vis, libro_resultados=None if ev.get("historial_aislado") or deporte in DEPORTES_SIN_CUPO_COMERCIAL else libro_resultados
    )
    if ev.get("fuente") == "sportscore" and fuente_sportscore:
        # El motor deduplica los encuentros presentes también en la forma.
        h2h_raw = list(h2h_raw or []) + fuente_sportscore.h2h_partido(ev)
    if deporte == 'Volleyball':
        h2h_raw = motor_voley.historial_sets(h2h_raw)
    h2h = motor_mismatches.analizar_h2h_extendido(h2h_raw, id_loc, id_vis)
    calendario_util = bool(forma_loc and forma_vis and all(p.get("_calendario_completo") for p in forma_loc + forma_vis))
    datos_extra = {
        "descanso": motor_mismatches.evaluar_descanso(forma_loc, id_loc, forma_vis, id_vis) if calendario_util else None,
        "congestion": motor_mismatches.evaluar_congestion(forma_loc, id_loc, forma_vis, id_vis) if calendario_util else None,
        "racha_local": motor_mismatches.evaluar_momentum(forma_loc, id_loc),
        "racha_visita": motor_mismatches.evaluar_momentum(forma_vis, id_vis),
    }
    if libro_resultados and not ev.get("historial_aislado") and deporte not in DEPORTES_SIN_CUPO_COMERCIAL:
        try:
            datos_extra["elo"] = motor_mismatches.evaluar_elo(libro_resultados.consulta_elo(deporte, nom_loc, nom_vis))
        except Exception as exc:
            U.log(f"[elo] {type(exc).__name__} para {ev.get('id')}")
    datos_extra["plantel"] = _evaluar_plantel(ev, deporte, nom_loc, nom_vis)

    tabla, cantidad_equipos = _tabla_evento(ev)
    motor_kwargs = dict(deporte=deporte, perf_local=perf_loc, perf_visita=perf_vis,
                        triangulaciones=triangs, h2h=h2h,
                        tabla_local_visita=motor_mismatches.evaluar_tabla_posiciones(tabla, id_loc, id_vis, cantidad_equipos) if tabla else None,
                        datos_extra=datos_extra)
    inputs_e = {"motor_kwargs": motor_kwargs, "forma_local": forma_loc, "forma_visita": forma_vis,
                "h2h": h2h_raw, "tabla": tabla, "inputs_observed_at_utc": ahora_ts}
    cobertura.actual.contexto(clave, forma_loc, forma_vis, h2h_raw, tabla)
    resultado = motor_mismatches.evaluar_mismatch(**motor_kwargs)
    inputs_e['analisis_deportivo'] = analisis_deportivo.equipos(ev, resultado, forma_loc, forma_vis, ahora_ts)
    cobertura.actual.contextos[clave]['recommendations'] = inputs_e['analisis_deportivo']
    _decision(ev, "alert" if resultado["hay_mismatch"] else "discard", resultado.get("motivo_descarte") or "threshold_met", inputs_e, resultado)

    if resultado["hay_mismatch"]:
        if time.time() >= ev["startTimestamp"]:
            _decision(ev, "discard", "started_during_evaluation", inputs_e, resultado)
            return True
        favorito = resultado["favorito"]
        contexto, fuentes_alerta = [], list(ev.get("_fuentes_detectadas") or [ev.get("fuente")])
        fuentes_alerta += sorted({p.get("fuente") for p in forma_loc+forma_vis if p.get("fuente")} |
                                {r.get("fuente") for r in (tabla or {}).values() if r.get("fuente")})
        obs_ss = next((o for o in ev.get("_observaciones") or [ev] if o.get("fuente") == "sportscore"), None)
        if obs_ss and fuente_sportscore:
            if not fuente_sportscore.permite_alerta(obs_ss):
                U.log("[sportscore] detalle del mismo partido contradice el calendario; alerta omitida")
                _decision(ev, "discard", "provider_contradiction", inputs_e, resultado)
                return True
            contexto = fuente_sportscore.contexto_alerta(obs_ss)
            if ev.get("fuente") == "sportscore":
                contexto += fuente_sportscore.contexto_estadistico(ev, (forma_loc, forma_vis))
            if contexto and "sportscore" not in fuentes_alerta:
                fuentes_alerta.append("sportscore")
        entregado = enviar_alerta(
            deporte,
            torneo,
            nom_loc,
            nom_vis,
            str(ev.get("horario") or "A confirmar"),
            list(resultado.get("alertas") or []) + contexto,
            favorito,
            f"Magnitud: {resultado.get('magnitud', 'Moderada')}; calidad: {resultado.get('calidad_datos', 'Limitada')}; "
            f"{resultado.get('grupos_independientes', 1)} familia(s) de señales, sin independencia garantizada",
            fuentes=fuentes_alerta,
            tipo="ASIMETRÍA EXPERIMENTAL" if deporte in DEPORTES_SIN_CUPO_COMERCIAL else "MISMATCH DEPORTIVO FEMENINO — ASIMETRÍA",
            analisis=inputs_e['analisis_deportivo'],
        )
        st["alertas"] += 1
        _decision(ev, "alert", "threshold_met", inputs_e, resultado, {"any_complete": entregado, "roles": getattr(enviar_telegram, "ultima_entrega", {})})
        if entregado:
            registro.marcar(clave)
    elif resultado.get("puntaje", 0) > 0:
        U.log(f"[analisis] sin mismatch suficiente: {nom_loc} vs {nom_vis}: {resultado.get('motivo_descarte', '')}")

    return True


# ---------------------------------------------------------------------------
# Agregación multi-fuente
# ---------------------------------------------------------------------------
_PRIORIDAD_FUENTE = {
    "tennis_api": 4,
    "balldontlie": 3,
    "sportapi": 4,
    "worldrugby": -2,
    "sportscore": 7,
    "bbs": 4,
    "cev": -4,
    "tauron": -5,
    "fivb": -3,
    "wta": -2,
    "pwhl": -1,
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


def _coincide_con_candidato(candidato, firma, inicio, observacion=None):
    if _firma_evento(candidato) != firma:
        return False
    inicio_c = _inicio_evento(candidato)
    if not inicio or not inicio_c:
        return False
    if candidato.get("deporte") == "Softball" and observacion:
        return candidato.get("id") == observacion.get("id")  # dobles jornadas son partidos distintos
    if candidato.get("deporte") == "Cricket":
        return inicio_c == inicio
    mismo_dia = _clave_canonica_evento(candidato).rsplit("|", 1)[-1] == datetime.fromtimestamp(
        inicio, timezone.utc).strftime("%Y%m%d")
    return mismo_dia or abs(inicio_c - inicio) <= TOLERANCIA_FECHA_S


def _recolectar_eventos(resumen):
    fuentes = [
        (fuente_lvf, "lvf"),
        (fuente_lnv, "lnv"),
        (fuente_tauron, "tauron"),
        (fuente_tennis_api, "tennis_api"),
        (fuente_cev, "cev"),
        (fuente_fivb, "fivb"),
        (fuente_bbs, "bbs"),
        (fuente_balldontlie, "balldontlie"),
        (fuente_sportscore, "sportscore"),
        (fuente_worldrugby, "worldrugby"),
        (fuente_sportapi, "sportapi"),
        (fuente_sportsapi_app, "sportsapi_app"),
        (fuente_wta, "wta"),
        (fuente_pwhl, "pwhl"),
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

        deportes=modulo.deportes_ciclo(DEPORTES_RADAR) if nombre=="sportsapi_app" else DEPORTES_RADAR
        for deporte in deportes:
            if deporte == "Cricket" and nombre != "sportscore":
                continue  # calendario nuevo sin consumir cuotas comerciales
            if deporte in DEPORTES_SIN_CUPO_COMERCIAL and nombre != "espn":
                continue  # los nuevos deportes nunca consultan planes comerciales
            if not planificador.actual.permitido(nombre):
                cobertura.actual.consulta(nombre, deporte, 0, "provider_paused")
                continue
            try:
                eventos = modulo.obtener_eventos(deporte) or []
                cobertura.actual.consulta(nombre, deporte, len(eventos))
            except Exception as exc:
                U.log(f"[{nombre}] error listando {deporte}: {type(exc).__name__}: {exc}")
                cobertura.actual.consulta(nombre, deporte, 0, type(exc).__name__)
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
                        if _coincide_con_candidato(candidatos[clave_c], firma, inicio, observacion):
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
    if fuente_wta:
        fuente_wta.enriquecer(salida)
    if ranking_wta and any(ev.get("deporte") == "Tennis" for ev in salida):
        ranking_wta.enriquecer(salida, fuente_espn)
    elif ranking_wta is None:
        for ev in salida:
            if ev.get("deporte") == "Tennis":
                for lado in ("local", "visita"):
                    (ev.get(lado) or {})["ranking"] = None
    if fuente_tennis_api and fuente_tennis_api.disponible():
        fuente_tennis_api.enriquecer_rankings(salida)
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
            f"{st['analizados']} evaluaciones -> {st['alertas']} alertas generadas "
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
    cobertura.iniciar()
    planificador.actual.iniciar()
    U.log("=== Barrido de asimetrías deportivas femeninas ===")
    if motor_mismatches is None:
        U.log("[fatal] motor_mismatches no está disponible; se omite este barrido")
        return

    registro.podar()
    resumen = {}
    ahora_ts = time.time()
    t_inicio = time.monotonic()
    if fuente_wta:
        fuente_wta.iniciar_ciclo()
    if fuente_tennis_api:
        fuente_tennis_api.iniciar_ciclo()
    for modulo in (fuente_fivb, fuente_cev, fuente_lvf, fuente_lnv):
        if modulo and hasattr(modulo, "iniciar_ciclo"):
            modulo.iniciar_ciclo()
    eventos = _recolectar_eventos(resumen)
    # Los pendientes nunca procesados van primero; luego rota por último intento.
    eventos = planificador.actual.ordenar_eventos(eventos, _ultimo_intento, _clave_canonica_evento, ahora_ts)
    for ev in eventos:
        cobertura.actual.evento(_clave_canonica_evento(ev), ev)

    tareas = [{"key": _clave_canonica_evento(ev), "source": ev.get('fuente','unknown'),
               "deadline":ev.get('startTimestamp',ahora_ts), "missing":not _tiene_historial_propio(ev),
               "new_coverage":not _ultimo_intento.get(_clave_canonica_evento(ev)), "cost":1} for ev in eventos]
    saldos = planificador.saldos_disponibles(ESTADO.get('presupuestos', {}))
    planificador.actual.seleccionar(tareas, saldos, ahora_ts, MAX_ANALISIS_POR_CICLO)
    intentos = 0
    busquedas_por_nombre = 0
    omitidos_busqueda = 0
    for posicion, ev in enumerate(eventos):
        if intentos >= MAX_ANALISIS_POR_CICLO:
            U.log(f"[radar] alcanzado el límite de {MAX_ANALISIS_POR_CICLO} eventos por ciclo")
            for pendiente in eventos[posicion:]:
                _decision(pendiente, "pending", "analysis_queue")
            break
        st = resumen.setdefault(f"{ev.get('fuente', 'ext')}:{ev.get('deporte', 'Multi')}", _nuevo_stat())
        clave_ev = _clave_canonica_evento(ev)
        if _en_enfriamiento(clave_ev, ahora_ts):
            st["enfriados"] += 1
            _decision(ev, "pending", "cooldown")
            continue
        # Filtros baratos antes de gastar cupo. Tenis sin ranking no ocupa intentos.
        if not _fecha_evento_valida(ev, ahora_ts, st):
            _decision(ev, "pending" if not ev.get("startTimestamp") or ev.get("startTimestamp",0)>ahora_ts else "discard", "outside_pre_match_window")
            continue
        if _ya_alertado(ev):
            st["ya_vistos"] += 1
            _decision(ev, "pending", "already_delivered")
            continue
        if not all(U.participante_definido((ev.get(lado) or {}).get("nombre")) for lado in ("local", "visita")):
            st["sin_datos"] += 1
            _decision(ev, "unevaluable", "undefined_participant")
            continue
        if (ev.get("deporte") == "Tennis"
                and any(x in U.normalizar(str(ev.get('torneo',''))+' '+str(ev.get('modalidad',''))).split()
                        for x in ('doubles','dobles','srl','simulated'))):
            _decision(ev, 'discard', 'tennis_unsupported_format')
            continue
        if (ev.get("deporte") == "Tennis"
                and not all((ev.get(lado) or {}).get("ranking") for lado in ("local", "visita"))
                and not any((ev.get(lado) or {}).get("entry") == "WC" and (ev.get(lado) or {}).get("entry_fuente") == "WTA cuadro oficial" for lado in ("local", "visita"))):
            st["sin_datos"] += 1
            _decision(ev, "unevaluable", "tennis_missing_ranking_and_official_wc")
            continue
        if not _tiene_historial_propio(ev):
            if busquedas_por_nombre >= MAX_BUSQUEDAS_POR_NOMBRE:
                omitidos_busqueda += 1
                _decision(ev, "pending", "identity_lookup_budget")
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
            _decision(ev, "pending", "evaluation_error:" + type(exc).__name__)
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
    U.guardar_caches((fuente_api_football, fuente_highlightly, fuente_thesportsdb, fuente_theoddsapi,
                      fuente_openligadb, fuente_espn, fuente_wta, fuente_pwhl, fuente_fivb, fuente_cev, fuente_bbs, fuente_sportscore, fuente_worldrugby, fuente_sportapi, fuente_sportsapi_app, fuente_cricsheet, fuente_balldontlie, fuente_tennis_api, fuente_lvf, fuente_lnv, fuente_tauron))
    ESTADO["presupuestos"] = _resumen_presupuestos()
    ESTADO["http_last_sweep"] = {fuente: dict(codigos) for fuente, codigos in U.ESTADISTICAS.items()}
    ESTADO["barridos"] += 1
    ESTADO["ultimo_barrido_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ESTADO["ultimo_barrido_segundos"] = round(time.monotonic() - t_inicio, 1)
    ESTADO["eventos_unicos"] = len(eventos)
    try:
        modules = {name[7:]: value for name, value in globals().items() if name.startswith('fuente_')}
        resultados.actual().recoger(modules)
        resultados.actual().guardar()
        auditoria.diario().flush()
        ESTADO['ultimo_barrido_segundos'] = round(time.monotonic()-t_inicio,1)
        ESTADO['http_last_sweep'] = {fuente:dict(codigos) for fuente,codigos in U.ESTADISTICAS.items()}
        ESTADO['presupuestos'] = _resumen_presupuestos()
        ESTADO['coverage'] = cobertura.actual.resumen()
        ESTADO['audit'] = auditoria.diario().estado()
        ESTADO['outcome_evaluation'] = resultados.actual().estado()
        ESTADO['data_planner'] = planificador.actual.resumen()
        ESTADO['source_capabilities'] = mapa_fuentes.construir(modules, ESPN_ACTIVO)
        _guardar_cobertura_diaria(ESTADO['coverage'])
    except Exception as exc:
        U.log('[observability] barrido deportivo conservado; ' + type(exc).__name__)
    _imprimir_resumen(resumen)
    _avisar_si_esta_ciego(resumen)


def _guardar_cobertura_diaria(report):
    dias = U.cargar_json('cobertura_diaria_v1.json', {})
    if not isinstance(dias, dict):
        dias = {}
    dia = datetime.now(timezone.utc).date().isoformat()
    row = dias.setdefault(dia, {'sweeps':0, 'sports':{}, 'http_requests':0, 'delivery_counts':{}})
    row['sweeps'] += 1
    row['http_requests'] += planificador.actual.resumen()['http_requests']
    for sport, data in report['sports'].items():
        old = row['sports'].setdefault(sport, {'max_unique_per_sweep':0, 'sources_observed':[], 'evaluations':0})
        old['max_unique_per_sweep'] = max(old['max_unique_per_sweep'], data['unique_events'])
        old['sources_observed'] = sorted(set(old['sources_observed']) | set(data['sources_observed']))
        old['evaluations'] += sum(n for label,n in data['states'].items() if label.startswith(('alert:', 'discard:')))
    for label, n in report['deliveries_by_role'].items():
        row['delivery_counts'][label] = row['delivery_counts'].get(label,0)+n
    U.guardar_json('cobertura_diaria_v1.json', dict(sorted(dias.items())[-35:]))


def _resumen_presupuestos():
    salida = {}
    for modulo in (fuente_api_football, fuente_highlightly):
        for nombre, presupuesto in getattr(modulo, "_presupuestos", {}).items():
            restante = presupuesto.restantes()
            fila = {"fecha_utc": presupuesto.fecha, "usadas": presupuesto.usadas,
                    "limite": presupuesto.limite, "disponibles_bot": restante,
                    "saldo_ultimo_proveedor": presupuesto.saldo_proveedor}
            salida[f"{modulo.FUENTE}:{nombre}"] = fila
            U.log(f"[presupuesto/{modulo.FUENTE}/{nombre}] {fila}")
    for modulo in (fuente_oddspapi, fuente_theoddsapi, fuente_wta):
        if modulo and modulo.disponible():
            salida[modulo.FUENTE] = modulo.presupuesto.resumen_datos()
            U.log(f"[presupuesto/{modulo.FUENTE}] {salida[modulo.FUENTE]}")
    if fuente_pwhl and fuente_pwhl.disponible():
        p = fuente_pwhl.presupuesto
        salida["pwhl"] = {"usadas": p.usadas, "limite": p.limite, "disponibles_bot": p.restantes()}
    for modulo in (fuente_fivb, fuente_cev, fuente_bbs, fuente_sportscore, fuente_worldrugby, fuente_sportapi, fuente_sportsapi_app, fuente_cricsheet, fuente_balldontlie, fuente_tennis_api, fuente_lvf, fuente_lnv, fuente_tauron):
        if modulo and (modulo.disponible() or modulo is fuente_sportsapi_app and bool(modulo.API_KEY)):
            p = modulo.presupuesto
            salida[modulo.FUENTE] = {"usadas": p.usadas, "limite": p.limite, "disponibles_bot": p.restantes(),
                                     "ventana": "24h móvil" if getattr(p, "ventana_horas", None) == 24 else "día UTC",
                                     "saldo_ultimo_proveedor": getattr(p, "saldo_proveedor", None)}
            if modulo is fuente_cricsheet:
                salida[modulo.FUENTE].update(modulo.estado())
            if modulo is fuente_sportapi:
                salida[modulo.FUENTE].update(p.estado_mensual())
            if modulo is fuente_sportsapi_app:
                salida[modulo.FUENTE].update(modulo.estado_contexto())
            if modulo is fuente_tennis_api:
                salida[modulo.FUENTE].update(modulo.estado_contexto())
            if modulo in (fuente_fivb, fuente_cev):
                salida[modulo.FUENTE].update(modulo.estado_contexto())
            if modulo in (fuente_lvf,fuente_lnv,fuente_tauron):
                salida[modulo.FUENTE].update(modulo.estado_contexto())
    return salida


def _fuentes_activas():
    fuentes = []
    for modulo, nombre in ((fuente_tauron, "TAURON Liga Kobiet oficial (Polonia)"), (fuente_lvf, "LVF oficial (contexto Serie A1 femenina)"), (fuente_lnv, "LNV oficial (contexto D1F)"), (fuente_tennis_api, "Tennis API (factual femenino)"), (fuente_fivb, "FIVB/VIS"), (fuente_cev, "CEV"), (fuente_bbs, "Big Balls Sports Data (WNBA)"),
                           (fuente_sportscore, "SportScore"), (fuente_worldrugby, "World Rugby (femenino XV)"), (fuente_sportapi, "SportAPI.ai"), (fuente_sportsapi_app, "SportsAPI.app (multideporte)"),
                           (fuente_cricsheet, "Cricsheet (resultados femeninos)"), (fuente_balldontlie, "BALLDONTLIE (WNBA)")):
        if modulo and modulo.disponible():
            fuentes.append(nombre)
    if fuente_wta and fuente_wta.disponible():
        fuentes.append("WTA oficial (cuadros, WC e historial)")
    if fuente_pwhl and fuente_pwhl.disponible():
        fuentes.append("PWHL oficial")
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
    enviar_telegram(mensajes.inicio(fuentes, DEPORTES_RADAR, INTERVALO_REVISION))
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
