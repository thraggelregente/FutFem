"""
fuente_oddspapi.py
OddsPapi (https://oddspapi.io/): fuente de EVENTOS (fixtures) femeninos y, opcionalmente, de forma y H2H.

OddsPapi es una API orientada a cuotas: da el calendario (equipos, hora, torneo, estado) y, en los partidos
terminados, el marcador final (scores.result). NO tiene endpoints de H2H ni de tabla de posiciones; por eso:
- Eventos: 1 solo pedido a /fixtures (sin sportId, ventana de 36 h) trae todos los deportes; se filtran los
  deportes de equipo y los torneos/equipos femeninos con el filtro compartido. Cache de 6 h.
- Forma y H2H (opcionales, ODDSPAPI_PROFUNDIDAD=1): salen de los fixtures de cada participante
  (/fixtures?participantId=) y solo para eventos que vienen de OddsPapi, porque ahí ya se conocen los ids.
  Cuesta 1 request por equipo (cache 6 h) y el plan Free tiene ~250 requests por mes: viene apagado.

Cuota: presupuesto diario persistente (ODDSPAPI_DAILY_LIMIT, por defecto 8, unos 240 por mes). Los eventos
tienen prioridad: forma / H2H solo se piden si quedan más de ODDSPAPI_RESERVA_EVENTOS requests en el día.

Autenticación: header X-API-Key con ODDSPAPI_API_KEY. Base configurable con ODDSPAPI_BASE.
"""

import os
from datetime import datetime, timedelta, timezone

import utilidades as U

API_KEY = os.environ.get("ODDSPAPI_API_KEY")
FUENTE = "oddspapi"
BASE = (os.environ.get("ODDSPAPI_BASE") or "https://api.oddspapi.io/v4").rstrip("/")
HORAS_VENTANA = 24
HORAS_PEDIDO = 36

_DEPORTES = {
    "soccer": "Soccer", "football": "Soccer",
    "basketball": "Basketball",
    "handball": "Handball",
    "volleyball": "Volleyball",
    "ice hockey": "Ice Hockey", "hockey": "Ice Hockey",
}
_SPORT_ID_CONOCIDOS = {10: "Soccer", 11: "Basketball", 15: "Ice Hockey"}

DEPORTES_ACTIVOS = [
    d.strip() for d in os.environ.get(
        "ODDSPAPI_DEPORTES", "Soccer,Volleyball,Handball,Basketball,Ice Hockey"
    ).split(",") if d.strip() in set(_DEPORTES.values())
]
PROFUNDIDAD = os.environ.get("ODDSPAPI_PROFUNDIDAD", "0") == "1"
RESERVA_EVENTOS = int(os.environ.get("ODDSPAPI_RESERVA_EVENTOS", "4"))

presupuesto = U.PresupuestoDiario(
    "oddspapi", limite=os.environ.get("ODDSPAPI_DAILY_LIMIT", "8"),
    reserva=os.environ.get("ODDSPAPI_RESERVA", "0"),
)

_cache_eventos = U.CacheTTL(6 * 3600)
_cache_participante = U.CacheTTL(6 * 3600)
_deshabilitada = {"motivo": ""}
_avisos = set()
_sports = {"mapa": None}


def _avisar_una_vez(clave, mensaje):
    if clave not in _avisos:
        _avisos.add(clave)
        U.log(mensaje)


def disponible():
    return bool(API_KEY) and not _deshabilitada["motivo"]


def _headers():
    return {"Accept": "application/json"}


def _get(ruta, params=None):
    """Devuelve el JSON o None si no se pudo (sin cuota, error, clave)."""
    if not disponible():
        return None
    if not presupuesto.puede_gastar(1):
        _avisar_una_vez(("presupuesto", presupuesto.fecha),
                        f"[oddspapi] presupuesto diario agotado ({presupuesto.usadas}/{presupuesto.limite}); "
                        "se reanuda mañana (UTC)")
        return None
    info = {}
    params = dict(params or {})
    params["apiKey"] = API_KEY  # <-- La key va como query parameter
    data = U.get_json(f"{BASE}{ruta}", FUENTE, headers=_headers(), params=params, timeout=30, info=info)
    if info.get("status") is not None:
        presupuesto.registrar(1)
    status = info.get("status")
    if status == 429:
        presupuesto.marcar_agotado()
        _avisar_una_vez(("limite", presupuesto.fecha), "[oddspapi] límite alcanzado (HTTP 429)")
    elif status in (401, 403):
        _deshabilitada["motivo"] = f"HTTP {status}: clave inválida o sin permiso"
        U.log(f"[oddspapi] DESACTIVADA: {_deshabilitada['motivo']}")
    return data


# ---------------------------------------------------------------------------
# NORMALIZACIÓN (acepta la forma anidada de la API actual y la plana de versiones anteriores)
# ---------------------------------------------------------------------------
def _mapa_sports():
    """sportId -> deporte interno. Los ids no conocidos se piden una sola vez a /sports y se guardan."""
    if _sports["mapa"] is not None:
        return _sports["mapa"]
    mapa = dict(_SPORT_ID_CONOCIDOS)
    guardado = U.cargar_json("oddspapi_sports.json", {})
    if isinstance(guardado, dict) and guardado:
        mapa.update({int(k): v for k, v in guardado.items() if str(k).isdigit()})
    else:
        data = _get("/sports")
        if isinstance(data, list):
            extra = {}
            for s in data:
                interno = _DEPORTES.get(str(s.get("slug") or s.get("sportName") or s.get("name") or "").lower())
                if interno and s.get("sportId") is not None:
                    extra[int(s["sportId"])] = interno
            if extra:
                U.guardar_json("oddspapi_sports.json", {str(k): v for k, v in extra.items()})
                mapa.update(extra)
    _sports["mapa"] = mapa
    return mapa


def _deporte_de(f):
    sport = f.get("sport") or {}
    nombre = str(sport.get("sportName") or f.get("sportName") or "").lower()
    if nombre in _DEPORTES:
        return _DEPORTES[nombre]
    sid = sport.get("sportId", f.get("sportId"))
    try:
        return _mapa_sports().get(int(sid))
    except (TypeError, ValueError):
        return None


def _ts(valor):
    if isinstance(valor, (int, float)):
        return int(valor)
    try:
        f = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if f.tzinfo is None:
            f = f.replace(tzinfo=timezone.utc)
        return int(f.timestamp())
    except Exception:
        return 0


def _normalizar(f):
    try:
        if not isinstance(f, dict) or f.get("fixtureId") is None:
            return None
        p = f.get("participants") or {}
        id1, id2 = p.get("participant1Id", f.get("participant1Id")), p.get("participant2Id", f.get("participant2Id"))
        n1 = p.get("participant1Name") or f.get("participant1Name")
        n2 = p.get("participant2Name") or f.get("participant2Name")
        if id1 is None or id2 is None or not n1 or not n2:
            return None
        st = f.get("status") if isinstance(f.get("status"), dict) else {}
        estado_id = st.get("statusId")
        if estado_id is None:
            nombre = str(f.get("statusName") or "").lower()
            estado_id = 0 if nombre in ("pre-game", "pregame", "not started") else (2 if "finish" in nombre else None)
        torneo = f.get("tournament") if isinstance(f.get("tournament"), dict) else {}
        res = (f.get("scores") or {}).get("result") or {}
        ts = _ts(f.get("startTime"))
        return {
            "id": str(f["fixtureId"]), "ts": ts, "estado": estado_id,
            "deporte": _deporte_de(f),
            "torneo": torneo.get("tournamentName") or f.get("tournamentName") or "",
            "pais": torneo.get("categoryName") or f.get("categoryName") or "",
            "id_local": str(id1), "nom_local": n1, "id_visita": str(id2), "nom_visita": n2,
            "pl": res.get("participant1Score"), "pv": res.get("participant2Score"),
        }
    except Exception:
        return None


def _como_historico(n):
    return {
        "fecha": datetime.fromtimestamp(n["ts"], timezone.utc).isoformat() if n["ts"] else "",
        "id_local": n["id_local"], "nom_local": n["nom_local"],
        "id_visita": n["id_visita"], "nom_visita": n["nom_visita"],
        "puntos_local": n["pl"], "puntos_visita": n["pv"],
    }


