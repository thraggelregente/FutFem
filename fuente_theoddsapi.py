"""The Odds API (https://the-odds-api.com) usada EXCLUSIVAMENTE para fixtures y resultados.

Modo CERO CUOTAS: nunca se llama a /odds ni /historical, no se piden regiones ni mercados y no se
almacena ningÃºn dato de cuotas ni de casas de apuestas. Endpoints usados:
    GET /v4/sports                    -> competiciones activas (se filtran las femeninas)   [sin costo]
    GET /v4/sports/{sport_key}/events -> partidos prÃ³ximos (equipos y horario)              [sin costo]
    GET /v4/sports/{sport_key}/scores?daysFrom=3 -> resultados de los Ãºltimos 3 dÃ­as        [2 crÃ©ditos]
Los resultados alimentan el libro de resultados (historial por nombre y Elo). Como /scores sÃ­ consume
crÃ©ditos, se controla con un presupuesto de tres ventanas (dÃ­a, semana y mes, con el mes repartido en
partes iguales) y con el saldo REAL que informa la API en cada respuesta: si el saldo real baja de
THEODDSAPI_RESERVA_REAL, el radar deja de gastar (la clave puede compartirse con otros proyectos).

QuÃ© aporta: calendario de competiciones femeninas que la casa publica en su catÃ¡logo (WNBA, WNBL,
Champions League femenina, etc., segÃºn lo que estÃ© activo ese dÃ­a). Los equipos no traen ID ni
historial: la forma reciente se resuelve con las demÃ¡s fuentes por nombre.

Clave: variable de entorno ODDS_API_KEY (alias THE_ODDS_API_KEY). Sin clave la fuente se omite.
Opcional: THEODDSAPI_EXTRA_SPORT_KEYS=clave1,clave2 fuerza competiciones verificadas por el operador
que no tengan marca femenina visible en el catÃ¡logo. El tenis queda fuera a propÃ³sito: sin ranking
oficial no hay anÃ¡lisis posible y ESPN es la Ãºnica fuente con ranking WTA.
"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import libro_resultados as L
import utilidades as U

API_KEY = (os.environ.get("ODDS_API_KEY") or os.environ.get("THE_ODDS_API_KEY") or "").strip()
BASE = (os.environ.get("THEODDSAPI_BASE") or "https://api.the-odds-api.com/v4").rstrip("/")
FUENTE = "theoddsapi"
VENTANA_HORAS = max(1, int(os.environ.get("THEODDSAPI_VENTANA_HORAS", "30")))
CACHE_MINUTOS = max(10, int(os.environ.get("THEODDSAPI_CACHE_MINUTOS", "45")))
TTL_FALLO = 5 * 60
# Presupuesto PROPIO del radar para /scores (crÃ©ditos). El plan gratuito da 500/mes; por defecto el
# radar usa como mÃ¡ximo 150 (30%) y reparte el mes en partes iguales (~5 por dÃ­a = ~2 competiciones).
CREDITOS_MES = max(2, int(os.environ.get("THEODDSAPI_CREDITOS_MES", "150")))
COSTO_SCORES = 2  # con daysFrom la documentaciÃ³n indica 2 crÃ©ditos por llamada
RESERVA_REAL = max(0, int(os.environ.get("THEODDSAPI_RESERVA_REAL", "250")))
RESULTADOS_ACTIVOS = os.environ.get("THEODDSAPI_RESULTADOS", "1").strip().lower() not in {"0", "false", "no", "off"}
HORAS_ENTRE_RESULTADOS = max(12, int(os.environ.get("THEODDSAPI_HORAS_ENTRE_RESULTADOS", "20")))
MAX_LLAMADAS_SCORES_POR_BARRIDO = 2
ARCHIVO_SCORES = "theoddsapi_scores.json"

_PREFIJOS_DEPORTE = (
    ("soccer_", "Soccer"),
    ("basketball_", "Basketball"),
    ("icehockey_", "Ice Hockey"),
    ("handball_", "Handball"),
    ("volleyball_", "Volleyball"),
    ("rugbyleague_", "Rugby"),
    ("rugbyunion_", "Rugby"),
)
_GRUPOS_DEPORTE = {
    "soccer": "Soccer",
    "basketball": "Basketball",
    "ice hockey": "Ice Hockey",
    "handball": "Handball",
    "volleyball": "Volleyball",
    "rugby league": "Rugby",
    "rugby union": "Rugby",
}

DEPORTES_ACTIVOS = [
    d.strip() for d in os.environ.get(
        "THEODDSAPI_DEPORTES", "Soccer,Basketball,Ice Hockey,Handball,Volleyball,Rugby"
    ).split(",") if d.strip()
]
_EXTRA = {
    x.strip().lower() for x in re.split(r"[,;\n]+", os.environ.get("THEODDSAPI_EXTRA_SPORT_KEYS", "")) if x.strip()
}

presupuesto = U.PresupuestoMultiple(
    "theoddsapi",
    mensual=CREDITOS_MES,
    semanal=os.environ.get("THEODDSAPI_CREDITOS_SEMANA", "") or None,
    diario=os.environ.get("THEODDSAPI_CREDITOS_DIA", "6"),
    reserva_mensual=0,
)
_real = {"restantes": None}
_cache_catalogo = U.CacheTTL(6 * 3600)
_cache_eventos = U.CacheTTL(CACHE_MINUTOS * 60)
_deshabilitada = {"motivo": ""}
_avisos = set()
_lock = threading.Lock()
_backoff_hasta = {"t": 0.0}
_catalogo_logueado = {"firma": ""}


def disponible():
    return bool(API_KEY) and not _deshabilitada["motivo"] and time.time() >= _backoff_hasta["t"]


def _avisar_una_vez(clave, mensaje):
    if clave not in _avisos:
        _avisos.add(clave)
        U.log(mensaje)


def _ruta_permitida(ruta):
    return (ruta == "/sports"
            or (ruta.startswith("/sports/") and (ruta.endswith("/events") or ruta.endswith("/scores"))))


def _get(ruta, params=None):
    """JSON o None. Solo rutas de catÃ¡logo/resultados; /scores se paga con crÃ©ditos y se mide."""
    if not _ruta_permitida(ruta):
        raise ValueError(f"ruta no permitida en modo CERO CUOTAS: {ruta}")
    if not disponible():
        return None
    es_scores = ruta.endswith("/scores")
    if es_scores:
        if not presupuesto.puede_gastar(COSTO_SCORES):
            return None
        if _real["restantes"] is not None and _real["restantes"] <= RESERVA_REAL:
            _avisar_una_vez(("reserva", time.strftime("%Y-%m")),
                            f"[theoddsapi] resultados pausados: saldo real {_real['restantes']} <= reserva {RESERVA_REAL}")
            return None
    parametros = dict(params or {})
    parametros["apiKey"] = API_KEY
    info = {}
    data = U.get_json(f"{BASE}{ruta}", FUENTE, params=parametros, timeout=15, info=info, reintentar=False)
    status = info.get("status")
    cabeceras = {str(k).lower(): v for k, v in (info.get("headers") or {}).items()}
    try:
        if cabeceras.get("x-requests-remaining") is not None:
            _real["restantes"] = int(float(cabeceras["x-requests-remaining"]))
    except (TypeError, ValueError):
        pass
    if es_scores:
        try:
            costo = int(float(cabeceras.get("x-requests-last", COSTO_SCORES)))
        except (TypeError, ValueError):
            costo = COSTO_SCORES
        presupuesto.registrar(max(1, costo))
        U.log(f"[theoddsapi] scores {ruta}: {presupuesto.resumen()}; saldo real={_real['restantes']}")
    if status == 401:
        _deshabilitada["motivo"] = "HTTP 401: ODDS_API_KEY invÃ¡lida"
        U.log(f"[theoddsapi] DESACTIVADA: {_deshabilitada['motivo']}")
    elif status == 429:
        _backoff_hasta["t"] = time.time() + 30 * 60
        _avisar_una_vez(("429", int(time.time() // 3600)), "[theoddsapi] HTTP 429; fuente pausada 30 minutos")
        if es_scores:
            presupuesto.marcar_agotado("dia")
    elif status == 422:
        _avisar_una_vez(("422", ruta), f"[theoddsapi] HTTP 422 en {ruta}: parÃ¡metros rechazados")
    return data


def _deporte_de(entrada):
    clave = str(entrada.get("key") or "").lower()
    for prefijo, deporte in _PREFIJOS_DEPORTE:
        if clave.startswith(prefijo):
            return deporte
    return _GRUPOS_DEPORTE.get(str(entrada.get("group") or "").strip().lower())


def _es_femenina(entrada):
    clave = str(entrada.get("key") or "").lower()
    if clave in _EXTRA:
        return True
    texto = " ".join((clave.replace("_", " "), str(entrada.get("title") or ""), str(entrada.get("description") or "")))
    return U.es_femenino(texto, "", "")


def _catalogo_femenino():
    """Competiciones femeninas activas: [{key, deporte, titulo}]."""
    hit, valor = _cache_catalogo.get("catalogo")
    if hit:
        return valor
    data = _get("/sports")
    if not isinstance(data, list):
        _cache_catalogo.set("catalogo", [], ttl=TTL_FALLO)
        return []
    competiciones = []
    for entrada in data:
        if not isinstance(entrada, dict) or not entrada.get("key") or entrada.get("active") is False:
            continue
        clave = str(entrada["key"]).lower()
        if clave.endswith("_winner") or "outright" in clave:
            continue  # mercados de campeÃ³n/futuros: no son partidos
        deporte = _deporte_de(entrada)
        if not deporte or not _es_femenina(entrada):
            continue
        competiciones.append({"key": entrada["key"], "deporte": deporte,
                              "titulo": str(entrada.get("title") or entrada["key"])})
    firma = ",".join(sorted(c["key"] for c in competiciones))
    if firma != _catalogo_logueado["firma"]:
        _catalogo_logueado["firma"] = firma
        U.log(f"[theoddsapi] competiciones femeninas activas: {firma or 'ninguna'}")
    _cache_catalogo.set("catalogo", competiciones)
    return competiciones


def _timestamp(valor):
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (TypeError, ValueError, OverflowError):
        return 0


def _eventos_de(competicion):
    clave = competicion["key"]
    hit, valor = _cache_eventos.get(clave)
    if hit:
        return valor
    ahora = datetime.now(timezone.utc)
    params = {
        "dateFormat": "iso",
        "commenceTimeFrom": ahora.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commenceTimeTo": (ahora + timedelta(hours=VENTANA_HORAS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    data = _get(f"/sports/{clave}/events", params)
    if not isinstance(data, list):
        _cache_eventos.set(clave, [], ttl=TTL_FALLO)
        return []
    _cache_eventos.set(clave, data)
    return data


def _normalizar(crudo, competicion, ahora_ts):
    if not isinstance(crudo, dict) or crudo.get("id") is None:
        return None
    local = str(crudo.get("home_team") or "").strip()
    visita = str(crudo.get("away_team") or "").strip()
    ts = _timestamp(crudo.get("commence_time"))
    if not local or not visita or not ts or ts <= ahora_ts or ts > ahora_ts + VENTANA_HORAS * 3600:
        return None
    deporte = competicion["deporte"]
    return {
        "id": f"theoddsapi_{crudo['id']}",
        "clave": U.clave_partido(local, visita, ts),
        "deporte": deporte,
        "torneo": competicion["titulo"],
        "local": {"id": f"toa:{U.firma_equipo(local)}", "nombre": local, "ranking": None, "fuera_ranking": False},
        "visita": {"id": f"toa:{U.firma_equipo(visita)}", "nombre": visita, "ranking": None, "fuera_ranking": False},
        "horario": U.formatear_hora_arg(ts),
        "tipo_estado": "pre",
        "startTimestamp": ts,
        "fuente": FUENTE,
        "femenino_seguro": True,
        "liga_ref": (competicion["key"],),
    }


def obtener_eventos(deporte):
    """Partidos femeninos pre-match de las prÃ³ximas horas para `deporte`. Sin cuotas."""
    if deporte not in DEPORTES_ACTIVOS or not disponible():
        return []
    ahora_ts = time.time()
    por_id = {}
    refrescar_resultados()
    for competicion in _catalogo_femenino():
        if competicion["deporte"] != deporte:
            continue
        for crudo in _eventos_de(competicion):
            evento = _normalizar(crudo, competicion, ahora_ts)
            if evento:
                por_id[evento["id"]] = evento
    if por_id:
        U.log(f"[theoddsapi/{deporte}] {len(por_id)} partidos femeninos capturados (solo fixtures)")
    return list(por_id.values())


# ---------------------------------------------------------------------------
# RESULTADOS (alimentan el libro de resultados)
# ---------------------------------------------------------------------------
def _resultado(crudo):
    """Partido terminado en formato interno, o None."""
    if not isinstance(crudo, dict) or not crudo.get("completed"):
        return None
    local, visita = str(crudo.get("home_team") or "").strip(), str(crudo.get("away_team") or "").strip()
    marcador = {}
    for item in crudo.get("scores") or []:
        try:
            marcador[str(item.get("name") or "").strip()] = int(float(item.get("score")))
        except (AttributeError, TypeError, ValueError):
            continue
    if not local or not visita or local not in marcador or visita not in marcador:
        return None
    ts = _timestamp(crudo.get("commence_time"))
    if not ts:
        return None
    return {"fecha": datetime.fromtimestamp(ts, timezone.utc).isoformat(), "nom_local": local, "nom_visita": visita,
            "puntos_local": marcador[local], "puntos_visita": marcador[visita]}


def refrescar_resultados():
    """
    Pide /scores de las competiciones femeninas con partidos prÃ³ximos, empezando por la que hace mÃ¡s
    tiempo que no se actualiza, siempre dentro del presupuesto. Devuelve cuÃ¡ntos resultados nuevos entraron.
    """
    if not RESULTADOS_ACTIVOS or not disponible():
        return 0
    estado = U.cargar_json(ARCHIVO_SCORES, {})
    estado = estado if isinstance(estado, dict) else {}
    ahora = time.time()
    pendientes = []
    for competicion in _catalogo_femenino():
        if competicion["deporte"] not in DEPORTES_ACTIVOS:
            continue
        ultimo = float(estado.get(competicion["key"], 0) or 0)
        if ahora - ultimo < HORAS_ENTRE_RESULTADOS * 3600:
            continue
        if not _eventos_de(competicion):  # sin partidos prÃ³ximos no vale la pena gastar crÃ©ditos
            continue
        pendientes.append((ultimo, competicion))
    nuevos = 0
    for _ultimo, competicion in sorted(pendientes, key=lambda x: x[0])[:MAX_LLAMADAS_SCORES_POR_BARRIDO]:
        if not presupuesto.puede_gastar(COSTO_SCORES):
            break
        data = _get(f"/sports/{competicion['key']}/scores", {"daysFrom": 3, "dateFormat": "iso"})
        if not isinstance(data, list):
            continue
        partidos = [r for r in (_resultado(x) for x in data) if r]
        nuevos += L.ingestar(competicion["deporte"], partidos, "theoddsapi")
        estado[competicion["key"]] = ahora
        U.guardar_json(ARCHIVO_SCORES, estado)
    return nuevos
