"""WNBA gratuita: sólo games, 5 req/min compartidas. Clave opcional en entorno.

No solicita los partidos NCAAW (de pago), ni estadísticas/lesiones de pago.
"""
import os
import re
import time
from datetime import datetime, timedelta, timezone

import utilidades as U
from fuentes_publicas import enteros

FUENTE = "balldontlie"
API_KEY = os.environ.get("BALLDONTLIE_API_KEY", "").strip()
presupuesto = U.PresupuestoDiario("balldontlie", 1000, reserva=0)  # límite operativo local, no cuota anunciada
_cache = U.CachePersistente("balldontlie_wnba_v1", 6 * 3600, max_items=1024)
_ritmo = U.RitmoPedidos(5, minimo_segundos=13)
_pausa = 0


def disponible():
    return bool(API_KEY)


def _get(params):
    global _pausa
    hit, dato = _cache.get(params)
    if hit:
        return dato
    if not disponible() or time.time() < _pausa or not presupuesto.puede_gastar():
        return None
    _ritmo.esperar()
    info = {}
    presupuesto.registrar()
    dato = U.get_json("https://api.balldontlie.io/wnba/v1/games", FUENTE, params=params,
                      headers={"Authorization": API_KEY}, info=info, timeout=25, reintentar=False)
    if info.get("status") in (401, 403):
        _pausa = time.time()+86400
    elif info.get("status") == 429:
        _pausa = time.time()+3600
    if not isinstance(dato, dict) or not isinstance(dato.get("data"), list):
        _cache.set(params, None, ttl=3600)
        return None
    _cache.set(params, dato)
    return dato


def normalizar(raw, ahora=None):
    ahora = time.time() if ahora is None else ahora
    if not isinstance(raw, dict) or not re.search(r"T\d{2}:\d{2}.*(?:Z|[+-]\d{2}:\d{2})$", str(raw.get("date", ""))):
        return None
    f = U._parsear_iso(raw["date"])
    if not f or str(raw.get("season")) != str(f.year):
        return None
    a, b = raw.get("home_team"), raw.get("visitor_team")
    if not all(isinstance(t, dict) and t.get("id") and U.participante_definido(t.get("full_name", "")) for t in (a, b)):
        return None
    if str(a["id"]) == str(b["id"]) or not raw.get("id"):
        return None
    ts = int(f.timestamp())
    local, visita = ({"id": "bdl:"+str(t["id"]), "nombre": t["full_name"], "balldontlie_id": t["id"]} for t in (a, b))
    base = {"fuente": FUENTE, "deporte": "Basketball", "torneo": "WNBA Women", "femenino_seguro": True,
            "historial_aislado": True, "contexto_competicion": "bdl:wnba:"+str(f.year),
            "local": local, "visita": visita, "startTimestamp": ts}
    if raw.get("status_state") == "scheduled" and ahora < ts <= ahora+86400:
        if f.hour == f.minute == 0 or any(raw.get(k) not in (None, 0) for k in ("home_score", "away_score")):
            return None
        return dict(base, id="bdl_"+str(raw["id"]), tipo_estado="pre", horario=U.formatear_hora_arg(ts))
    puntos = enteros(raw.get("home_score"), raw.get("away_score"))
    if raw.get("status_state") != "final" or not puntos or min(puntos) < 0 or puntos[0] == puntos[1] or not ahora-90*86400 <= ts < ahora:
        return None
    return dict(base, id="bdl_"+str(raw["id"]), _outcome_status="normal", fecha=U.ts_a_iso_utc(ts), id_local=local["id"], id_visita=visita["id"],
                nom_local=local["nombre"], nom_visita=visita["nombre"], puntos_local=puntos[0], puntos_visita=puntos[1])


def _paginas(params):
    salida, cursores = [], set()
    for _ in range(6):
        dato = _get(dict(params, per_page=100)) or {}
        salida.extend(dato.get("data") or [])
        cursor = (dato.get("meta") or {}).get("next_cursor")
        if cursor is None:
            break
        if str(cursor) in cursores:
            U.log("[balldontlie] cursor repetido: cobertura parcial")
            break
        cursores.add(str(cursor))
        params = dict(params, cursor=cursor)
    else:
        U.log("[balldontlie] límite operativo de páginas: cobertura parcial")
    return salida


def obtener_eventos(deporte):
    if deporte != "Basketball" or not disponible():
        return []
    ahora = datetime.now(timezone.utc)
    filas = _paginas({"start_date": ahora.date().isoformat(), "end_date": (ahora+timedelta(days=1)).date().isoformat()})
    return list({p["id"]: p for r in filas for p in [normalizar(r)] if p and p.get("tipo_estado") == "pre"}.values())


def historial_equipo(evento, lado):
    equipo = evento.get(lado) or {}
    if not equipo.get("balldontlie_id"):
        return []
    ahora = datetime.now(timezone.utc)
    filas = _paginas({"team_ids[]": equipo["balldontlie_id"], "start_date": (ahora-timedelta(days=90)).date().isoformat(),
                      "end_date": ahora.date().isoformat()})
    salida = [p for r in filas for p in [normalizar(r)] if p and "fecha" in p
              and equipo["id"] in (p["id_local"], p["id_visita"])
              and p["contexto_competicion"] == evento.get("contexto_competicion")]
    return sorted({(p["fecha"], p["id_local"], p["id_visita"]): p for p in salida}.values(), key=lambda p:p["fecha"], reverse=True)[:10]


def resultados_evaluacion(evento):
    from resultados_evaluacion import de_historial
    if evento.get('deporte')!='Basketball' or not disponible():
        return []
    if not any(o.get('fuente')==FUENTE for o in evento.get('_observaciones') or [evento]):
        return []
    dia=datetime.fromtimestamp(evento['startTimestamp'],timezone.utc).date().isoformat()
    return [r for raw in _paginas({'start_date':dia,'end_date':dia}) if (p:=normalizar(raw)) and 'fecha' in p
            and (r:=de_historial(p,'Basketball',FUENTE))]
