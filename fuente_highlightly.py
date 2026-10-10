"""
fuente_highlightly.py
Highlightly (https://highlightly.net/): fuente de EVENTOS femeninos y de datos de profundidad.

QuÃ© aporta (deportes: Soccer, Basketball, Ice Hockey, Handball, Volleyball):
- Eventos: partidos de las prÃ³ximas 24 h (GET /matches?date=), filtrados con el filtro femenino compartido.
- Forma reciente por equipo (GET /last-five-games?teamId=).
- H2H por equipo (GET /head-2-head?teamIdOne=&teamIdTwo=). Los ids se resuelven por nombre (GET /teams?name=).
- Tabla de posiciones (GET /standings?leagueId=&season=). La liga se deduce de los Ãºltimos partidos
  que comparten los dos equipos.

AutenticaciÃ³n: header x-rapidapi-key con la clave de Highlightly (HIGHLIGHTLY_API_KEY).
Hosts: cada deporte tiene su host propio (soccer.highlightly.net, volleyball.highlightly.net, ...) y
tambien existe el host de la suscripcion All Sports (sports.highlightly.net/<deporte>/...). Con
HIGHLIGHTLY_MODO=auto (por defecto) prueba el host del deporte y, si no responde (403/404), el de All Sports.

Cuota: presupuesto diario persistente (HIGHLIGHTLY_DAILY_LIMIT, por defecto 100) corregido con los headers
x-ratelimit-requests-*. El listado de eventos solo gasta mientras quede por encima de
HIGHLIGHTLY_RESERVA_ANALISIS requests, que quedan reservados para forma / H2H / tablas.
"""

import os
import re
from datetime import datetime, timedelta, timezone

import utilidades as U

API_KEY = os.environ.get("HIGHLIGHTLY_API_KEY")
FUENTE = "highlightly"
HORAS_VENTANA = 24
BASE_TODOS = "https://sports.highlightly.net"
MODO = (os.environ.get("HIGHLIGHTLY_MODO") or "auto").strip().lower()

_DEPORTES_HL = {
    "Soccer": "football",
    "Basketball": "basketball",
    "Ice Hockey": "hockey",
    "Handball": "handball",
    "Volleyball": "volleyball",
}
_SUBHOSTS = {
    "Soccer": "https://soccer.highlightly.net",
    "Basketball": "https://basketball.highlightly.net",
    "Ice Hockey": "https://hockey.highlightly.net",
    "Handball": "https://handball.highlightly.net",
    "Volleyball": "https://volleyball.highlightly.net",
}

DEPORTES_ACTIVOS = [
    d.strip() for d in os.environ.get(
        "HIGHLIGHTLY_DEPORTES", "Soccer,Volleyball,Handball,Basketball,Ice Hockey"
    ).split(",") if d.strip() in _DEPORTES_HL
]
MAX_PAGINAS = max(1, int(os.environ.get("HIGHLIGHTLY_MAX_PAGINAS", "1")))
RESERVA_ANALISIS = int(os.environ.get("HIGHLIGHTLY_RESERVA_ANALISIS", "40"))
EXIGIR_FEMENINO = os.environ.get("HIGHLIGHTLY_EXIGIR_FEMENINO", "1") != "0"


def _leer_ligas_femeninas():
    """IDs verificados por el operador; formato: Soccer:123;Volleyball:456."""
    resultado = {}
    raw = (os.environ.get("HIGHLIGHTLY_WOMENS_LEAGUES") or "").strip()
    for item in raw.replace(",", ";").split(";"):
        item = item.strip()
        if ":" not in item:
            continue
        deporte, league_id = (parte.strip() for parte in item.split(":", 1))
        if deporte in _DEPORTES_HL and league_id.isdigit():
            resultado.setdefault(deporte, set()).add(league_id)
    return resultado


_LIGAS_FEMENINAS = _leer_ligas_femeninas()


def _liga_es_femenina(deporte, liga_id, nombre_liga, nombre_local, nombre_visita):
    identificador = str(liga_id or "")
    if identificador and identificador in _LIGAS_FEMENINAS.get(deporte, set()):
        return True
    return U.es_femenino(nombre_liga, nombre_local, nombre_visita)

presupuesto = U.PresupuestoDiario(
    "highlightly", limite=os.environ.get("HIGHLIGHTLY_DAILY_LIMIT", "100"),
    reserva=os.environ.get("HIGHLIGHTLY_RESERVA", "5"),
)

