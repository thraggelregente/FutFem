"""
utilidades.py
Funciones compartidas por todo el radar:
- Hora de Argentina (zona horaria real, no la del servidor).
- Logging y estadÃ­sticas por fuente (cuÃ¡ntas respuestas 200 / 403 / errores).
- HTTP con manejo de errores visible (nada falla en silencio), con soporte de proxy.
- Cache con vencimiento.
- Persistencia de partidos ya vistos (Upstash Redis o archivo en DATA_DIR).
- NormalizaciÃ³n y comparaciÃ³n de nombres de equipos / jugadoras.
"""

import json
import os
import re
import threading
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

try:
    from zoneinfo import ZoneInfo
    TZ_ARG = ZoneInfo("America/Argentina/Buenos_Aires")
except Exception:
    TZ_ARG = timezone(timedelta(hours=-3))

try:
    from curl_cffi import requests as curl_requests
except Exception as _e_import_curl:
    curl_requests = None
    _ERROR_IMPORT_CURL = f"{type(_e_import_curl).__name__}: {_e_import_curl}"
else:
    _ERROR_IMPORT_CURL = ""


# ---------------------------------------------------------------------------
# HORA
# ---------------------------------------------------------------------------
def ahora_arg():
    return datetime.now(TZ_ARG)


def fecha_arg(dias=0):
    return (ahora_arg() + timedelta(days=dias)).strftime("%Y-%m-%d")


