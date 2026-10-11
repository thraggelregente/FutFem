"""Libro de resultados: memoria persistente de partidos femeninos terminados.

Para qué sirve:
- Memoria persistente deduplicada de resultados terminados.
- Historial por nombre para ligas solo calendario.
- Rating Elo y consulta directa de H2H acumulado.
"""

from __future__ import annotations

import math
import os
import threading
import time
from datetime import datetime, timezone

import utilidades as U

ARCHIVO = "libro_resultados.json"
MAX_PARTIDOS = max(500, int(os.environ.get("LIBRO_MAX_PARTIDOS", "5000")))
DIAS_RETENCION = max(30, int(os.environ.get("LIBRO_DIAS_RETENCION", "150")))
MIN_PARTIDOS_ELO = max(3, int(os.environ.get("ELO_MIN_PARTIDOS", "5")))
ACTIVIDAD_MAX_DIAS = 75
ELO_INICIAL = 1500.0

K_ELO = {"Soccer": 24, "Basketball": 22, "Ice Hockey": 22, "Volleyball": 26, "Handball": 24, "Rugby": 24}
VENTAJA_LOCAL_ELO = {"Soccer": 55, "Basketball": 70, "Ice Hockey": 40, "Volleyball": 45, "Handball": 55, "Rugby": 55}
ESCALA_MARGEN = {"Soccer": 1.0, "Ice Hockey": 1.0, "Volleyball": 1.0, "Basketball": 10.0, "Handball": 4.0, "Rugby": 8.0}
K_DEFECTO, HFA_DEFECTO, ESCALA_DEFECTO = 24, 50, 2.0

_lock = threading.RLock()
_partidos: dict[str, list] = {}
_sucio = {"v": False}
_version = {"n": 0}
_cache_elo: dict[str, tuple[int, dict]] = {}


def _clave(deporte, fl, fv, ts):
    a, b = sorted((fl, fv))
    dia = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%d")
    return f"{deporte}|{a}|{b}|{dia}", dia


def _cargar():
    crudo = U.cargar_json(ARCHIVO, {})
    lista = crudo.get("p") if isinstance(crudo, dict) else None
    if not isinstance(lista, list):
        return
    limite = time.time() - DIAS_RETENCION * 86400
    for fila in lista:
        try:
            ts, deporte, fl, fv, nl, nv, pl, pv = fila
            ts, pl, pv = int(ts), int(pl), int(pv)
        except (TypeError, ValueError):
            continue
        if ts < limite or not fl or not fv:
            continue
        clave, _ = _clave(deporte, fl, fv, ts)
        _partidos[clave] = [ts, deporte, fl, fv, str(nl)[:40], str(nv)[:40], pl, pv]
    if _partidos:
        U.log(f"[libro] {len(_partidos)} resultados cargados")


_cargar()


def _a_ts(fecha):
    if isinstance(fecha, (int, float)):
        return int(fecha)
    f = U._parsear_iso(fecha)
    return int(f.timestamp()) if f else 0


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def ingestar(deporte, partidos, fuente=""):
    nuevos = 0
    try:
        ahora = time.time()
        limite = ahora - DIAS_RETENCION * 86400
        with _lock:
            for p in partidos or []:
                ts = _a_ts(p.get("fecha", ""))
                pl, pv = _entero(p.get("puntos_local")), _entero(p.get("puntos_visita"))
                nl, nv = str(p.get("nom_local") or "").strip(), str(p.get("nom_visita") or "").strip()
                if not ts or ts >= ahora or ts < limite or pl is None or pv is None or not nl or not nv:
                    continue
                fl, fv = U.firma_equipo(nl), U.firma_equipo(nv)
                if not fl or not fv or fl == fv:
                    continue
                clave, _ = _clave(deporte, fl, fv, ts)
                if any(
                    (e := _partidos.get(_clave(deporte, fl, fv, ts + d)[0])) is not None and abs(e[0] - ts) <= 10 * 3600
                    for d in (0, -86400, 86400)
                ):
                    continue
                _partidos[clave] = [ts, deporte, fl, fv, nl[:40], nv[:40], pl, pv]
                nuevos += 1
            if nuevos:
                _sucio["v"] = True
                _version["n"] += 1
    except Exception as exc:
        U.log(f"[libro] error ingestando de {fuente or '?'}: {type(exc).__name__}")
    return nuevos


def guardar():
    with _lock:
        if not _sucio["v"]:
            return False
        limite = time.time() - DIAS_RETENCION * 86400
        for clave in [k for k, v in _partidos.items() if v[0] < limite]:
            del _partidos[clave]
        if len(_partidos) > MAX_PARTIDOS:
            ordenadas = sorted(_partidos.items(), key=lambda kv: kv[1][0], reverse=True)[:MAX_PARTIDOS]
            _partidos.clear()
            _partidos.update(ordenadas)
        cargados = {"v": 1, "p": [fila for fila in _partidos.values()]}
        if U.guardar_json(ARCHIVO, cargados):
            _sucio["v"] = False
            return True
        return False


def total():
    with _lock:
        return len(_partidos)


def _partidos_de(deporte, firma):
    return sorted(
        (v for v in _partidos.values() if v[1] == deporte and firma in (v[2], v[3])),
        key=lambda v: v[0], reverse=True,
    )


