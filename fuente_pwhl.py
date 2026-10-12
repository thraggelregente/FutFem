"""Calendario y resultados del sitio oficial PWHL/HockeyTech.

El identificador público de su widget se descubre del HTML oficial. No se pide
una clave privada. Fechas exactas se leen del calendario iCal oficial; no se
inventan horas a partir del texto de la tabla.
"""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
import libro_resultados as L
import utilidades as U

FUENTE = "pwhl"
ACTIVO = os.environ.get("PWHL_ACTIVO", "1") != "0"
presupuesto = U.PresupuestoDiario("pwhl_publica", 20, reserva=2)
_cache = U.CachePersistente("pwhl_v1", 24 * 3600, max_items=64)
_ritmo = U.RitmoPedidos(8, minimo_segundos=1)
_historial = []
_pausa = 0.0


def disponible():
    return ACTIVO and time.time() >= _pausa


def _texto(url, ttl=24 * 3600):
    global _pausa
    hit, texto = _cache.get(url)
    if hit:
        return texto
    if not disponible() or not presupuesto.puede_gastar():
        return None
    _ritmo.esperar()
    presupuesto.registrar()
    try:
        r = requests.get(url, timeout=20)
        U._registrar(FUENTE, r.status_code)
        if r.status_code in (403, 429):
            _pausa = time.time() + 6 * 3600
        r.raise_for_status()
        texto = r.text
        _cache.set(url, texto, ttl=ttl)
        return texto
    except requests.RequestException:
        U.log("[pwhl] fuente pública no disponible; no se intenta eludir bloqueos")
        _cache.set(url, None, ttl=3600)
        return None


def _feed(key, view, **params):
    query = {"feed": "statviewfeed", "view": view, "key": key, "client_code": "pwhl", "site_id": 0,
             "lang": "en", **params}
    texto = _texto("https://lscluster.hockeytech.com/feed/index.php?" + urlencode(query),
                   ttl=6 * 3600 if view == "schedule" else 24 * 3600)
    if not texto:
        return None
    texto = texto.strip()
    if texto.startswith("(") and texto.endswith(")"):
        texto = texto[1:-1]
    try:
        return json.loads(texto)
    except ValueError:
        return None


def parsear_ical(texto, game_ids):
    salida = {}
    for bloque in texto.split("BEGIN:VEVENT")[1:]:
        valores = dict(re.findall(r"^([A-Z]+):([^\r\n]+)", bloque, re.M))
        uid, inicio = valores.get("UID", ""), valores.get("DTSTART", "")
        # El prefijo del UID tiene longitud variable. Resolver solo contra IDs pedidos.
        opciones = [str(pid) for pid in game_ids if uid.endswith(str(pid) + "@hockeytech.com")]
        if len(opciones) != 1 or not inicio.endswith("Z"):
            continue
        try:
            ts = int(datetime.strptime(inicio, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp())
            salida[opciones[0]] = ts
        except ValueError:
            continue
    return salida


def _dia_aproximado(fila, temporada):
    """Solo selecciona qué IDs consultar en iCal; nunca se publica como hora."""
    try:
        base = datetime.fromisoformat(temporada["start_date"])
        _, mes, dia = fila["date_with_day"].replace(",", "").split()
        meses = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
        year = base.year + (1 if meses[mes] < base.month and "Regular" in temporada["name"] else 0)
        return datetime(year, meses[mes], int(dia), tzinfo=timezone.utc).timestamp()
    except (KeyError, ValueError, TypeError):
        return 0


def obtener_eventos(deporte):
    global _historial
    if deporte != "Ice Hockey" or not disponible():
        return []
    html = _texto("https://www.thepwhl.com/en/stats/schedule")
    m = re.search(r"var appKey\s*=\s*'([A-Za-z0-9]+)'", html or "")
    if not m:
        return []
    meta = _feed(m[1], "bootstrap")
    if not isinstance(meta, dict):
        return []
    teams = {str(t["id"]): t["name"] for t in meta.get("teams", []) if str(t.get("id", "")).isdigit()}
    temporadas = sorted(meta.get("seasons", []), key=lambda s: s.get("start_date", ""), reverse=True)[:4]
    candidatos = []
    now = time.time()
    for temporada in temporadas:
        tabla = _feed(m[1], "schedule", season=temporada["id"])
        if not isinstance(tabla, list):
            continue
        for grupo in tabla:
            for seccion in grupo.get("sections", []):
                for item in seccion.get("data", []):
                    fila = item.get("row") or {}
                    fecha = _dia_aproximado(fila, temporada)
                    if now - 90 * 86400 <= fecha <= now + 2 * 86400:
                        candidatos.append(item)
    ids = sorted({str(x.get("row", {}).get("game_id")) for x in candidatos
                  if str(x.get("row", {}).get("game_id", "")).isdigit()})[:60]
    tiempos = {}
    for offset in range(0, len(ids), 20):
        texto = _texto("https://lscluster.hockeytech.com/components/calendar/ical_add_games.php?" +
                       urlencode({"client_code": "pwhl", "game_ids": ",".join(ids[offset:offset + 20])}), ttl=24 * 3600)
        if texto:
            tiempos.update(parsear_ical(texto, ids[offset:offset + 20]))
    salida, hist = [], []
    for item in candidatos:
        fila, props = item.get("row", {}), item.get("prop", {})
        ts = tiempos.get(str(fila.get("game_id")))
        il, iv = str(props.get("home_team_city", {}).get("teamLink", "")), str(props.get("visiting_team_city", {}).get("teamLink", ""))
        if not ts or il not in teams or iv not in teams:
            continue
        estado = fila.get("game_status", "").lower()
        if estado.startswith("final") and ts < now:
            try:
                hist.append({"fecha": U.ts_a_iso_utc(ts), "id_local": "pwhl:" + il, "id_visita": "pwhl:" + iv,
                             "nom_local": teams[il], "nom_visita": teams[iv],
                             "puntos_local": int(fila["home_goal_count"]), "puntos_visita": int(fila["visiting_goal_count"])})
            except (KeyError, ValueError):
                continue
        elif now < ts <= now + 24 * 3600 and fila.get("home_goal_count") == "-" and "postpon" not in estado and "cancel" not in estado:
            salida.append({"id": "pwhl_" + str(fila["game_id"]), "fuente": FUENTE, "deporte": deporte,
                           "torneo": "PWHL Women", "local": {"id": "pwhl:" + il, "nombre": teams[il]},
                           "visita": {"id": "pwhl:" + iv, "nombre": teams[iv]}, "femenino_seguro": True,
                           "tipo_estado": "pre", "startTimestamp": ts, "horario": U.formatear_hora_arg(ts)})
    _historial = hist
    L.ingestar("Ice Hockey", hist, FUENTE)
    U.log(f"[pwhl] {len(salida)} próximos; {len(hist)} resultados con fecha exacta")
    return salida


def historial_equipo(evento, lado):
    pid = str((evento.get(lado) or {}).get("id"))
    return sorted((p for p in _historial if pid in (p["id_local"], p["id_visita"])),
                  key=lambda p: p["fecha"], reverse=True)[:10]
