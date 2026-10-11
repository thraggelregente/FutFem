"""OddsPapi V4 como fuente de fixtures deportivos, sin consumir datos de cuotas.

ÃšNICA ruta billable usada por defecto: GET /v4/fixtures. No se consultan ni
almacenan odds, mercados, bookmakers, mÃ¡rgenes o probabilidades implÃ­citas.
AutenticaciÃ³n: apiKey como parÃ¡metro de query (documentaciÃ³n oficial); se envÃ­a
ademÃ¡s X-API-Key como compatibilidad con gateways que lo admiten.

GuardarraÃ­les:
- 6 requests billable/dÃ­a por defecto y 180/mes en contador persistente local.
- Consulta opcional a GET /v4/account (endpoint no medido segÃºn documentaciÃ³n)
  para pausar antes de tocar la cuota real restante.
- Cache de fixtures de 4 h y forma/H2H apagadas por defecto.
- La allowlist ODDSPAPI_WOMENS_TOURNAMENT_IDS acepta torneos sin marca visible de
  gÃ©nero; agregÃ¡ solamente IDs que hayas verificado como femeninos.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone

import libro_resultados as L
import utilidades as U

API_KEY = (os.environ.get("ODDSPAPI_API_KEY") or "").strip()
FUENTE = "oddspapi"
BASE = (os.environ.get("ODDSPAPI_BASE") or "https://api.oddspapi.io/v4").rstrip("/")
HORAS_VENTANA = max(1, int(os.environ.get("ODDSPAPI_VENTANA_HORAS", "24")))
HORAS_PEDIDO = max(HORAS_VENTANA, min(36, int(os.environ.get("ODDSPAPI_HORAS_PEDIDO", "36"))))
CACHE_MINUTOS = max(30, int(os.environ.get("ODDSPAPI_CACHE_MINUTOS", "480")))

_DEPORTES = {
    "soccer": "Soccer", "football": "Soccer",
    "basketball": "Basketball",
    "handball": "Handball",
    "volleyball": "Volleyball",
    "ice hockey": "Ice Hockey", "hockey": "Ice Hockey",
    "tennis": "Tennis", "rugby": "Rugby",
}

DEPORTES_ACTIVOS = [
    d.strip() for d in os.environ.get(
        "ODDSPAPI_DEPORTES", "Soccer,Volleyball,Handball,Basketball,Ice Hockey"
    ).split(",") if d.strip() in set(_DEPORTES.values())
]
PROFUNDIDAD = os.environ.get("ODDSPAPI_PROFUNDIDAD", "0").strip() == "1"
# "Profundidad" eficiente: UN request por dÃ­a trae los resultados de los Ãºltimos 3 dÃ­as de TODOS los
# deportes (statusId=2) y los anota en el libro de resultados. Reemplaza el pedido por equipo
# (PROFUNDIDAD=1), que cuesta 1 request por equipo y es inviable con 180 requests al mes.
HISTORIAL_DIARIO = os.environ.get("ODDSPAPI_HISTORIAL_DIARIO", "1").strip().lower() not in {"0", "false", "no", "off"}
HISTORIAL_HORAS = max(12, int(os.environ.get("ODDSPAPI_HISTORIAL_HORAS", "24")))
HISTORIAL_DIAS_ATRAS = max(1, min(7, int(os.environ.get("ODDSPAPI_HISTORIAL_DIAS", "3"))))
LIMITE_MENSUAL_LOCAL = max(1, int(os.environ.get("ODDSPAPI_MONTHLY_LIMIT", "180")))
RESERVA_CUOTA_REAL = max(0, int(os.environ.get("ODDSPAPI_RESERVA_CUOTA_REAL", "25")))
CONTROL_CUOTA_REAL = os.environ.get("ODDSPAPI_CONTROL_CUOTA_REAL", "1").strip().lower() not in {"0", "false", "no", "off"}
CACHE_CUOTA_REAL_SEGUNDOS = max(3600, int(os.environ.get("ODDSPAPI_CUOTA_REAL_CACHE_HORAS", "6")) * 3600)

# Plan por defecto: 3 listados de fixtures por dÃ­a (cada 8 h) + 1 feed de resultados = ~4/dÃ­a = ~120 al
# mes, dentro del tope propio de 180 y con 20 de reserva para reinicios/deploys. El presupuesto exige
# ademÃ¡s tope semanal y reparte el mes en partes iguales: nunca se gasta el mes en pocos dÃ­as.
presupuesto = U.PresupuestoMultiple(
    "oddspapi",
    mensual=LIMITE_MENSUAL_LOCAL,
    semanal=os.environ.get("ODDSPAPI_WEEKLY_LIMIT", "35"),
    diario=os.environ.get("ODDSPAPI_DAILY_LIMIT", "6"),
    reserva_mensual=os.environ.get("ODDSPAPI_RESERVA_MENSUAL", "20"),
)
_cache_eventos = U.CacheTTL(CACHE_MINUTOS * 60)
_cache_participante = U.CacheTTL(6 * 3600)
_deshabilitada = {"motivo": ""}
_avisos = set()
_lock = threading.RLock()
_cuota_real = {"consultada_en": 0.0, "restantes": None, "limite": None, "usadas": None}
_backoff_hasta = 0.0


def _avisar_una_vez(clave, mensaje):
    if clave not in _avisos:
        _avisos.add(clave)
        U.log(mensaje)


def disponible():
    return bool(API_KEY) and not _deshabilitada["motivo"] and time.time() >= _backoff_hasta


def _headers():
    # La documentaciÃ³n V4 usa apiKey en query. El header extra no reemplaza ese parÃ¡metro.
    return {"Accept": "application/json", "X-API-Key": API_KEY}


def _mes_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _cuota_real_restante(forzar=False):
    """Lee /account, endpoint que la documentaciÃ³n marca como no medido."""
    if not CONTROL_CUOTA_REAL or not API_KEY:
        return None
    ahora = time.time()
    with _lock:
        if not forzar and ahora - _cuota_real["consultada_en"] < CACHE_CUOTA_REAL_SEGUNDOS:
            return _cuota_real["restantes"]
        info = {}
        data = U.get_json(
            f"{BASE}/account", FUENTE, headers=_headers(), params={"apiKey": API_KEY}, timeout=12, info=info
        )
        restantes = limite = usadas = None
        if isinstance(data, dict):
            subs = data.get("subscriptions") or []
            if isinstance(subs, list) and subs:
                activas = [s for s in subs if isinstance(s, dict) and s.get("is_active")]
                opciones = activas or [s for s in subs if isinstance(s, dict)]
                preferida = max(opciones, key=lambda s: int(s.get("request_limit") or 0), default={})
                try:
                    limite = int(preferida.get("request_limit"))
                    usadas = int(preferida.get("request_count"))
                    restantes = max(0, limite - usadas)
                except (TypeError, ValueError):
                    restantes = limite = usadas = None
        _cuota_real.update({
            "consultada_en": ahora,
            "restantes": restantes,
            "limite": limite,
            "usadas": usadas,
        })
        if restantes is not None:
            U.log(f"[oddspapi] cuota real reportada por /account: {usadas}/{limite}; restantes={restantes}")
        elif info.get("status") in (401, 403):
            _deshabilitada["motivo"] = f"HTTP {info['status']} en /account: verificar ODDSPAPI_API_KEY"
            U.log(f"[oddspapi] DESACTIVADA: {_deshabilitada['motivo']}")
        return restantes


def _cuota_real_ok():
    """False si /account informa que quedan menos requests que la reserva real."""
    restante_real = _cuota_real_restante()
    if restante_real is not None and restante_real <= RESERVA_CUOTA_REAL:
        _avisar_una_vez(
            ("reserva-real", _mes_utc()),
            f"[oddspapi] pausada para proteger la cuota real: quedan {restante_real} requests y la reserva es {RESERVA_CUOTA_REAL}",
        )
        return False
    return True


def _get(ruta, params=None, exigir=1):
    """
    Pide datos de fixtures y contabiliza solo endpoints billables. `exigir` = cupo que debe quedar
    disponible HOY (diario, semanal y ritmo mensual) para hacer el pedido: los pedidos opcionales
    exigen mÃ¡s para no quitarle cupo al listado de fixtures, que tiene prioridad.
    """
    global _backoff_hasta
    if not disponible():
        return None
    es_account = ruta.rstrip("/") == "/account"
    if not es_account:
        if not presupuesto.puede_gastar(exigir):
            _avisar_una_vez(
                ("cupo", presupuesto.claves["dia"], exigir),
                f"[oddspapi] sin cupo para este pedido ({presupuesto.resumen()}); se reanuda cuando el ritmo lo permita",
            )
            return None
        if not _cuota_real_ok():
            return None

    parametros = dict(params or {})
    parametros["apiKey"] = API_KEY
    info = {}
    data = U.get_json(f"{BASE}{ruta}", FUENTE, headers=_headers(), params=parametros, timeout=20, info=info)
    status = info.get("status")
    if not es_account and status is not None:
        presupuesto.registrar(1)
        U.log(f"[oddspapi] request {ruta} registrado: {presupuesto.resumen()}")
    if status == 429:
        presupuesto.marcar_agotado("dia")
        _backoff_hasta = time.time() + 6 * 3600
        _avisar_una_vez(("429", presupuesto.claves["dia"]), "[oddspapi] HTTP 429; fuente pausada por 6 h para proteger la cuota")
    elif status in (401, 403):
        _deshabilitada["motivo"] = f"HTTP {status}: clave invÃ¡lida o sin permiso"
        U.log(f"[oddspapi] DESACTIVADA: {_deshabilitada['motivo']}")
    return data


def _normalizar_deporte(valor):
    return _DEPORTES.get(str(valor or "").strip().lower())


def _deporte_de(fixture):
    sport = fixture.get("sport") if isinstance(fixture.get("sport"), dict) else {}
    nombre = sport.get("sportName") or fixture.get("sportName")
    deporte = _normalizar_deporte(nombre)
    if deporte:
        return deporte
    sport_id = sport.get("sportId", fixture.get("sportId"))
    # IDs documentados/usados con frecuencia; no se asume gÃ©nero a partir del ID.
    try:
        return {10: "Soccer", 11: "Basketball", 12: "Tennis", 13: "Handball", 14: "Volleyball", 15: "Ice Hockey", 16: "Rugby"}.get(int(sport_id))
    except (TypeError, ValueError):
        return None


def _timestamp(valor):
    if isinstance(valor, (int, float)):
        return int(valor)
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (TypeError, ValueError, OverflowError):
        return 0


def _normalizar(fixture):
    try:
        if not isinstance(fixture, dict) or fixture.get("fixtureId") is None:
            return None
        participants = fixture.get("participants") if isinstance(fixture.get("participants"), dict) else {}
        id1 = participants.get("participant1Id", fixture.get("participant1Id"))
        id2 = participants.get("participant2Id", fixture.get("participant2Id"))
        name1 = participants.get("participant1Name") or fixture.get("participant1Name")
        name2 = participants.get("participant2Name") or fixture.get("participant2Name")
        if id1 is None or id2 is None or not name1 or not name2:
            return None
        status = fixture.get("status") if isinstance(fixture.get("status"), dict) else {}
        status_id = status.get("statusId", fixture.get("statusId"))
        if status_id is None:
            raw_status = str(status.get("statusName") or fixture.get("statusName") or "").strip().lower()
            if raw_status in {"pre-game", "pregame", "not started", "scheduled"}:
                status_id = 0
            elif "finish" in raw_status or "ended" in raw_status or "full time" in raw_status:
                status_id = 2
            elif "cancel" in raw_status:
                status_id = 3
        tournament = fixture.get("tournament") if isinstance(fixture.get("tournament"), dict) else {}
        result = (fixture.get("scores") or {}).get("result") or {}
        tournament_id = tournament.get("tournamentId", fixture.get("tournamentId"))
        return {
            "id": str(fixture["fixtureId"]),
            "ts": _timestamp(fixture.get("startTime")),
            "estado": int(status_id) if status_id is not None else None,
            "deporte": _deporte_de(fixture),
            "torneo_id": str(tournament_id or ""),
            "torneo": tournament.get("tournamentName") or fixture.get("tournamentName") or "",
            "pais": tournament.get("categoryName") or fixture.get("categoryName") or "",
            "id_local": str(id1), "nom_local": str(name1),
            "id_visita": str(id2), "nom_visita": str(name2),
            "pl": result.get("participant1Score"), "pv": result.get("participant2Score"),
        }
    except (TypeError, ValueError, AttributeError):
        return None


def _como_historico(partido):
    try:
        ts = int(partido.get("ts") or 0)
        fecha = datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else ""
    except (TypeError, ValueError, OverflowError):
        fecha = ""
    return {
        "fecha": fecha,
        "id_local": partido["id_local"], "nom_local": partido["nom_local"],
        "id_visita": partido["id_visita"], "nom_visita": partido["nom_visita"],
        "puntos_local": partido.get("pl"), "puntos_visita": partido.get("pv"),
    }


ARCHIVO_VENTANA = "oddspapi_ventana.json"
ARCHIVO_HISTORIAL = "oddspapi_historial.json"


def _cargar_ventana_persistida():
    """Tras un reinicio/deploy reutiliza el Ãºltimo listado si todavÃ­a es fresco (no repite el pedido)."""
    crudo = U.cargar_json(ARCHIVO_VENTANA, {})
    try:
        edad = time.time() - float(crudo.get("ts", 0))
        items = crudo.get("items")
    except (AttributeError, TypeError, ValueError):
        return None
    if isinstance(items, list) and 0 <= edad < CACHE_MINUTOS * 60:
        _cache_eventos.set("ventana", items, ttl=CACHE_MINUTOS * 60 - edad)
        U.log(f"[oddspapi] listado reutilizado tras el reinicio ({len(items)} fixtures, {int(edad / 60)} min de antigÃ¼edad)")
        return items
    return None


def _fixtures_ventana():
    hit, valor = _cache_eventos.get("ventana")
    if hit:
        return valor
    persistido = _cargar_ventana_persistida()
    if persistido is not None:
        return persistido
    ahora = datetime.now(timezone.utc)
    hasta = ahora + timedelta(hours=HORAS_PEDIDO)
    parametros = {
        "from": ahora.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": hasta.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "statusId": 0,
    }
    # No agregar hasOdds, bookmakers ni consultar endpoints de odds/markets.
    data = _get("/fixtures", parametros)
    if not isinstance(data, list):
        # Enfriamiento: sin esto cada deporte del mismo barrido repetirÃ­a el pedido fallido y gastarÃ­a cupo.
        _cache_eventos.set("ventana", [], ttl=30 * 60)
        return []
    items = [p for p in (_normalizar(f) for f in data) if p]
    if data and not items:
        _avisar_una_vez("normalizacion", f"[oddspapi] la API devolviÃ³ {len(data)} fixtures, pero ninguno se pudo normalizar")
    U.log(f"[oddspapi] {len(items)} fixtures recibidos; se filtran por gÃ©nero, deporte y ventana")
    # Se persisten solo los femeninos pre-match: alcanza para el radar y mantiene el archivo chico.
    utiles = [p for p in items if p["estado"] == 0 and _torneo_femenino(p)]
    U.guardar_json(ARCHIVO_VENTANA, {"ts": time.time(), "items": utiles})
    _cache_eventos.set("ventana", utiles)
    return utiles


def _torneo_femenino(partido):
    raw = (os.environ.get("ODDSPAPI_WOMENS_TOURNAMENT_IDS") or "").strip()
    autorizados = {x.strip() for x in raw.replace(";", ",").split(",") if x.strip().isdigit()}
    if partido.get("torneo_id") and partido["torneo_id"] in autorizados:
        return True
    return U.es_femenino(partido.get("torneo", ""), partido.get("nom_local", ""), partido.get("nom_visita", ""))


def _terminados_recientes():
    """
    Un Ãºnico request cada HISTORIAL_HORAS: resultados terminados de los Ãºltimos dÃ­as de todos los deportes.
    Solo se anotan los femeninos en el libro de resultados (historial por nombre y Elo). Se ejecuta
    despuÃ©s del listado de fixtures y solo si queda cupo para ambos.
    """
    if not HISTORIAL_DIARIO or not disponible():
        return 0
    estado = U.cargar_json(ARCHIVO_HISTORIAL, {})
    estado = estado if isinstance(estado, dict) else {}
    ahora = time.time()
    if ahora - float(estado.get("ultimo", 0) or 0) < HISTORIAL_HORAS * 3600:
        return 0
    if ahora - float(estado.get("intento", 0) or 0) < 3 * 3600:
        return 0  # un intento fallido no se repite en cada barrido
    if not presupuesto.puede_gastar(2):  # deja siempre 1 pedido para el listado de fixtures
        return 0
    desde = datetime.now(timezone.utc) - timedelta(days=HISTORIAL_DIAS_ATRAS)
    estado["intento"] = ahora
    U.guardar_json(ARCHIVO_HISTORIAL, estado)
    data = _get("/fixtures", {
        "from": desde.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "statusId": 2,
    }, exigir=2)
    if not isinstance(data, list):
        return 0
    por_deporte = {}
    for raw in data:
        partido = _normalizar(raw)
        if (not partido or partido["estado"] != 2 or partido["pl"] is None or partido["pv"] is None
                or partido["deporte"] not in DEPORTES_ACTIVOS or not _torneo_femenino(partido)):
            continue
        por_deporte.setdefault(partido["deporte"], []).append(_como_historico(partido))
    nuevos = sum(L.ingestar(dep, lista, "oddspapi") for dep, lista in por_deporte.items())
    estado["ultimo"] = ahora
    U.guardar_json(ARCHIVO_HISTORIAL, estado)
    U.log(f"[oddspapi] feed de terminados: {len(data)} fixtures, {nuevos} resultados femeninos nuevos en el libro")
    return nuevos


def obtener_eventos(deporte):
    """Devuelve solo fixtures pre-match femeninos de las prÃ³ximas 24 h."""
    if deporte not in DEPORTES_ACTIVOS or not disponible():
        return []
    ahora = datetime.now(timezone.utc).timestamp()
    eventos = []
    ventana = _fixtures_ventana()
    _terminados_recientes()
    for partido in ventana:
        if partido["deporte"] != deporte or partido["estado"] != 0:
            continue
        ts = partido["ts"]
        if not ts or ts <= ahora or ts > ahora + HORAS_VENTANA * 3600:
            continue
        if not _torneo_femenino(partido):
            continue
        torneo = f"{partido['torneo']} ({partido['pais']})" if partido["pais"] else partido["torneo"]
        eventos.append({
            "id": f"oddspapi_{deporte}_{partido['id']}",
            "clave": U.clave_partido(partido["nom_local"], partido["nom_visita"], ts),
            "deporte": deporte,
            "torneo": torneo,
            "local": {"id": partido["id_local"], "nombre": partido["nom_local"], "ranking": None, "fuera_ranking": False},
            "visita": {"id": partido["id_visita"], "nombre": partido["nom_visita"], "ranking": None, "fuera_ranking": False},
            "horario": U.formatear_hora_arg(ts),
            "tipo_estado": "pre",
            "startTimestamp": ts,
            "fuente": FUENTE,
            "femenino_seguro": True,
            "liga_ref": (partido.get("torneo_id"),),
        })
    return eventos


def _terminados_del_participante(participante_id):
    if not PROFUNDIDAD or not disponible() or not participante_id:
        return None
    hit, valor = _cache_participante.get(str(participante_id))
    if hit:
        return valor
    data = _get("/fixtures", {"participantId": participante_id}, exigir=3)
    if not isinstance(data, list):
        return None
    partidos = []
    for raw in data:
        partido = _normalizar(raw)
        if not partido or partido["estado"] != 2 or partido["pl"] is None or partido["pv"] is None:
            continue
        if not _torneo_femenino(partido):
            continue
        partidos.append(partido)
    partidos.sort(key=lambda p: p["ts"], reverse=True)
    _cache_participante.set(str(participante_id), partidos)
    return partidos


def historial_equipo(evento, lado):
    if evento.get("fuente") != FUENTE:
        return []
    equipo = evento.get(lado) or {}
    partidos = _terminados_del_participante(equipo.get("id")) or []
    return [_como_historico(partido) for partido in partidos[:8]]


def obtener_h2h(evento):
    if evento.get("fuente") != FUENTE:
        return []
    local = (evento.get("local") or {}).get("id")
    visita = (evento.get("visita") or {}).get("id")
    partidos = _terminados_del_participante(local) or []
    return [
        _como_historico(p) for p in partidos
        if str(visita) in (str(p["id_local"]), str(p["id_visita"]))
    ]