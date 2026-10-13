"""Historial femenino Cricsheet (ODC-By), sin fixtures ni cuotas comerciales.

Se descarga el archivo del año vigente y el anterior, una vez al día. Sólo se
persisten resultados compactos; género, formato y fecha se validan por partido.
"""
import io
import json
import os
import re
import time
import zipfile
from threading import RLock, Thread
from datetime import datetime, timezone

import requests
import utilidades as U

FUENTE = "cricsheet"
ACTIVO = os.environ.get("CRICSHEET_ACTIVO", "1") != "0"
presupuesto = U.PresupuestoDiario("cricsheet", 4, reserva=0)
class CacheSegura(U.CachePersistente):
    def __init__(self):
        self.lock = RLock()
        super().__init__("cricsheet_resultados_v1", 86400, max_items=6)

    def get(self, clave):
        with self.lock:
            return super().get(clave)

    def set(self, clave, valor, ttl=None):
        with self.lock:
            return super().set(clave, valor, ttl)

    def guardar(self):
        with self.lock:
            return super().guardar()


_cache = CacheSegura()
_pausa = 0
_worker = None
_worker_lock = RLock()


def disponible():
    return ACTIVO


def identidad(nombre):
    # El archivo acredita género femenino; añadirlo evita mezclar con hombres.
    return U.firma_equipo(nombre if U.es_femenino("", nombre, "") else nombre + " Women")


def normalizar(raw, ident, ahora=None):
    ahora = time.time() if ahora is None else ahora
    info = raw.get("info") if isinstance(raw, dict) else None
    if not isinstance(info, dict) or info.get("gender") != "female":
        return None
    formato = {"T20": "T20", "ODI": "ODI", "ODM": "ODI"}.get(info.get("match_type"))
    if not formato or info.get("overs") != (20 if formato == "T20" else 50):
        return None
    equipos, fechas, outcome = info.get("teams"), info.get("dates"), info.get("outcome")
    if not isinstance(equipos, list) or len(equipos) != 2 or not all(isinstance(n, str) and U.participante_definido(n) for n in equipos):
        return None
    if not isinstance(fechas, list) or len(fechas) != 1 or not isinstance(outcome, dict):
        return None
    try:
        dia = datetime.strptime(fechas[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    # Sólo días concluidos: no usar un resultado posterior al inicio del partido.
    if not 0 <= ahora - (dia.timestamp() + 86400) <= 365 * 86400:
        return None
    a, b = (identidad(n) for n in equipos)
    if a == b or outcome.get("winner") not in equipos or outcome.get("method") or outcome.get("result"):
        return None  # DLS, empate/super-over y no-result no son márgenes normales
    by = outcome.get("by") or {}
    if not isinstance(by, dict) or len(by) != 1:
        return None
    unidad, margen = next(iter(by.items()))
    if unidad not in ("runs", "wickets") or isinstance(margen, bool) or not isinstance(margen, int) or margen <= 0:
        return None
    if unidad == "wickets" and margen > 10:
        return None
    evento = info.get("event") or {}
    if not isinstance(evento, dict) or not isinstance(evento.get("name"), str):
        return None
    if U.categoria_equipo(evento["name"]) != ((), False) or any(U.categoria_equipo(n) != ((), False) for n in equipos):
        return None  # no mezclar sub-19/reservas con selecciones mayores
    if any(re.search(r"\bA$", n) for n in equipos):
        return None  # selecciones A no son la selección absoluta
    if info.get("team_type") not in ("international", "club"):
        return None
    return {"id": str(ident), "fecha": fechas[0], "formato": formato,
            "temporada": str(info.get("season") or ""),
            "tipo_equipo": info["team_type"], "competicion": evento["name"],
            "equipos": [a, b], "ganadora": identidad(outcome["winner"]),
            "unidad": unidad, "margen": margen, "fuente": FUENTE}


def leer_zip(contenido, ahora=None):
    if len(contenido) > 12_000_000:
        raise ValueError("archivo demasiado grande")
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        archivos = [i for i in z.infolist() if i.filename.endswith(".json")]
        if len(archivos) > 3000 or sum(i.file_size for i in archivos) > 120_000_000:
            raise ValueError("archivo expandido demasiado grande")
        salida = []
        for i in archivos:
            if i.file_size > 2_000_000:
                raise ValueError("partido demasiado grande")
            p = normalizar(json.loads(z.read(i)), i.filename.rsplit("/", 1)[-1][:-5], ahora)
            if p:
                salida.append(p)
        return salida


def _anio(year):
    global _pausa
    hit, rows = _cache.get(year)
    if hit:
        return rows or []
    if not disponible() or time.time() < _pausa or not presupuesto.puede_gastar():
        return []
    presupuesto.registrar()
    try:
        inicio, partes, total = time.monotonic(), [], 0
        archivo = f"{year}_female_json" if isinstance(year, int) else "recently_played_30_female_json"
        with requests.get(f"https://cricsheet.org/downloads/{archivo}.zip", stream=True, timeout=(10, 15)) as r:
            U._registrar(FUENTE, r.status_code)
            if r.status_code in (403, 429):
                _pausa = time.time() + 6 * 3600
            r.raise_for_status()
            for parte in r.iter_content(65536):
                total += len(parte)
                if total > 12_000_000 or time.monotonic() - inicio > 300:
                    raise ValueError("límite de descarga")
                partes.append(parte)
        rows = leer_zip(b"".join(partes))
        _cache.set(year, rows, ttl=86400)
        _cache.guardar()
        U.log(f"[cricsheet] archivo {year}: {len(rows)} resultados normales femeninos indexados")
        return rows
    except (requests.RequestException, ValueError, zipfile.BadZipFile, KeyError, TypeError):
        _cache.set(year, None, ttl=3600)
        U.log("[cricsheet] archivo no disponible; no se repite durante una hora")
        return []


def _claves_archivos():
    ahora = datetime.now(timezone.utc)
    claves = ["recientes", ahora.year]
    if ahora.timetuple().tm_yday <= 91:
        claves.append(ahora.year-1)  # sólo cuando la ventana de 90 días cruza el año
    return claves


def _actualizar():
    try:
        for clave in _claves_archivos():
            _anio(clave)
    finally:
        _cache.guardar()


def historial(evento):
    global _worker
    if not disponible():
        return []
    claves = _claves_archivos()
    # Archivos grandes no bloquean el radar. Primero carga el paquete reciente.
    with _worker_lock:
        if any(not _cache.get(k)[0] for k in claves) and (_worker is None or not _worker.is_alive()):
            _worker = Thread(target=_actualizar, daemon=True, name="cricsheet-index")
            _worker.start()
    registros = {p["id"]: p for k in claves for p in (_cache.get(k)[1] or [])}
    return list(registros.values())


def estado():
    registros = {p["id"]: p for k in _claves_archivos() for p in (_cache.get(k)[1] or [])}
    return {"resultados_indexados": len(registros), "actualizando": bool(_worker and _worker.is_alive())}
