"""
fuente_api_football.py
API-Sports (https://www.api-sports.io/): fuente SECUNDARIA, con cuota (Free = 100 requests/día
COMPARTIDOS entre todos los deportes). ESPN es la principal; esta suma deportes y ligas que ESPN
no cubre (handball, vóley, rugby, más fútbol).

Por defecto consulta SOLO Soccer y pide el historial de como máximo 2 ligas por deporte y por día
(API_SPORTS_DEPORTES y API_SPORTS_MAX_LIGAS lo ajustan).

Cómo cuida la cuota (antes gastaba más de 100 requests en el primer barrido):
- 1 pedido por deporte y fecha para listar partidos (/fixtures?date= o /games?date=), cache 8 h.
- 1 pedido por liga (y temporada) para traer TODA la temporada y armar el historial de todos sus
  equipos, cache 6 h. Antes eran 3 pedidos por partido (h2h + forma local + forma visita).
- Presupuesto diario persistente con reserva: si no alcanza, no pide y lo loguea.

Detecta lo que la API devuelve con HTTP 200 pero con error en el cuerpo ("errors": {...}):
límite diario agotado y "plan Free sin acceso a esta temporada". Antes ambos pasaban como
"respuesta vacía" y el radar quedaba mudo sin avisar.

Football usa /fixtures (fixture/goals); el resto de los deportes usa /games (scores). Esta versión
entiende los dos formatos. Los formatos de basketball/handball/hockey/volleyball/rugby los
escribí de la documentación pública, sin poder probarlos con tu clave: el primer barrido loguea
cualquier forma inesperada.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import utilidades as U

API_KEY = os.environ.get("API_FOOTBALL_KEY")
FUENTE = "api_sports"
HORAS_VENTANA = 24

_HOSTS = {
    "Soccer": "v3.football.api-sports.io",
    "Basketball": "v1.basketball.api-sports.io",
    "Handball": "v1.handball.api-sports.io",
    "Ice Hockey": "v1.hockey.api-sports.io",
    "Volleyball": "v1.volleyball.api-sports.io",
    "Rugby": "v1.rugby.api-sports.io",
}

# Deportes a consultar (cada uno cuesta ~2 requests por refresco de 8 h). Configurable.
DEPORTES_ACTIVOS = [
    d.strip() for d in os.environ.get("API_SPORTS_DEPORTES", "Soccer").split(",")
    if d.strip() in _HOSTS
]
MAX_LIGAS_POR_DEPORTE = int(os.environ.get("API_SPORTS_MAX_LIGAS", "2"))

_FINALIZADOS = {"FT", "AET", "PEN", "AOT", "AP", "FIN", "FINISHED", "AW"}
_PROGRAMADOS = {"NS", "TBD", "SCH", "SCHEDULED"}
_NO_JUGADOS = {"PST", "CANC", "SUSP", "ABD", "AWD", "WO", "INT"}

presupuesto = U.PresupuestoDiario(
    "api_sports", limite=os.environ.get("API_FOOTBALL_DAILY_LIMIT", "100"),
    reserva=os.environ.get("API_FOOTBALL_RESERVA", "8"),
)

_cache_eventos = U.CacheTTL(8 * 3600)
_cache_temporada = U.CacheTTL(6 * 3600)
_deshabilitada = {"motivo": ""}
_avisos = set()


def _avisar_una_vez(clave, mensaje):
    if clave not in _avisos:
        _avisos.add(clave)
        U.log(mensaje)


def disponible():
    return bool(API_KEY) and not _deshabilitada["motivo"]


# ---------------------------------------------------------------------------
# HTTP con presupuesto y detección de errores en el cuerpo
# ---------------------------------------------------------------------------
def _errores_del_cuerpo(data):
    err = data.get("errors") if isinstance(data, dict) else None
    if not err:
        return ""
    if isinstance(err, dict):
        return "; ".join(f"{k}: {v}" for k, v in err.items())
    if isinstance(err, list):
        return "; ".join(str(x) for x in err)
    return str(err)


def _get(deporte, ruta, params):
    """Devuelve la lista 'response' o None si no se pudo (sin cuota, error, plan)."""
    if not disponible():
        return None
    host = _HOSTS[deporte]
    if not presupuesto.puede_gastar(1):
        _avisar_una_vez(("presupuesto", presupuesto.fecha),
                        f"[api_sports] presupuesto diario agotado ({presupuesto.usadas}/{presupuesto.limite}); "
                        "se reanuda mañana (UTC)")
        return None

    info = {}
    data = U.get_json(f"https://{host}{ruta}", f"{FUENTE}_{deporte}",
                      headers={"x-apisports-key": API_KEY}, params=params, timeout=15, info=info)
    h = {k.lower(): v for k, v in (info.get("headers") or {}).items()}
    presupuesto.registrar(1, restantes_reales=h.get("x-ratelimit-requests-remaining"))
    if h.get("x-ratelimit-requests-remaining") is not None:
        U.log(f"[api_sports] requests restantes hoy: {h['x-ratelimit-requests-remaining']}")

    if data is None:
        status = info.get("status")
        if status in (401, 403):
            _deshabilitada["motivo"] = f"HTTP {status}: clave inválida o sin permiso"
            U.log(f"[api_sports] DESACTIVADA: {_deshabilitada['motivo']}")
        return None

    error = _errores_del_cuerpo(data)
    if error:
        bajo = error.lower()
        if "request" in bajo and ("limit" in bajo or "reached" in bajo):
            presupuesto.marcar_agotado()
            _avisar_una_vez(("limite", presupuesto.fecha), f"[api_sports] límite diario alcanzado: {error}")
        elif "plan" in bajo or "season" in bajo or "access" in bajo:
            _avisar_una_vez(("plan", ruta), f"[api_sports] tu plan no permite este pedido ({ruta}): {error}")
        elif "token" in bajo or "key" in bajo or "subscription" in bajo:
            _deshabilitada["motivo"] = error
            U.log(f"[api_sports] DESACTIVADA: {error}")
        else:
            _avisar_una_vez(("err", error), f"[api_sports] error en {ruta}: {error}")
        return None

    resp = data.get("response") if isinstance(data, dict) else None
    return resp if isinstance(resp, list) else None


# ---------------------------------------------------------------------------
# NORMALIZACIÓN (football y deportes /games)
# ---------------------------------------------------------------------------
def _num(x):
    """Marcador: entero, o dict {'total': n} (basketball), o None."""
    if isinstance(x, dict):
        x = x.get("total")
    try:
        return int(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _normalizar_item(deporte, item):
    """Devuelve un dict común o None si el item no tiene la forma esperada."""
    try:
        teams = item.get("teams") or {}
        h, a = teams.get("home") or {}, teams.get("away") or {}
        liga = item.get("league") or {}
        if deporte == "Soccer":
            fx = item.get("fixture") or {}
            pid, fecha, ts = fx.get("id"), fx.get("date"), fx.get("timestamp")
            estado = (fx.get("status") or {}).get("short", "")
            pl, pv = _num((item.get("goals") or {}).get("home")), _num((item.get("goals") or {}).get("away"))
            pais = liga.get("country") or ""
        else:
            pid, fecha, ts = item.get("id"), item.get("date"), item.get("timestamp")
            estado = (item.get("status") or {}).get("short", "")
            sc = item.get("scores") or {}
            pl, pv = _num(sc.get("home")), _num(sc.get("away"))
            pais = (item.get("country") or {}).get("name") or ""
        if pid is None or h.get("id") is None or a.get("id") is None:
            return None
        if not ts and fecha:
            try:
                ts = int(datetime.fromisoformat(str(fecha).replace("Z", "+00:00")).timestamp())
            except Exception:
                ts = 0
        return {
            "id": str(pid), "ts": int(ts or 0), "fecha": str(fecha or ""), "estado": str(estado).upper(),
            "liga_id": liga.get("id"), "liga_nombre": liga.get("name") or "", "pais": pais,
            "season": liga.get("season"),
            "id_local": str(h["id"]), "nom_local": h.get("name") or "Local",
            "id_visita": str(a["id"]), "nom_visita": a.get("name") or "Visitante",
            "pl": pl, "pv": pv,
        }
    except Exception:
        return None


def _como_partido_historico(n):
    return {
        "fecha": n["fecha"],
        "id_local": n["id_local"], "nom_local": n["nom_local"],
        "id_visita": n["id_visita"], "nom_visita": n["nom_visita"],
        "puntos_local": n["pl"], "puntos_visita": n["pv"],
    }


# ---------------------------------------------------------------------------
# PRÓXIMOS PARTIDOS
# ---------------------------------------------------------------------------
def _items_del_dia(deporte, fecha):
    clave = (deporte, fecha)
    hit, valor = _cache_eventos.get(clave)
    if hit:
        return valor
    ruta = "/fixtures" if deporte == "Soccer" else "/games"
    resp = _get(deporte, ruta, {"date": fecha})
    if resp is None:
        return []  # no se cachea el fallo: se reintenta en el próximo barrido
    items = [n for n in (_normalizar_item(deporte, i) for i in resp) if n]
    if resp and not items:
        _avisar_una_vez(("forma", deporte),
                        f"[api_sports/{deporte}] llegaron {len(resp)} items pero ninguno con la forma esperada")
    _cache_eventos.set(clave, items)
    return items


def obtener_eventos(deporte):
    """Partidos FEMENINOS de las próximas 24 h (por nombre de liga/equipos)."""
    if deporte not in DEPORTES_ACTIVOS or not disponible():
        return []

    ahora = time.time()
    hoy = datetime.now(timezone.utc)
    fechas = [hoy.strftime("%Y-%m-%d"), (hoy + timedelta(days=1)).strftime("%Y-%m-%d")]

    por_id = {}
    for fecha in fechas:
        for n in _items_del_dia(deporte, fecha):
            if n["estado"] not in _PROGRAMADOS:
                continue
            if not n["ts"] or n["ts"] < ahora or n["ts"] > ahora + HORAS_VENTANA * 3600:
                continue
            if not U.es_femenino(n["liga_nombre"], n["nom_local"], n["nom_visita"]):
                continue
            torneo = f"{n['liga_nombre']} ({n['pais']})" if n["pais"] else n["liga_nombre"]
            por_id[n["id"]] = {
                "id": f"apisports_{deporte}_{n['id']}",
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
                "liga_ref": (deporte, n["liga_id"], n["season"]),
            }
    return list(por_id.values())


# ---------------------------------------------------------------------------
# HISTORIAL: una liga = un pedido con toda la temporada
# ---------------------------------------------------------------------------
_ligas_pedidas_hoy = {"fecha": "", "ligas": set()}


def _historial_liga(deporte, liga_id, season):
    clave = (deporte, liga_id, season)
    hit, valor = _cache_temporada.get(clave)
    if hit:
        return valor

    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _ligas_pedidas_hoy["fecha"] != hoy:
        _ligas_pedidas_hoy.update(fecha=hoy, ligas=set())
    ligas_del_deporte = [k for k in _ligas_pedidas_hoy["ligas"] if k[0] == deporte]
    if clave not in _ligas_pedidas_hoy["ligas"] and len(ligas_del_deporte) >= MAX_LIGAS_POR_DEPORTE:
        return {}  # tope de ligas distintas por deporte y por día para no gastar la cuota

    ruta = "/fixtures" if deporte == "Soccer" else "/games"
    resp = _get(deporte, ruta, {"league": liga_id, "season": season})
    if resp is None:
        return {}
    _ligas_pedidas_hoy["ligas"].add(clave)

    por_equipo = {}
    for n in (_normalizar_item(deporte, i) for i in resp):
        if not n or n["estado"] not in _FINALIZADOS or n["pl"] is None or n["pv"] is None:
            continue
        p = _como_partido_historico(n)
        for tid in (n["id_local"], n["id_visita"]):
            por_equipo.setdefault(tid, []).append(p)
    for lista in por_equipo.values():
        lista.sort(key=lambda p: p["fecha"], reverse=True)

    U.log(f"[api_sports/{deporte}] historial liga {liga_id}: {sum(len(v) for v in por_equipo.values()) // 2} partidos")
    _cache_temporada.set(clave, por_equipo)
    return por_equipo


def historial_equipo(evento, lado):
    ref = evento.get("liga_ref")
    if not ref or len(ref) != 3:
        return []
    deporte, liga_id, season = ref
    if not liga_id or not season or not disponible():
        return []
    tid = (evento.get(lado) or {}).get("id")
    return _historial_liga(deporte, liga_id, season).get(tid, [])