def ts_a_arg(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(TZ_ARG)


def ts_a_iso_utc(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def formatear_hora_arg(ts):
    return ts_a_arg(ts).strftime("%d/%m %H:%M hs (ARG)")


def log(msg):
    print(f"[{ahora_arg().strftime('%d/%m %H:%M:%S')}] {msg}", flush=True)


if curl_requests is None:
    log(f"[http] curl_cffi no disponible ({_ERROR_IMPORT_CURL}); uso requests")


# ---------------------------------------------------------------------------
# HTTP + ESTADÃSTICAS POR FUENTE
# ---------------------------------------------------------------------------
HEADERS_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}

_HEADERS_QUE_PONE_CURL = {"user-agent", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"}

ESTADISTICAS = defaultdict(lambda: defaultdict(int))
_lock = threading.Lock()
_avisos_curl = set()


def reiniciar_estadisticas():
    with _lock:
        ESTADISTICAS.clear()


def _registrar(fuente, codigo):
    with _lock:
        ESTADISTICAS[fuente][codigo] += 1


def hay_bloqueo(fuente, minimo=3):
    codigos = ESTADISTICAS.get(fuente)
    if not codigos:
        return False
    return sum(codigos.values()) >= minimo and codigos.get(200, 0) == 0


def proxies_desde_env(nombre_var):
    url = (os.environ.get(nombre_var) or "").strip()
    return {"http": url, "https": url} if url else None


def _pedir(url, headers, params, timeout, proxies, fuente):
    base = headers or HEADERS_NAVEGADOR
    if curl_requests is not None:
        try:
            h = {k: v for k, v in base.items() if k.lower() not in _HEADERS_QUE_PONE_CURL}
            return curl_requests.get(
                url, headers=h, params=params, timeout=timeout,
                impersonate="chrome124", proxies=proxies,
            )
        except Exception as e_curl:
            clave = (fuente, type(e_curl).__name__)
            if clave not in _avisos_curl:
                _avisos_curl.add(clave)
                log(f"[{fuente}] curl_cffi fallÃ³ ({type(e_curl).__name__}: {str(e_curl)[:120]}); uso requests")
    try:
        return requests.get(url, headers=base, params=params, timeout=timeout, proxies=proxies)
    except requests.RequestException as e:
        _registrar(fuente, "error_red")
        log(f"[{fuente}] error_red: {type(e).__name__} en {url.split('?')[0]}")
        return None


def get_json(url, fuente, headers=None, params=None, timeout=12, proxies=None, info=None):
    r = _pedir(url, headers, params, timeout, proxies, fuente)
    if r is None:
        return None

    if info is not None:
        info["status"] = r.status_code
        info["headers"] = dict(r.headers)

    _registrar(fuente, r.status_code)
    if r.status_code != 200:
        log(f"[{fuente}] HTTP {r.status_code} en {url.split('?')[0]}")
        return None

    try:
        return r.json()
    except Exception:
        _registrar(fuente, "json_invalido")
        cuerpo = (r.text or "")[:200].replace("\n", " ")
        tipo = r.headers.get("content-type", "?")
        log(f"[{fuente}] respuesta no es JSON en {url.split('?')[0]} (content-type {tipo}) cuerpo: {cuerpo!r}")
        return None


def get_texto(url, fuente, headers=None, params=None, timeout=15):
    try:
        r = requests.get(url, headers=headers or HEADERS_NAVEGADOR, params=params, timeout=timeout)
    except requests.RequestException as e:
        _registrar(fuente, "error_red")
        log(f"[{fuente}] error de red ({type(e).__name__}) en {url.split('?')[0]}")
        return None
    _registrar(fuente, r.status_code)
    if r.status_code != 200:
        log(f"[{fuente}] HTTP {r.status_code} en {url.split('?')[0]}")
        return None
    r.encoding = r.encoding or "utf-8"
    return r.text


# ---------------------------------------------------------------------------
# CACHE CON VENCIMIENTO
# ---------------------------------------------------------------------------
class CacheTTL:
    def __init__(self, ttl_segundos):
        self.ttl = ttl_segundos
        self._datos = {}

    def get(self, clave):
        item = self._datos.get(clave)
        if item and (time.time() - item[0]) < self.ttl:
            return True, item[1]
        return False, None

    def set(self, clave, valor):
        self._datos[clave] = (time.time(), valor)
        if len(self._datos) > 2000:
            self.limpiar()

    def limpiar(self):
        ahora = time.time()
        self._datos = {k: v for k, v in self._datos.items() if (ahora - v[0]) < self.ttl}


# ---------------------------------------------------------------------------
# PERSISTENCIA (Upstash Redis o archivo en DATA_DIR)
# ---------------------------------------------------------------------------
DATA_DIR = os.environ.get("DATA_DIR", ".")
UPSTASH_URL = (os.environ.get("UPSTASH_REDIS_REST_URL") or "").strip()
UPSTASH_TOKEN = (os.environ.get("UPSTASH_REDIS_REST_TOKEN") or "").strip()
_UPSTASH_ULTIMO_OK = None  # None = todavía no se probó en este proceso


def usa_upstash():
    return bool(UPSTASH_URL and UPSTASH_TOKEN)


def persistencia_es_duradera():
    # No anunciar persistencia remota sana si ya falló una operación de Upstash.
    # El primer GET de RegistroVistos sucede al importar main, antes del aviso de inicio.
    if usa_upstash():
        return _UPSTASH_ULTIMO_OK is not False
    return "DATA_DIR" in os.environ


def modo_persistencia():
    if usa_upstash():
        return "Upstash Redis"
    if "DATA_DIR" in os.environ:
        return f"archivo en {DATA_DIR}"
    return "archivo local (se pierde al reiniciar/deployar)"


def _upstash(comando):
    global _UPSTASH_ULTIMO_OK
    try:
        r = requests.post(
            UPSTASH_URL,
            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
            json=comando,
            timeout=8,
        )
        r.raise_for_status()
        resultado = r.json().get("result")
        _UPSTASH_ULTIMO_OK = True
        return resultado
    except Exception:
        _UPSTASH_ULTIMO_OK = False
        raise


def cargar_json(nombre, defecto):
    if usa_upstash():
        try:
            res = _upstash(["GET", f"radar:{nombre}"])
            return json.loads(res) if res else defecto
        except Exception as e:
            log(f"[persistencia] Upstash GET fallÃ³ ({type(e).__name__}); uso archivo")
    ruta = os.path.join(DATA_DIR, nombre)
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"[persistencia] no pude leer {nombre} ({type(e).__name__})")
    return defecto


def guardar_json(nombre, datos):
    texto = json.dumps(datos, ensure_ascii=False)
    if usa_upstash():
        try:
            _upstash(["SET", f"radar:{nombre}", texto])
            return True
        except Exception as e:
            log(f"[persistencia] Upstash SET fallÃ³ ({type(e).__name__}); uso archivo")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        ruta = os.path.join(DATA_DIR, nombre)
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(texto)
        os.replace(tmp, ruta)
        return True
    except Exception as e:
        log(f"[persistencia] no pude guardar {nombre} ({type(e).__name__})")
        return False


def _parsear_iso(texto):
    try:
        f = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
        if f.tzinfo is None:
            f = f.replace(tzinfo=timezone.utc)
        return f
    except Exception:
        return None


def podar_por_antiguedad(diccionario, dias):
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    limpio = {}
    for clave, valor in diccionario.items():
        f = _parsear_iso(valor)
        if f is not None and f >= limite:
            limpio[clave] = valor
    return limpio


class RegistroVistos:
    def __init__(self, nombre, dias_retencion=3):
        self.nombre = nombre
        self.dias = dias_retencion
        crudo = cargar_json(nombre, {})
        ahora = datetime.now(timezone.utc).isoformat()
        if isinstance(crudo, list):
            crudo = {str(k): ahora for k in crudo}
        elif not isinstance(crudo, dict):
            crudo = {}
        self.datos = podar_por_antiguedad(crudo, self.dias)
        self.sucio = False

    def visto(self, id_unico):
        return id_unico in self.datos

    def marcar(self, id_unico):
        self.datos[id_unico] = datetime.now(timezone.utc).isoformat()
        self.sucio = True

    def podar(self):
        antes = len(self.datos)
        self.datos = podar_por_antiguedad(self.datos, self.dias)
        if len(self.datos) != antes:
            self.sucio = True

    def guardar(self):
        if self.sucio and guardar_json(self.nombre, self.datos):
            self.sucio = False


# ---------------------------------------------------------------------------
# PRESUPUESTO DIARIO DE REQUESTS (APIs con cuota, p. ej. API-Sports 100/dÃ­a)
# ---------------------------------------------------------------------------
class PresupuestoDiario:
    """
    Cuenta los requests gastados en el dÃ­a (UTC, igual que el reinicio de API-Sports) y
    los persiste, asÃ­ un reinicio/deploy no "olvida" lo gastado. Nunca deja gastar la reserva.
    """

    def __init__(self, nombre, limite, reserva=8):
        self.nombre = nombre
        self.limite = max(1, int(limite))
        self.reserva = max(0, int(reserva))
        self.agotado_hasta_manana = False
        crudo = cargar_json(f"presupuesto_{nombre}.json", {})
        hoy = self._hoy()
        if isinstance(crudo, dict) and crudo.get("fecha") == hoy:
            self.fecha = hoy
            self.usadas = int(crudo.get("usadas", 0) or 0)
        else:
            self.fecha = hoy
            self.usadas = 0

    @staticmethod
    def _hoy():
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _rotar(self):
        hoy = self._hoy()
        if hoy != self.fecha:
            self.fecha, self.usadas, self.agotado_hasta_manana = hoy, 0, False

    def restantes(self):
        self._rotar()
        if self.agotado_hasta_manana:
            return 0
        return max(0, self.limite - self.reserva - self.usadas)

    def puede_gastar(self, n=1):
        return self.restantes() >= n

    def registrar(self, n=1, restantes_reales=None):
        """Suma n requests. Si la API informÃ³ cuÃ¡ntos le quedan, se corrige con ese dato."""
        self._rotar()
        self.usadas += n
        if restantes_reales is not None:
            try:
                self.usadas = max(self.usadas, self.limite - int(restantes_reales))
            except (TypeError, ValueError):
                pass
        guardar_json(f"presupuesto_{self.nombre}.json", {"fecha": self.fecha, "usadas": self.usadas})

    def marcar_agotado(self):
        self._rotar()
        self.agotado_hasta_manana = True
        self.usadas = self.limite
        guardar_json(f"presupuesto_{self.nombre}.json", {"fecha": self.fecha, "usadas": self.usadas})


# ---------------------------------------------------------------------------
# NOMBRES
# ---------------------------------------------------------------------------
def normalizar(texto):
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


_PALABRAS_RUIDO = {
    "fc", "cf", "sc", "ac", "afc", "club", "women", "womens", "woman", "ladies",
    "fem", "femenino", "femenina", "femenil", "feminin", "damen", "frauen",
    "del", "los", "las", "cd", "ud", "u19", "u20", "u21", "u23", "sub",
}


def tokens_significativos(texto):
    return {t for t in normalizar(texto).split() if len(t) >= 3 and t not in _PALABRAS_RUIDO}


def nombres_coinciden(a, b):
    ta, tb = tokens_significativos(a), tokens_significativos(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta


# ---------------------------------------------------------------------------
# FILTRO FEMENINO COMPARTIDO (todas las fuentes usan el mismo)
# ---------------------------------------------------------------------------
# Evidencia POSITIVA de torneo/equipo femenino. El texto se normaliza antes (sin tildes ni signos),
# asÃ­ "Division 1 FÃ©minine", "Frauen-Bundesliga" o "Liga MX Femenil" quedan cubiertos.
_RE_FEM = re.compile(
    r"\b(women|womens|woman|wom|female|femenino|femenina|femenil|femeni|feminino|feminina|"
    r"feminin|feminine|femminile|fem|frauen|damen|dames|ladies|vrouwen|kvinde\w*|kvinnor|"
    r"damallsvenskan|toppserien|wta|wnba|nwsl|wsl|itf w|we league|liga f|"
    r"w\s?(15|25|35|50|60|75|80|100))\b"
)
_RE_EQUIPO_W = re.compile(r"\bw$")  # "Arsenal W", "Barcelona (W)"


def es_femenino(torneo="", local="", visita=""):
    """
    True si hay evidencia positiva de que el partido es femenino.
    Antes se descartaba primero por palabras "masculinas" (bundesliga, serie a, liga mx...),
    lo que eliminaba justo ligas femeninas como "Frauen-Bundesliga", "Serie A Femminile" o
    "Liga MX Femenil". Ahora manda la evidencia femenina.
    """
    if _RE_FEM.search(normalizar(torneo)):
        return True
    for equipo in (local, visita):
        n = normalizar(equipo)
        if _RE_FEM.search(n) or _RE_EQUIPO_W.search(n):
            return True
    return False


def clave_partido(local, visita, start_ts):
    """
    Clave estable para no alertar dos veces el mismo partido que llega de dos fuentes distintas
    (ESPN y API-Sports nombran distinto: se usan los tokens significativos ordenados).
    """
    def firma(nombre):
        toks = sorted(tokens_significativos(nombre))
        return "-".join(toks) if toks else normalizar(nombre).replace(" ", "-")

    dia = ts_a_arg(start_ts).strftime("%Y%m%d") if start_ts else "sinfecha"
    return f"{firma(local)}|{firma(visita)}|{dia}"


# ---------------------------------------------------------------------------
# HISTORIAL, H2H Y TABLA UNIFICADOS (prueban varias fuentes en orden)
# ---------------------------------------------------------------------------
def historial_desde_fuentes(evento, lado, fuente_espn, fuente_highlightly, fuente_oddspapi, fuente_api_football):
    """
    Historial de un equipo (`lado` = "local" o "visita") en formato interno, o [].
    Orden: 1) la fuente de la que vino el evento (ESPN, API-Sports, Highlightly u OddsPapi);
    2) Highlightly buscando el equipo por nombre (los ids se reescriben a los del evento).
    """
    fuente = evento.get("fuente")
    propias = {"espn": fuente_espn, "api_sports": fuente_api_football,
               "highlightly": fuente_highlightly, "oddspapi": fuente_oddspapi}
    modulo = propias.get(fuente)
    if modulo is not None and hasattr(modulo, "historial_equipo"):
        try:
            partidos = modulo.historial_equipo(evento, lado)
            if partidos:
                return partidos
        except Exception as e:
            log(f"[historial] {fuente} fallÃ³ para {evento.get('id')}: {type(e).__name__}")

    if fuente != "highlightly" and fuente_highlightly and fuente_highlightly.disponible():
        try:
            equipo = evento.get(lado) or {}
            if equipo.get("nombre"):
                partidos = fuente_highlightly.obtener_forma_reciente(
                    equipo["nombre"], evento.get("deporte", "Soccer"), limite=6, id_interno=equipo.get("id")
                )
                if partidos:
                    return partidos
        except Exception as e:
            log(f"[historial] Highlightly fallÃ³ para {evento.get('id')}: {type(e).__name__}")

    return []


def h2h_desde_fuentes(evento, hist_local, hist_visita, fuente_highlightly, fuente_oddspapi, id_visita):
    """
    H2H entre local y visita en formato interno, o []. Orden:
    1) los cruces que ya estÃ¡n en el historial del local;
    2) Highlightly (por ids propios si el evento viene de ahÃ­, si no por nombre; ids reescritos al evento);
    3) OddsPapi (solo eventos de OddsPapi y con ODDSPAPI_PROFUNDIDAD=1).
    """
    h2h_local = [p for p in hist_local if id_visita and id_visita in (p.get("id_local"), p.get("id_visita"))]
    if h2h_local:
        return h2h_local

    if fuente_highlightly and fuente_highlightly.disponible():
        try:
            loc, vis = evento["local"], evento["visita"]
            ids_hl = (loc["id"], vis["id"]) if evento.get("fuente") == "highlightly" else None
            h2h = fuente_highlightly.obtener_h2h(
                loc["nombre"], vis["nombre"], evento.get("deporte", "Soccer"),
                id_local=loc["id"], id_visita=vis["id"], ids_hl=ids_hl,
            )
            if h2h:
                return h2h
        except Exception as e:
            log(f"[h2h] Highlightly fallÃ³: {type(e).__name__}")

    if fuente_oddspapi and fuente_oddspapi.disponible():
        try:
            h2h = fuente_oddspapi.obtener_h2h(evento)
            if h2h:
                return h2h
        except Exception as e:
            log(f"[h2h] OddsPapi fallÃ³: {type(e).__name__}")

    return []


def tabla_desde_fuentes(evento, fuente_highlightly):
    """
    Tabla de posiciones de la liga del partido: devuelve ({id_local: fila, id_visita: fila}, n_equipos)
    con los ids del EVENTO, o (None, 0). Solo Highlightly tiene tablas (OddsPapi no tiene ese endpoint).
    """
    if not (fuente_highlightly and fuente_highlightly.disponible()):
        return None, 0
    try:
        loc, vis = evento["local"], evento["visita"]
        ids_hl = (loc["id"], vis["id"]) if evento.get("fuente") == "highlightly" else None
        res = fuente_highlightly.obtener_tabla_partido(
            loc["nombre"], vis["nombre"], evento.get("deporte", "Soccer"), ids_hl=ids_hl
        )
    except Exception as e:
        log(f"[tabla] Highlightly fallÃ³: {type(e).__name__}")
        return None, 0
    if not res:
        return None, 0
    return {loc["id"]: res["local"], vis["id"]: res["visita"]}, res.get("n_equipos", 0)