_cache_eventos = U.CacheTTL(max(30, int(os.environ.get("HIGHLIGHTLY_CACHE_MINUTES", "240"))) * 60)
_cache_equipo = U.CacheTTL(12 * 3600)
_cache_forma = U.CacheTTL(3 * 3600)
_cache_h2h = U.CacheTTL(6 * 3600)
_cache_tabla = U.CacheTTL(6 * 3600)
_deshabilitada = {"motivo": ""}
_base_ok = {}
_avisos = set()
_reintentar_despues = {}


def _avisar_una_vez(clave, mensaje):
    if clave not in _avisos:
        _avisos.add(clave)
        U.log(mensaje)


def disponible():
    return bool(API_KEY) and not _deshabilitada["motivo"]


def _headers():
    return {"x-rapidapi-key": API_KEY, "Accept": "application/json"}


# ---------------------------------------------------------------------------
# HTTP con presupuesto y respaldo de host
# ---------------------------------------------------------------------------
def _bases(deporte):
    if deporte in _base_ok:
        return [_base_ok[deporte]]
    propio = (_SUBHOSTS[deporte], "")
    todos = (BASE_TODOS, "/" + _DEPORTES_HL[deporte])
    if MODO == "deporte":
        return [propio]
    if MODO == "todos":
        return [todos]
    return [propio, todos]


def _get(deporte, ruta, params=None):
    """Devuelve JSON o None; tras 403/404 alterna host una vez y enfría el endpoint."""
    if not disponible() or deporte not in _DEPORTES_HL:
        return None
    clave_cooldown = (deporte, ruta)
    if __import__("time").time() < _reintentar_despues.get(clave_cooldown, 0):
        return None
    estados_vistos = []
    for base, prefijo in _bases(deporte):
        if not presupuesto.puede_gastar(1):
            _avisar_una_vez(("presupuesto", presupuesto.fecha),
                            f"[highlightly] presupuesto diario agotado ({presupuesto.usadas}/{presupuesto.limite}); "
                            "se reanuda maÃ±ana (UTC)")
            return None
        info = {}
        data = U.get_json(f"{base}{prefijo}{ruta}", FUENTE, headers=_headers(), params=params,
                          timeout=15, info=info)
        status = info.get("status")
        if status is None:
            continue  # error de red o host inexistente: get_json ya lo logueÃ³
        h = {k.lower(): v for k, v in (info.get("headers") or {}).items()}
        try:
            if h.get("x-ratelimit-requests-limit") is not None:
                presupuesto.limite = max(1, int(h["x-ratelimit-requests-limit"]))
        except (TypeError, ValueError):
            pass
        presupuesto.registrar(1, restantes_reales=h.get("x-ratelimit-requests-remaining"))
        if status == 429:
            presupuesto.marcar_agotado()
            _avisar_una_vez(("limite", presupuesto.fecha), "[highlightly] lÃ­mite diario alcanzado (HTTP 429)")
            return None
        if status == 401:
            _deshabilitada["motivo"] = "HTTP 401: clave invÃ¡lida"
            U.log(f"[highlightly] DESACTIVADA: {_deshabilitada['motivo']}")
            return None
        if status in (403, 404):
            estados_vistos.append(status)
            continue
        if data is None:
            import time
            _reintentar_despues[clave_cooldown] = time.time() + 15 * 60
            return None
        _base_ok[deporte] = (base, prefijo)
        _reintentar_despues.pop(clave_cooldown, None)
        return data
    import time
    if estados_vistos and all(estado in (403, 404) for estado in estados_vistos):
        _reintentar_despues[clave_cooldown] = time.time() + 3 * 3600
        _avisar_una_vez(("hosts", deporte, ruta), f"[highlightly/{deporte}] ambos hosts rechazaron {ruta}; se reintentará en 3 h")
    elif estados_vistos:
        _reintentar_despues[clave_cooldown] = time.time() + 15 * 60
    return None


