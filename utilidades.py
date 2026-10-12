"""
utilidades.py
Funciones compartidas por todo el radar:
- Hora de Argentina (zona horaria real, no la del servidor).
- Logging y estadísticas por fuente (cuántas respuestas 200 / 403 / errores).
- HTTP con manejo de errores visible (nada falla en silencio), con soporte de proxy.
- Cache con vencimiento.
- Persistencia de partidos ya vistos (Upstash Redis o archivo en DATA_DIR).
- Normalización y comparación de nombres de equipos / jugadoras.
- Redacción automática de claves y tokens en los logs.
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


_RE_SECRETO = re.compile(
    r"(?i)\b(api[_-]?key|apikey|key|token|access_token|x-apisports-key|x-rapidapi-key)=([^&\s\'\"<>]+)"
)
_RE_BOT_TELEGRAM = re.compile(r"/bot\d{5,}:[A-Za-z0-9_-]{20,}")


def redactar(texto):
    """Oculta claves y tokens que puedan aparecer en URLs o mensajes de error."""
    texto = _RE_SECRETO.sub(lambda m: f"{m.group(1)}=***", str(texto))
    return _RE_BOT_TELEGRAM.sub("/bot***", texto)


def log(msg):
    print(f"[{ahora_arg().strftime('%d/%m %H:%M:%S')}] {redactar(msg)}", flush=True)


if curl_requests is None:
    log(f"[http] curl_cffi no disponible ({_ERROR_IMPORT_CURL}); uso requests")


# ---------------------------------------------------------------------------
# HTTP + ESTADÍSTICAS POR FUENTE
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
                log(f"[{fuente}] curl_cffi falló ({type(e_curl).__name__}: {str(e_curl)[:120]}); uso requests")
            if "timeout" in type(e_curl).__name__.lower() or "timed out" in str(e_curl).lower():
                _registrar(fuente, "error_red")
                return None
    try:
        return requests.get(url, headers=base, params=params, timeout=timeout, proxies=proxies)
    except requests.RequestException as e:
        _registrar(fuente, "error_red")
        log(f"[{fuente}] error_red: {type(e).__name__} en {url.split('?')[0]}")
        return None


ESTADOS_TRANSITORIOS = (502, 503, 504)


def get_json(url, fuente, headers=None, params=None, timeout=12, proxies=None, info=None, reintentar=True):
    r = _pedir(url, headers, params, timeout, proxies, fuente)
    if reintentar and r is not None and r.status_code in ESTADOS_TRANSITORIOS:
        _registrar(fuente, r.status_code)
        log(f"[{fuente}] HTTP {r.status_code} transitorio en {url.split('?')[0]}; un reintento")
        time.sleep(1.5)
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
        if item and time.time() < item[2]:
            return True, item[1]
        return False, None

    def set(self, clave, valor, ttl=None):
        ahora = time.time()
        self._datos[clave] = (ahora, valor, ahora + (self.ttl if ttl is None else ttl))
        if len(self._datos) > 2000:
            self.limpiar()

    def limpiar(self):
        ahora = time.time()
        self._datos = {k: v for k, v in self._datos.items() if ahora < v[2]}


# ---------------------------------------------------------------------------
# PERSISTENCIA (Upstash Redis o archivo en DATA_DIR)
# ---------------------------------------------------------------------------
DATA_DIR = os.environ.get("DATA_DIR", ".")
UPSTASH_URL = (os.environ.get("UPSTASH_REDIS_REST_URL") or "").strip()
UPSTASH_TOKEN = (os.environ.get("UPSTASH_REDIS_REST_TOKEN") or "").strip()
_UPSTASH_ULTIMO_OK = None


def usa_upstash():
    return bool(UPSTASH_URL and UPSTASH_TOKEN)


def persistencia_es_duradera():
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
            log(f"[persistencia] Upstash GET falló ({type(e).__name__}); uso archivo")
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
            log(f"[persistencia] Upstash SET falló ({type(e).__name__}); uso archivo")
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
# PRESUPUESTO DIARIO DE REQUESTS (APIs con cuota, p. ej. API-Sports 100/día)
# ---------------------------------------------------------------------------
class PresupuestoDiario:
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


class PresupuestoMultiple:
    def __init__(self, nombre, mensual, semanal=None, diario=None, reserva_mensual=0):
        self.nombre = nombre
        self.mensual = max(1, int(mensual))
        self.reserva = max(0, int(reserva_mensual))
        self.semanal = max(1, int(semanal)) if semanal else max(1, -(-self.mensual * 7 // 31))
        self.diario = max(1, int(diario)) if diario else None
        self.agotado = {"dia": None, "mes": None}
        self._lock = threading.RLock()
        crudo = cargar_json(f"presupuesto_{nombre}_multi.json", {})
        self.claves = self._claves()
        self.d = self.s = self.m = 0
        if isinstance(crudo, dict):
            try:
                if crudo.get("mes") == self.claves["mes"]:
                    self.m = max(0, int(crudo.get("m", 0)))
                if crudo.get("semana") == self.claves["semana"]:
                    self.s = max(0, int(crudo.get("s", 0)))
                if crudo.get("dia") == self.claves["dia"]:
                    self.d = max(0, int(crudo.get("d", 0)))
            except (TypeError, ValueError):
                self.d = self.s = self.m = 0

    @staticmethod
    def _ahora():
        return datetime.now(timezone.utc)

    def _claves(self):
        ahora = self._ahora()
        iso = ahora.isocalendar()
        return {"dia": ahora.strftime("%Y-%m-%d"), "semana": f"{iso[0]}-W{iso[1]:02d}", "mes": ahora.strftime("%Y-%m")}

    def _rotar(self):
        nuevas = self._claves()
        if nuevas["mes"] != self.claves["mes"]:
            self.m = 0
        if nuevas["semana"] != self.claves["semana"]:
            self.s = 0
        if nuevas["dia"] != self.claves["dia"]:
            self.d = 0
        self.claves = nuevas

    def _dias_del_mes(self):
        ahora = self._ahora()
        siguiente = (ahora.replace(day=28) + timedelta(days=4)).replace(day=1)
        return (siguiente - ahora.replace(day=1)).days

    def _dias_restantes_mes(self):
        ahora = self._ahora()
        siguiente = (ahora.replace(day=28) + timedelta(days=4)).replace(day=1)
        return max(1, (siguiente - ahora.replace(hour=0, minute=0, second=0, microsecond=0)).days)

    @property
    def usadas(self):
        with self._lock:
            self._rotar()
            return self.d

    @property
    def limite(self):
        return self.diario or self.mensual

    def permitido_ahora(self):
        with self._lock:
            self._rotar()
            if self.agotado["dia"] == self.claves["dia"] or self.agotado["mes"] == self.claves["mes"]:
                return 0
            disponible_mes = self.mensual - self.reserva - self.m
            if disponible_mes <= 0:
                return 0
            ritmo_hoy = -(-(disponible_mes + self.d) // self._dias_restantes_mes())
            parejo = -(-(self.mensual - self.reserva) // self._dias_del_mes())
            ritmo_hoy = min(ritmo_hoy, -(-parejo * 3 // 2))
            topes = [ritmo_hoy - self.d, self.semanal - self.s, disponible_mes]
            if self.diario:
                topes.append(self.diario - self.d)
            return max(0, min(topes))

    def puede_gastar(self, n=1):
        return self.permitido_ahora() >= n

    def registrar(self, n=1):
        with self._lock:
            self._rotar()
            self.d += n
            self.s += n
            self.m += n
            self._guardar()

    def marcar_agotado(self, periodo="dia"):
        with self._lock:
            self._rotar()
            self.agotado[periodo] = self.claves[periodo]

    def _guardar(self):
        guardar_json(f"presupuesto_{self.nombre}_multi.json", {
            "dia": self.claves["dia"], "semana": self.claves["semana"], "mes": self.claves["mes"],
            "d": self.d, "s": self.s, "m": self.m,
        })

    def resumen(self):
        with self._lock:
            self._rotar()
            tope_d = self.diario or "-"
            return (f"hoy {self.d}/{tope_d}, semana {self.s}/{self.semanal}, "
                    f"mes {self.m}/{self.mensual - self.reserva}")


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
    "fem", "femenino", "femenina", "femenil", "femeni", "feminino", "feminina",
    "feminin", "feminine", "femminile", "damen", "frauen",
    "del", "los", "las", "cd", "ud",
}


def tokens_significativos(texto):
    return {t for t in normalizar(texto).split() if len(t) >= 3 and t not in _PALABRAS_RUIDO}


def nombres_coinciden(a, b):
    if categoria_equipo(a) != categoria_equipo(b):
        return False
    ta, tb = tokens_significativos(a), tokens_significativos(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta


def categoria_equipo(nombre):
    """Preserva juveniles y reservas al resolver nombres entre proveedores."""
    n = normalizar(nombre)
    edades = re.findall(r"\b(?:u|sub|under)\s*(\d{2})\b", n)
    reserva = bool(re.search(r"\b(?:ii|b|reserves?|reservas?|juniores|juniors)\b", n))
    return tuple(sorted(edades)), reserva


def participante_definido(nombre):
    n = normalizar(nombre)
    return bool(n) and n not in {"tbd", "tba", "unknown", "a confirmar", "por definir", "local", "visitante"} and not re.search(r"\b(?:winner|loser|ganador|perdedor)\b", n)


# ---------------------------------------------------------------------------
# FILTRO FEMENINO COMPARTIDO
# ---------------------------------------------------------------------------
_RE_FEM = re.compile(
    r"\b(women|womens|woman|wom|female|femenino|femenina|femenil|femeni|feminino|feminina|"
    r"feminin|feminine|femminile|fem|frauen|damen|dames|ladies|vrouwen|kvinde\w*|kvinnor|"
    r"damallsvenskan|toppserien|wta|wnba|wnbl|pwhl|aflw|nrlw|wbbl|nwsl|wsl|itf w|we league|liga f|"
    r"w\s?(15|25|35|50|60|75|80|100))\b"
)
_RE_EQUIPO_W = re.compile(r"\bw$")


def es_femenino(torneo="", local="", visita=""):
    if _RE_FEM.search(normalizar(torneo)):
        return True
    for equipo in (local, visita):
        n = normalizar(equipo)
        if _RE_FEM.search(n) or _RE_EQUIPO_W.search(n):
            return True
    return False


def firma_equipo(nombre):
    toks = sorted(tokens_significativos(nombre))
    base = "-".join(toks) if toks else normalizar(nombre).replace(" ", "-")
    edades, reserva = categoria_equipo(nombre)
    return base + ("|cat:" + ",".join(edades) if edades else "") + ("|reserva" if reserva else "")


def firma_partido(local, visita):
    a, b = sorted((firma_equipo(local), firma_equipo(visita)))
    return f"{a}|{b}"


def clave_partido(local, visita, start_ts):
    dia = ts_a_arg(start_ts).strftime("%Y%m%d") if start_ts else "sinfecha"
    return f"{firma_equipo(local)}|{firma_equipo(visita)}|{dia}"


# ---------------------------------------------------------------------------
# HISTORIAL, H2H Y TABLA UNIFICADOS
# ---------------------------------------------------------------------------
MIN_HISTORIAL_UTIL = 4


def historial_desde_fuentes(evento, lado, fuente_espn, fuente_highlightly, fuente_oddspapi,
                            fuente_api_football, fuente_thesportsdb=None, modo="todo"):
    fuente = evento.get("fuente")
    propias = {"espn": fuente_espn, "api_sports": fuente_api_football, "highlightly": fuente_highlightly,
               "oddspapi": fuente_oddspapi, "thesportsdb": fuente_thesportsdb}
    mejor = []
    equipo = evento.get(lado) or {}
    deporte = evento.get("deporte", "Soccer")

    def suficiente(partidos):
        nonlocal mejor
        if partidos and len(partidos) > len(mejor):
            mejor = partidos
        return len(mejor) >= MIN_HISTORIAL_UTIL

    modulo = propias.get(fuente) if modo in ("propia", "todo") else None
    if modulo is not None and hasattr(modulo, "historial_equipo"):
        try:
            if suficiente(modulo.historial_equipo(evento, lado)):
                return mejor
        except Exception as e:
            log(f"[historial] {fuente} falló para {evento.get('id')}: {type(e).__name__}")

    por_nombre = modo in ("nombre", "todo")
    if por_nombre and fuente != "thesportsdb" and fuente_thesportsdb and equipo.get("nombre"):
        try:
            if hasattr(fuente_thesportsdb, "historial_disponible") and fuente_thesportsdb.historial_disponible():
                if suficiente(fuente_thesportsdb.obtener_forma_reciente(
                        equipo["nombre"], deporte, limite=8, id_interno=equipo.get("id"))):
                    return mejor
        except Exception as e:
            log(f"[historial] TheSportsDB falló para {evento.get('id')}: {type(e).__name__}")

    if por_nombre and fuente != "highlightly" and fuente_highlightly and fuente_highlightly.disponible():
        try:
            if equipo.get("nombre"):
                if suficiente(fuente_highlightly.obtener_forma_reciente(
                        equipo["nombre"], deporte, limite=6, id_interno=equipo.get("id"))):
                    return mejor
        except Exception as e:
            log(f"[historial] Highlightly falló para {evento.get('id')}: {type(e).__name__}")

    return mejor


def h2h_desde_fuentes(evento, hist_local, hist_visita, fuente_highlightly, fuente_oddspapi, id_visita, libro_resultados=None):
    h2h_local = [p for p in (hist_local or []) if id_visita and id_visita in (p.get("id_local"), p.get("id_visita"))]
    if h2h_local:
        return h2h_local

    loc, vis = evento.get("local") or {}, evento.get("visita") or {}
    nom_loc, nom_vis = loc.get("nombre", ""), vis.get("nombre", "")

    if libro_resultados and nom_loc and nom_vis:
        try:
            h2h_libro = libro_resultados.h2h_equipos(evento.get("deporte", "Soccer"), nom_loc, nom_vis, loc.get("id"), vis.get("id"))
            if h2h_libro:
                return h2h_libro
        except Exception as e:
            log(f"[h2h] libro_resultados fallo: {type(e).__name__}")

    if fuente_highlightly and fuente_highlightly.disponible():
        try:
            ids_hl = (loc["id"], vis["id"]) if evento.get("fuente") == "highlightly" else None
            h2h = fuente_highlightly.obtener_h2h(
                nom_loc, nom_vis, evento.get("deporte", "Soccer"),
                id_local=loc.get("id"), id_visita=vis.get("id"), ids_hl=ids_hl,
            )
            if h2h:
                return h2h
        except Exception as e:
            log(f"[h2h] Highlightly falló: {type(e).__name__}")

    if fuente_oddspapi and fuente_oddspapi.disponible():
        try:
            h2h = fuente_oddspapi.obtener_h2h(evento)
            if h2h:
                return h2h
        except Exception as e:
            log(f"[h2h] OddsPapi falló: {type(e).__name__}")

    return []


def tabla_desde_fuentes(evento, fuente_highlightly):
    if not (fuente_highlightly and fuente_highlightly.disponible()):
        return None, 0
    try:
        loc, vis = evento["local"], evento["visita"]
        ids_hl = (loc["id"], vis["id"]) if evento.get("fuente") == "highlightly" else None
        res = fuente_highlightly.obtener_tabla_partido(
            loc["nombre"], vis["nombre"], evento.get("deporte", "Soccer"), ids_hl=ids_hl,
            liga_ref=evento.get("liga_ref") if evento.get("fuente") == "highlightly" else None
        )
    except Exception as e:
        log(f"[tabla] Highlightly falló: {type(e).__name__}")
        return None, 0
    if not res:
        return None, 0
    return {loc["id"]: res["local"], vis["id"]: res["visita"]}, res.get("n_equipos", 0)
