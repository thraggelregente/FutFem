"""Cliente limitado para fuentes oficiales públicas, separado de planes con cuota."""
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests
import utilidades as U


class PresupuestoVentana:
    """Contador persistente de 24 h; no se reinicia al cambiar el día UTC."""
    ventana_horas = 24

    def __init__(self, nombre, limite, reserva=0):
        self.nombre, self.limite, self.reserva = nombre, int(limite), int(reserva)
        self.archivo = "presupuesto_" + nombre + "_24h.json"
        crudo = U.cargar_json(self.archivo, None)
        self.pedidos = crudo if isinstance(crudo, list) else []
        if crudo is None:
            # Al migrar, conservar de forma conservadora el consumo del contador anterior.
            anterior = U.cargar_json("presupuesto_" + nombre + ".json", {})
            try:
                fecha = datetime.fromisoformat(anterior.get("fecha", "")).replace(tzinfo=timezone.utc).timestamp()
                cantidad = max(0, int(anterior.get("usadas", 0)))
                if time.time() - 2 * 86400 < fecha <= time.time() and cantidad:
                    self.pedidos = [[time.time(), cantidad]]
            except (TypeError, ValueError):
                pass
        self._limpiar()
        U.guardar_json(self.archivo, self.pedidos)

    def _limpiar(self):
        ahora = time.time()
        self.pedidos = [p for p in self.pedidos if isinstance(p, list) and len(p) == 2
                        and isinstance(p[0], (int, float)) and isinstance(p[1], int)
                        and ahora - 86400 < p[0] <= ahora and p[1] > 0]

    @property
    def usadas(self):
        self._limpiar()
        return sum(p[1] for p in self.pedidos)

    def restantes(self):
        return max(0, self.limite - self.reserva - self.usadas)

    def puede_gastar(self, n=1):
        return self.restantes() >= n

    def registrar(self, n=1):
        self._limpiar()
        self.pedidos.append([time.time(), n])
        U.guardar_json(self.archivo, self.pedidos)


class Cliente:
    def __init__(self, nombre, cache, limite=30):
        self.nombre, self.cache = nombre, cache
        self.presupuesto = U.PresupuestoDiario(nombre + "_publica", limite, reserva=2)
        self.ritmo = U.RitmoPedidos(6, minimo_segundos=1)
        self.pausa = 0

    def pedir(self, url, params=None, ttl=6 * 3600, xml=False):
        clave = (url, params or {})
        hit, dato = self.cache.get(clave)
        if hit:
            return dato
        if time.time() < self.pausa or not self.presupuesto.puede_gastar():
            return None
        self.ritmo.esperar()
        self.presupuesto.registrar()
        try:
            r = requests.get(url, params=params, timeout=25)
            U._registrar(self.nombre, r.status_code)
            if r.status_code in (403, 429):
                self.pausa = time.time() + 6 * 3600
            r.raise_for_status()
            if len(r.content) > 8_000_000:
                raise ValueError("respuesta demasiado grande")
            dato = r.text if xml else r.json()
            self.cache.set(clave, dato, ttl=ttl)
            return dato
        except (requests.RequestException, ValueError):
            U.log(f"[{self.nombre}] fuente no disponible o respuesta inválida; no se repite durante una hora")
            self.cache.set(clave, None, ttl=3600)
            return None


def instante_utc(valor):
    """Usar solamente sobre campos declarados UTC por la fuente."""
    fecha = U._parsear_iso(valor)
    return int(fecha.timestamp()) if fecha else 0


def fechas_validas(ts, inicio=None, fin=None):
    if not ts:
        return False
    dia = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
    return (not inicio or str(inicio)[:10] <= dia) and (not fin or dia <= str(fin)[:10])


def enteros(*valores):
    try:
        if any(isinstance(v, bool) or isinstance(v, float) and not v.is_integer() for v in valores):
            return None
        return tuple(int(v) for v in valores)
    except (TypeError, ValueError):
        return None


def xml_seguro(texto):
    if not texto or "<!DOCTYPE" in texto.upper() or "<!ENTITY" in texto.upper():
        return None
    try:
        return ET.fromstring(texto)
    except ET.ParseError:
        return None
