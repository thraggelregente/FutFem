"""Respaldo gratuito SportScore para fútbol femenino; cobertura parcial por página.

API pública documentada. La atribución visible se conserva en Telegram. No se
consulta el feed suspendido ni se afirma equivalencia con toda API-Sports.
"""
import os
import re
import time
from datetime import datetime, timedelta, timezone

import utilidades as U
from fuentes_publicas import Cliente, PresupuestoVentana, enteros

FUENTE = "sportscore"
ACTIVO = os.environ.get("SPORTSCORE_ACTIVO", "1") != "0"
_cache = U.CachePersistente("sportscore_v1", 6 * 3600, max_items=4096)
cliente = Cliente(FUENTE, _cache, limite=1000)
cliente.presupuesto = PresupuestoVentana("sportscore_publica", max(1, min(10000, int(os.environ.get("SPORTSCORE_LIMIT_24H", "9800")))))
cliente.ritmo = U.RitmoPedidos(30, minimo_segundos=1)
presupuesto = cliente.presupuesto
BASE = "https://sportscore.com"


def disponible():
    return ACTIVO


def normalizar(raw, ahora=None):
    if not isinstance(raw, dict) or not isinstance(raw.get("competition", ""), str):
        return None
    ahora = time.time() if ahora is None else ahora
    a, b, liga = raw.get("home", ""), raw.get("away", ""), raw.get("competition", "")
    if not all(isinstance(n, str) and U.participante_definido(n) for n in (a, b)):
        return None
    femenino = U.es_femenino(liga, "", "") or (U.es_femenino("", a, "") and U.es_femenino("", b, ""))
    if not femenino:
        return None
    fecha = str(raw.get("time") or "")
    # El contrato es datetime con zona: rechazar fecha sola o zona ausente.
    if not re.search(r"T\d{2}:\d{2}.*(?:Z|[+-]\d{2}:\d{2})$", fecha):
        return None
    f = U._parsear_iso(fecha)
    if not f:
        return None
    ts = f.timestamp()
    edades = re.findall(r"\bU[ -]?(\d{2})\b", liga, re.I)
    if edades:
        if U.categoria_equipo(a)[0] == ():
            a += " U" + edades[0]
        if U.categoria_equipo(b)[0] == ():
            b += " U" + edades[0]
    contexto = "sportscore:Soccer:" + U.normalizar(liga)
    local = {"id": "ss:" + U.firma_equipo(a), "nombre": a, "busqueda_nombre": raw["home"]}
    visita = {"id": "ss:" + U.firma_equipo(b), "nombre": b, "busqueda_nombre": raw["away"]}
    if local["id"] == visita["id"]:
        return None
    comunes = {"fuente": FUENTE, "deporte": "Soccer", "torneo": liga, "historial_aislado": True,
               "contexto_competicion": contexto, "femenino_seguro": True, "local": local, "visita": visita,
               "startTimestamp": int(ts)}
    if raw.get("status") == "upcoming" and ahora < ts <= ahora + 86400:
        url = str(raw.get("url", ""))
        if not re.fullmatch(r"/football/match/[-a-z0-9]+/[-a-z0-9]+/?", url):
            return None
        if f.hour == 0 and f.minute == 0:
            return None  # precisión de medianoche no confirmada en este contrato
        return dict(comunes, id="ss_" + url.rstrip("/").rsplit("/", 1)[-1],
                    tipo_estado="pre", horario=U.formatear_hora_arg(ts))
    scores = enteros(raw.get("home_score"), raw.get("away_score"))
    if raw.get("status") != "finished" or not scores or min(scores) < 0 or not ahora - 90 * 86400 <= ts < ahora:
        return None
    return dict(comunes, fecha=U.ts_a_iso_utc(ts), id_local=local["id"], id_visita=visita["id"],
                nom_local=a, nom_visita=b, puntos_local=scores[0], puntos_visita=scores[1])


def obtener_eventos(deporte):
    if deporte != "Soccer" or not disponible():
        return []
    salida = {}
    for delta in (0, 1):
        dia = (datetime.now(timezone.utc) + timedelta(days=delta)).date().isoformat()
        data = cliente.pedir(BASE + "/api/v1/fixtures/", {"sport": "football", "date": dia, "status": "upcoming", "limit": 200}, ttl=3600)
        if not isinstance(data, dict) or data.get("date") != dia:
            continue
        rows = data.get("matches") or []
        if not isinstance(rows, list):
            continue
        if len(rows) >= 200:
            U.log("[sportscore] página al límite: cobertura parcial, no representa todas las ligas")
        for raw in rows:
            p = normalizar(raw)
            if p and p.get("tipo_estado") == "pre":
                salida[p["id"]] = p
    U.log(f"[sportscore] {len(salida)} próximos femeninos con fecha verificable")
    return list(salida.values())


def _resolver(nombre):
    clave = ("identidad", nombre)
    hit, slug = _cache.get(clave)
    if hit:
        return slug
    data = cliente.pedir(BASE + "/api/v1/search/", {"sport": "football", "q": nombre, "limit": 20}, ttl=6 * 3600)
    if not isinstance(data, dict):
        return None
    equipos = data.get("teams")
    if not isinstance(equipos, list):
        return None
    rows = [r for r in equipos if isinstance(r, dict) and U.firma_equipo(r.get("name", "")) == U.firma_equipo(nombre)]
    slug = rows[0].get("slug") if len(rows) == 1 else None
    if slug and not re.fullmatch(r"[-a-z0-9]+", slug):
        slug = None
    _cache.set(clave, slug, ttl=7 * 86400 if slug else 6 * 3600)
    return slug


def historial_equipo(evento, lado):
    equipo = evento.get(lado) or {}
    nombre = equipo.get("busqueda_nombre") or equipo.get("nombre", "")
    slug = _resolver(nombre)
    if not slug:
        return []
    data = cliente.pedir(BASE + "/api/widget/team/", {"sport": "football", "slug": slug, "limit": 30})
    if not isinstance(data, dict) or U.firma_equipo((data.get("team") or {}).get("name", "")) != U.firma_equipo(nombre):
        return []
    filas = [p for p in (normalizar(r) for r in data.get("matches", [])) if p and "fecha" in p]
    return sorted((p for p in filas if p.get("contexto_competicion") == evento.get("contexto_competicion") and
                   equipo.get("id") in (p["id_local"], p["id_visita"])), key=lambda p: p["fecha"], reverse=True)[:10]