# ---------------------------------------------------------------------------
# EVENTOS (próximas 24 h)
# ---------------------------------------------------------------------------
def _fixtures_ventana():
    hit, valor = _cache_eventos.get("ventana")
    if hit:
        return valor
    ahora = datetime.now(timezone.utc)
    hasta = ahora + timedelta(hours=HORAS_PEDIDO)
    data = _get("/fixtures", {
        "from": ahora.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": hasta.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "startTimeFrom": int(ahora.timestamp()), "startTimeTo": int(hasta.timestamp()),
        "statusId": 0,
    })
    if not isinstance(data, list):
        return []  # no se cachea el fallo: se reintenta en el próximo barrido
    items = [n for n in (_normalizar(f) for f in data) if n]
    if data and not items:
        _avisar_una_vez("forma", f"[oddspapi] llegaron {len(data)} fixtures pero ninguno con la forma esperada")
    U.log(f"[oddspapi] {len(items)} fixtures en las próximas {HORAS_PEDIDO} h")
    _cache_eventos.set("ventana", items)
    return items


def obtener_eventos(deporte):
    """Partidos FEMENINOS de las próximas 24 h (por nombre de torneo/equipos)."""
    if deporte not in DEPORTES_ACTIVOS or not disponible():
        return []
    t0 = datetime.now(timezone.utc).timestamp()
    eventos = []
    for n in _fixtures_ventana():
        if n["deporte"] != deporte or n["estado"] != 0:
            continue
        if not n["ts"] or n["ts"] < t0 or n["ts"] > t0 + HORAS_VENTANA * 3600:
            continue
        if not U.es_femenino(n["torneo"], n["nom_local"], n["nom_visita"]):
            continue
        torneo = f"{n['torneo']} ({n['pais']})" if n["pais"] else n["torneo"]
        eventos.append({
            "id": f"oddspapi_{deporte}_{n['id']}",
            "clave": U.clave_partido(n["nom_local"], n["nom_visita"], n["ts"]),
            "deporte": deporte,
            "torneo": torneo,
            "local": {"id": n["id_local"], "nombre": n["nom_local"], "ranking": None, "fuera_ranking": False},
            "visita": {"id": n["id_visita"], "nombre": n["nom_visita"], "ranking": None, "fuera_ranking": False},
            "horario": U.formatear_hora_arg(n["ts"]),
            "tipo_estado": "pre",
            "startTimestamp": n["ts"],
            "fuente": FUENTE,
            "femenino_seguro": True,
        })
    return eventos


# ---------------------------------------------------------------------------
# FORMA Y H2H (opcional, 1 request por equipo)
# ---------------------------------------------------------------------------
def _terminados_del_participante(participante_id):
    """Partidos terminados con marcador de un participante (más reciente primero), o None si no se pudo."""
    if not PROFUNDIDAD or not disponible():
        return None
    hit, valor = _cache_participante.get(str(participante_id))
    if hit:
        return valor
    if presupuesto.restantes() <= RESERVA_EVENTOS:
        return None  # lo que queda se reserva para los eventos; no se cachea
    data = _get("/fixtures", {"participantId": participante_id})
    if not isinstance(data, list):
        return None
    partidos = []
    for n in (_normalizar(f) for f in data):
        if n and n["estado"] == 2 and n["pl"] is not None and n["pv"] is not None:
            partidos.append(n)
    partidos.sort(key=lambda n: n["ts"], reverse=True)
    _cache_participante.set(str(participante_id), partidos)
    return partidos


def historial_equipo(evento, lado):
    """Forma del equipo; solo para eventos que ya vienen de OddsPapi (ids de OddsPapi)."""
    if evento.get("fuente") != FUENTE:
        return []
    pid = (evento.get(lado) or {}).get("id")
    partidos = _terminados_del_participante(pid) if pid else None
    return [_como_historico(n) for n in (partidos or [])[:8]]


def obtener_h2h(evento):
    """H2H entre local y visita de un evento de OddsPapi, o [] (apagado, sin cuota o sin cruces)."""
    if evento.get("fuente") != FUENTE:
        return []
    id_loc, id_vis = evento["local"]["id"], evento["visita"]["id"]
    partidos = _terminados_del_participante(id_loc)
    if not partidos:
        return []
    return [_como_historico(n) for n in partidos if id_vis in (n["id_local"], n["id_visita"])]