def _lista(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        d = data.get("data")
        return d if isinstance(d, list) else []
    return []


# ---------------------------------------------------------------------------
# NORMALIZACIÃ“N
# ---------------------------------------------------------------------------
_RE_MARCADOR = re.compile(r"(\d+)\s*[-:]\s*(\d+)")


def _marcador(m):
    sc = (m.get("state") or {}).get("score")
    texto = sc.get("current") if isinstance(sc, dict) else None
    if not texto:
        return None, None
    r = _RE_MARCADOR.search(str(texto))
    if not r:
        return None, None
    return int(r.group(1)), int(r.group(2))


def _ts(fecha):
    try:
        f = datetime.fromisoformat(str(fecha).replace("Z", "+00:00"))
        if f.tzinfo is None:
            f = f.replace(tzinfo=timezone.utc)
        return int(f.timestamp())
    except Exception:
        return 0


def _normalizar_partido(m):
    """Devuelve un dict comÃºn o None si el item no tiene la forma esperada."""
    try:
        h, a = m.get("homeTeam") or {}, m.get("awayTeam") or {}
        if m.get("id") is None or h.get("id") is None or a.get("id") is None:
            return None
        liga = m.get("league") or {}
        pais = (m.get("country") or {}).get("name") or ""
        pl, pv = _marcador(m)
        fecha = str(m.get("date") or "")
        return {
            "id": str(m["id"]), "ts": _ts(fecha), "fecha": fecha,
            "estado": str((m.get("state") or {}).get("description") or "").lower(),
            "liga_id": liga.get("id"), "liga_nombre": liga.get("name") or "", "season": liga.get("season"),
            "pais": pais,
            "id_local": str(h["id"]), "nom_local": h.get("name") or "Local",
            "id_visita": str(a["id"]), "nom_visita": a.get("name") or "Visitante",
            "pl": pl, "pv": pv,
        }
    except Exception:
        return None


def _como_historico(n, equipo_id=None, id_interno=None):
    """
    Formato interno del radar. Si se da `id_interno`, el equipo consultado (equipo_id de Highlightly)
    queda con el id que usa el evento, para que el motor lo reconozca como local o visita.
    """
    id_local, id_visita = n["id_local"], n["id_visita"]
    if equipo_id is not None and id_interno is not None:
        if id_local == str(equipo_id):
            id_local = str(id_interno)
        elif id_visita == str(equipo_id):
            id_visita = str(id_interno)
    return {
        "fecha": n["fecha"],
        "id_local": id_local, "nom_local": n["nom_local"],
        "id_visita": id_visita, "nom_visita": n["nom_visita"],
        "puntos_local": n["pl"], "puntos_visita": n["pv"],
    }


# ---------------------------------------------------------------------------
# EVENTOS (prÃ³ximas 24 h)
# ---------------------------------------------------------------------------
def _items_del_dia(deporte, fecha):
    clave = (deporte, fecha)
    hit, valor = _cache_eventos.get(clave)
    if hit:
        return valor
    if presupuesto.restantes() <= RESERVA_ANALISIS:
        return []  # lo que queda se reserva para forma / H2H / tablas; no se cachea
    items, offset, limite, total = [], 0, 100, None
    for pagina in range(MAX_PAGINAS):
        data = _get(deporte, "/matches", {"date": fecha, "limit": limite, "offset": offset})
        if data is None:
            if pagina == 0:
                return []  # no se cachea el fallo: se reintenta en el prÃ³ximo barrido
            break
        lista = _lista(data)
        items += [n for n in (_normalizar_partido(m) for m in lista) if n]
        if isinstance(data, dict):
            try:
                total = int((data.get("pagination") or {}).get("totalCount"))
            except (TypeError, ValueError):
                total = None
        offset += limite
        if not lista or (total is not None and offset >= total):
            break
        if presupuesto.restantes() <= RESERVA_ANALISIS:
            break
    if total is not None and len(items) < total:
        U.log(f"[highlightly/{deporte}] {fecha}: leÃ­ {len(items)} de {total} partidos "
              f"(tope de {MAX_PAGINAS} pÃ¡ginas; HIGHLIGHTLY_MAX_PAGINAS lo amplÃ­a)")
    _cache_eventos.set(clave, items)
    return items


def obtener_eventos(deporte):
    """Partidos FEMENINOS de las prÃ³ximas 24 h (por nombre de liga/equipos)."""
    if deporte not in DEPORTES_ACTIVOS or not disponible():
        return []
    ahora = datetime.now(timezone.utc)
    t0 = ahora.timestamp()
    fechas = [ahora.strftime("%Y-%m-%d"), (ahora + timedelta(days=1)).strftime("%Y-%m-%d")]

    por_id = {}
    for fecha in fechas:
        for n in _items_del_dia(deporte, fecha):
            if n["estado"] != "not started":
                continue
            if not n["ts"] or n["ts"] < t0 or n["ts"] > t0 + HORAS_VENTANA * 3600:
                continue
            if not _liga_es_femenina(
                deporte, n["liga_id"], n["liga_nombre"], n["nom_local"], n["nom_visita"]
            ):
                continue
            torneo = f"{n['liga_nombre']} ({n['pais']})" if n["pais"] else n["liga_nombre"]
            por_id[n["id"]] = {
                "id": f"highlightly_{deporte}_{n['id']}",
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
                "liga_ref": (n["liga_id"], n["season"]),
            }
    return list(por_id.values())


# ---------------------------------------------------------------------------
# EQUIPOS POR NOMBRE
# ---------------------------------------------------------------------------
def _elegir_equipo(nombre, candidatos):
    """
    Elige el candidato que coincide con `nombre`. Con EXIGIR_FEMENINO (por defecto) solo acepta equipos
    con marca femenina en el nombre: asÃ­ "Arsenal W" nunca se resuelve al Arsenal masculino.
    """
    objetivo = U.normalizar(nombre)
    mejor, mejor_pts = None, 0
    for c in candidatos:
        nom = c.get("name") or ""
        if c.get("id") is None or not U.nombres_coinciden(nombre, nom):
            continue
        fem = U.es_femenino("", nom, "")
        if EXIGIR_FEMENINO and not fem:
            continue
        pts = 1 + (2 if U.normalizar(nom) == objetivo else 0) + (1 if fem else 0)
        if pts > mejor_pts:
            mejor, mejor_pts = c["id"], pts
    return mejor


def _buscar_equipo(nombre, deporte="Soccer"):
    if not disponible() or not nombre or deporte not in _DEPORTES_HL:
        return None
    clave = f"busq|{deporte}|{U.normalizar(nombre)}"
    hit, valor = _cache_equipo.get(clave)
    if hit:
        return valor
    data = _get(deporte, "/teams", {"name": nombre, "limit": 50})
    if data is None:
        return None  # no se cachea el fallo
    equipo_id = _elegir_equipo(nombre, _lista(data))
    _cache_equipo.set(clave, equipo_id)
    return equipo_id


def _resolver_ids(nombre_local, nombre_visita, deporte, ids_hl=None):
    if ids_hl:
        return str(ids_hl[0]), str(ids_hl[1])
    a, b = _buscar_equipo(nombre_local, deporte), _buscar_equipo(nombre_visita, deporte)
    if not a or not b:
        return None, None
    return str(a), str(b)


# ---------------------------------------------------------------------------
# FORMA RECIENTE
# ---------------------------------------------------------------------------
def _forma_cruda(deporte, equipo_id):
    """Ãšltimos partidos terminados del equipo (normalizados, mÃ¡s reciente primero)."""
    clave = (deporte, str(equipo_id))
    hit, valor = _cache_forma.get(clave)
    if hit:
        return valor
    data = _get(deporte, "/last-five-games", {"teamId": equipo_id})
    if data is None:
        return []
    partidos = [n for n in (_normalizar_partido(m) for m in _lista(data)) if n and n["pl"] is not None]
    partidos.sort(key=lambda n: n["fecha"], reverse=True)
    _cache_forma.set(clave, partidos)
    return partidos


def historial_equipo(evento, lado):
    """Para eventos que vienen de Highlightly: el id del equipo ya es el de Highlightly."""
    if not disponible():
        return []
    equipo = evento.get(lado) or {}
    if not equipo.get("id"):
        return []
    return [_como_historico(n) for n in _forma_cruda(evento.get("deporte", "Soccer"), equipo["id"])]


def obtener_forma_reciente(nombre_equipo, deporte="Soccer", limite=6, id_interno=None):
    """Ãšltimos partidos de un equipo buscado por nombre, con el id del evento (`id_interno`)."""
    equipo_id = _buscar_equipo(nombre_equipo, deporte)
    if not equipo_id:
        return []
    return [_como_historico(n, equipo_id, id_interno)
            for n in _forma_cruda(deporte, equipo_id)[:limite]]


# ---------------------------------------------------------------------------
# H2H
# ---------------------------------------------------------------------------
def obtener_h2h(nombre_local, nombre_visita, deporte="Soccer", id_local=None, id_visita=None, ids_hl=None):
    """
    H2H entre dos equipos. Devuelve [{fecha, id_local, id_visita, puntos_local, puntos_visita}] con los ids
    del EVENTO (`id_local` / `id_visita`), que son los que usa el motor. `ids_hl` = ids de Highlightly si
    el evento ya viene de Highlightly; si no, se buscan por nombre.
    """
    hl_loc, hl_vis = _resolver_ids(nombre_local, nombre_visita, deporte, ids_hl)
    if not hl_loc or not hl_vis:
        return []
    clave = (deporte, hl_loc, hl_vis)
    hit, crudo = _cache_h2h.get(clave)
    if not hit:
        data = _get(deporte, "/head-2-head", {"teamIdOne": hl_loc, "teamIdTwo": hl_vis})
        if data is None:
            return []
        crudo = [n for n in (_normalizar_partido(m) for m in _lista(data)) if n and n["pl"] is not None]
        _cache_h2h.set(clave, crudo)

    id_ev_loc = str(id_local) if id_local is not None else hl_loc
    id_ev_vis = str(id_visita) if id_visita is not None else hl_vis
    partidos = []
    for n in crudo:
        if n["id_local"] == hl_loc and n["id_visita"] == hl_vis:
            il, iv, pl, pv = id_ev_loc, id_ev_vis, n["pl"], n["pv"]
        elif n["id_local"] == hl_vis and n["id_visita"] == hl_loc:
            il, iv, pl, pv = id_ev_vis, id_ev_loc, n["pl"], n["pv"]
        else:
            continue
        partidos.append({"fecha": n["fecha"], "id_local": il, "id_visita": iv,
                         "puntos_local": pl, "puntos_visita": pv})
    return partidos


# ---------------------------------------------------------------------------
# TABLA DE POSICIONES
# ---------------------------------------------------------------------------
def _num(x, defecto=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return defecto


def _fila_tabla(f):
    team = f.get("team") or {}
    t = f.get("total") or {}
    victorias = t.get("wins")
    derrotas = t.get("loses", t.get("losses", t.get("lost")))
    if team.get("id") is None or (victorias is None and derrotas is None):
        return None
    return {
        "id": str(team["id"]), "nombre": team.get("name") or "",
        "posicion": _num(f.get("position")),
        "victorias": _num(victorias), "empates": _num(t.get("draws")), "derrotas": _num(derrotas),
        "dif_neta": _num(t.get("scoredGoals", t.get("scoredPoints"))) - _num(
            t.get("receivedGoals", t.get("receivedPoints"))),
    }


def _standings(deporte, liga_id, season):
    """Lista de grupos; cada grupo es una lista de filas normalizadas."""
    clave = (deporte, liga_id, season)
    hit, valor = _cache_tabla.get(clave)
    if hit:
        return valor
    data = _get(deporte, "/standings", {"leagueId": liga_id, "season": season})
    if data is None:
        return []
    grupos = []
    for g in (data.get("groups") if isinstance(data, dict) else None) or []:
        filas = [x for x in (_fila_tabla(f) for f in (g.get("standings") or [])) if x]
        if filas:
            grupos.append(filas)
    _cache_tabla.set(clave, grupos)
    return grupos


def _liga_comun(partidos_a, partidos_b):
    """(liga_id, season) mÃ¡s frecuente entre los Ãºltimos partidos de AMBOS equipos."""
    def conteo(partidos):
        c = {}
        for n in partidos:
            if n["liga_id"] is not None and n["season"] is not None:
                k = (n["liga_id"], n["season"])
                c[k] = c.get(k, 0) + 1
        return c
    ca, cb = conteo(partidos_a), conteo(partidos_b)
    comunes = [k for k in ca if k in cb]
    if not comunes:
        return None
    return max(comunes, key=lambda k: ca[k] + cb[k])


def obtener_tabla_partido(nombre_local, nombre_visita, deporte="Soccer", ids_hl=None):
    """
    Filas de tabla de los dos equipos en la liga que comparten: {"local": fila, "visita": fila,
    "n_equipos": n} o None (sin liga comÃºn, sin tabla o equipos no encontrados).
    Cada fila: {posicion, victorias, empates, derrotas, dif_neta, nombre}.
    """
    if not disponible():
        return None
    hl_loc, hl_vis = _resolver_ids(nombre_local, nombre_visita, deporte, ids_hl)
    if not hl_loc or not hl_vis:
        return None
    liga = _liga_comun(_forma_cruda(deporte, hl_loc), _forma_cruda(deporte, hl_vis))
    if not liga:
        return None
    for filas in _standings(deporte, liga[0], liga[1]):
        por_id = {f["id"]: f for f in filas}
        if hl_loc in por_id and hl_vis in por_id:
            return {"local": por_id[hl_loc], "visita": por_id[hl_vis], "n_equipos": len(filas)}
    return None