def historial_equipo(evento, lado, limite=10):
    equipo = evento.get(lado) or {}
    nombre, deporte = equipo.get("nombre"), evento.get("deporte")
    if not nombre or not deporte:
        return []
    firma = U.firma_equipo(nombre)
    id_evento = str(equipo.get("id") if equipo.get("id") is not None else f"lib:{firma}")
    with _lock:
        filas = _partidos_de(deporte, firma)[:max(1, int(limite))]
    salida = []
    for ts, _dep, fl, fv, nl, nv, pl, pv in filas:
        salida.append({
            "fecha": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
            "id_local": id_evento if fl == firma else f"lib:{fl}", "nom_local": nl,
            "id_visita": id_evento if fv == firma else f"lib:{fv}", "nom_visita": nv,
            "puntos_local": pl, "puntos_visita": pv,
        })
    return salida


def h2h_equipos(deporte, nombre_local, nombre_visita, id_local=None, id_visita=None):
    fl, fv = U.firma_equipo(nombre_local), U.firma_equipo(nombre_visita)
    if not fl or not fv or fl == fv:
        return []
    with _lock:
        filas = sorted(
            (v for v in _partidos.values() if v[1] == deporte and {fl, fv} == {v[2], v[3]}),
            key=lambda v: v[0], reverse=True
        )
    salida = []
    id_loc_out = str(id_local) if id_local is not None else f"lib:{fl}"
    id_vis_out = str(id_visita) if id_visita is not None else f"lib:{fv}"
    for ts, _dep, fl_part, fv_part, nl, nv, pl, pv in filas:
        es_local_actual = (fl_part == fl)
        salida.append({
            "fecha": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
            "id_local": id_loc_out if es_local_actual else id_vis_out,
            "nom_local": nl,
            "id_visita": id_vis_out if es_local_actual else id_loc_out,
            "nom_visita": nv,
            "puntos_local": pl,
            "puntos_visita": pv,
        })
    return salida


def tiene_historial(evento, minimo=4):
    deporte = evento.get("deporte")
    firmas = []
    for lado in ("local", "visita"):
        nombre = (evento.get(lado) or {}).get("nombre")
        if not nombre or not deporte:
            return False
        firmas.append(U.firma_equipo(nombre))
    with _lock:
        return all(len(_partidos_de(deporte, f)) >= minimo for f in firmas)


def _esperado(r_a, r_b, ventaja):
    return 1.0 / (1.0 + 10 ** (-(r_a - r_b + ventaja) / 400.0))


def _recalcular(deporte):
    with _lock:
        hit = _cache_elo.get(deporte)
        if hit and hit[0] == _version["n"]:
            return hit[1]
        filas = sorted((v for v in _partidos.values() if v[1] == deporte), key=lambda v: v[0])
        k_base = K_ELO.get(deporte, K_DEFECTO)
        hfa = VENTAJA_LOCAL_ELO.get(deporte, HFA_DEFECTO)
        escala = ESCALA_MARGEN.get(deporte, ESCALA_DEFECTO)
        rating, juegos, ultimo, padre = {}, {}, {}, {}

        def raiz(x):
            while padre.setdefault(x, x) != x:
                padre[x] = padre[padre[x]]
                x = padre[x]
            return x

        for ts, _dep, fl, fv, _nl, _nv, pl, pv in filas:
            rl, rv = rating.get(fl, ELO_INICIAL), rating.get(fv, ELO_INICIAL)
            esperado_l = _esperado(rl, rv, hfa)
            resultado_l = 1.0 if pl > pv else (0.0 if pl < pv else 0.5)
            margen = abs(pl - pv) / escala
            mult = min(3.0, 1.0 + math.log1p(margen)) if pl != pv else 1.0
            delta = k_base * mult * (resultado_l - esperado_l)
            rating[fl], rating[fv] = rl + delta, rv - delta
            juegos[fl] = juegos.get(fl, 0) + 1
            juegos[fv] = juegos.get(fv, 0) + 1
            ultimo[fl] = ultimo[fv] = ts
            padre[raiz(fl)] = raiz(fv)
        resultado = {"rating": rating, "juegos": juegos, "ultimo": ultimo,
                     "componente": {e: raiz(e) for e in rating}, "hfa": hfa}
        _cache_elo[deporte] = (_version["n"], resultado)
        return resultado


def consulta_elo(deporte, nombre_local, nombre_visita):
    if not deporte or not nombre_local or not nombre_visita:
        return None
    datos = _recalcular(deporte)
    fl, fv = U.firma_equipo(nombre_local), U.firma_equipo(nombre_visita)
    if fl not in datos["rating"] or fv not in datos["rating"]:
        return None
    if datos["juegos"][fl] < MIN_PARTIDOS_ELO or datos["juegos"][fv] < MIN_PARTIDOS_ELO:
        return None
    if datos["componente"][fl] != datos["componente"][fv]:
        return None
    limite = time.time() - ACTIVIDAD_MAX_DIAS * 86400
    if datos["ultimo"][fl] < limite or datos["ultimo"][fv] < limite:
        return None
    rl, rv = datos["rating"][fl], datos["rating"][fv]
    return {
        "elo_local": round(rl), "elo_visita": round(rv),
        "p_local": round(_esperado(rl, rv, datos["hfa"]), 4),
        "n_local": datos["juegos"][fl], "n_visita": datos["juegos"][fv],
    }
