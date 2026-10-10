"""
utilidades.py
Funciones compartidas por todo el radar:
- Hora de Argentina (zona horaria real, no la del servidor).
- Logging y estadísticas por fuente (cuántas respuestas 200 / 403 / errores).
- HTTP con manejo de errores visible (nada falla en silencio).
- Cache con vencimiento.
- Persistencia de partidos ya vistos (Upstash Redis o archivo en DATA_DIR).
- Normalización y comparación de nombres de equipos / jugadoras.
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
    # Sin tzdata: Argentina es UTC-3 todo el año (no tiene horario de verano).
    TZ_ARG = timezone(timedelta(hours=-3))


# ---------------------------------------------------------------------------
# HORA
# ---------------------------------------------------------------------------
def ahora_arg():
    return datetime.now(TZ_ARG)


def fecha_arg(dias=0):
    """Fecha YYYY-MM-DD en hora argentina (con desplazamiento opcional en días)."""
    return (ahora_arg() + timedelta(days=dias)).strftime("%Y-%m-%d")


def ts_a_arg(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(TZ_ARG)


def ts_a_iso_utc(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def formatear_hora_arg(ts):
    return ts_a_arg(ts).strftime("%d/%m %H:%M hs (ARG)")


def log(msg):
    print(f"[{ahora_arg().strftime('%d/%m %H:%M:%S')}] {msg}", flush=True)


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

ESTADISTICAS = defaultdict(lambda: defaultdict(int))
_lock = threading.Lock()


def reiniciar_estadisticas():
    with _lock:
        ESTADISTICAS.clear()


def _registrar(fuente, codigo):
    with _lock:
        ESTADISTICAS[fuente][codigo] += 1


def get_json(url, fuente, headers=None, params=None, timeout=12, proxies=None, info=None):
    r = None
    # Intento 1: Emulación de navegador TLS real
    try:
        from curl_cffi import requests as curl_requests
        r = curl_requests.get(
            url,
            headers=headers or HEADERS_NAVEGADOR,
            params=params,
            timeout=timeout,
            impersonate="chrome124"
        )
    except Exception as e_curl:
        # Intento 2: Fallback estándar
        try:
            r = requests.get(
                url,
                headers=headers or HEADERS_NAVEGADOR,
                params=params,
                timeout=timeout
            )
        except requests.RequestException as e:
            _registrar(fuente, "error_red")
            log(f"[{fuente}] error_red: {type(e).__name__} en {url.split('?')[0]} (curl error: {e_curl})")
            return None

    if r is None:
        _registrar(fuente, "error_red")
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
        log(f"[{fuente}] respuesta no es JSON en {url.split('?')[0]}")
        return None

    try:
        return r.json()
    except ValueError:
        _registrar(fuente, "json_invalido")
        log(f"[{fuente}] respuesta no es JSON en {url.split('?')[0]}")
        return None


def get_texto(url, fuente, headers=None, params=None, timeout=15):
    """Igual que get_json pero devuelve el texto crudo (CSV, RSS, etc.)."""
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
        """Devuelve (acierto, valor). Permite cachear también None / listas vacías."""
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
# PERSISTENCIA (Upstash Redis gratis, o archivo en DATA_DIR / Render Disk)
# ---------------------------------------------------------------------------
DATA_DIR = os.environ.get("DATA_DIR", ".")
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")


def usa_upstash():
    return bool(UPSTASH_URL and UPSTASH_TOKEN)


def persistencia_es_duradera():
    return usa_upstash() or ("DATA_DIR" in os.environ)


def modo_persistencia():
    if usa_upstash():
        return "Upstash Redis"
    if "DATA_DIR" in os.environ:
        return f"archivo en {DATA_DIR}"
    return "archivo local (se pierde al reiniciar/deployar)"


def _upstash(comando):
    r = requests.post(
        UPSTASH_URL,
        headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
        json=comando,
        timeout=8,
    )
    r.raise_for_status()
    return r.json().get("result")


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
    """Descarta entradas {clave: iso_timestamp} más viejas que `dias`."""
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    limpio = {}
    for clave, valor in diccionario.items():
        f = _parsear_iso(valor)
        if f is not None and f >= limite:
            limpio[clave] = valor
    return limpio


class RegistroVistos:
    """
    Partidos ya analizados / notificados. Guarda {id: fecha} y descarta lo viejo
    para que el archivo no crezca indefinidamente. Lee el formato viejo (lista).
    """

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
    """
    True si los nombres son compatibles: los tokens significativos de uno están
    incluidos en el otro ("Swiatek I." ~ "Iga Swiatek", "Real Madrid W" ~ "Real Madrid").
    """
    ta, tb = tokens_significativos(a), tokens_significativos(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta
