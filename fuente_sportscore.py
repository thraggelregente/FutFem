"""SportScore: fútbol/básquet femenino y calendario de tenis individual real.

API pública documentada. La atribución visible se conserva en Telegram. No se
consulta el feed suspendido ni se afirma equivalencia con toda API-Sports.
"""
import os
import re
import time
import hashlib
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
DEPORTES = {"Soccer": "football", "Basketball": "basketball", "Tennis": "tennis", "Cricket": "cricket"}


def disponible():
    return ACTIVO


def normalizar(raw, ahora=None, deporte="Soccer", max_dias=90):
    if deporte not in DEPORTES:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("competition", ""), str):
        return None
    ahora = time.time() if ahora is None else ahora
    a, b, liga = raw.get("home", ""), raw.get("away", ""), raw.get("competition", "")
    if not all(isinstance(n, str) and U.participante_definido(n) for n in (a, b)):
        return None
    femenino = U.es_femenino(liga, "", "") or (U.es_femenino("", a, "") and U.es_femenino("", b, ""))
    if not femenino:
        return None
    descripcion = " ".join((liga, a, b, str(raw.get("status_text") or "")))
    if re.search(r"\b(?:srl|simulat\w*|virtual|esports?|e[- ]?sports?|efootball|ebasketball|esoccer)\b", descripcion, re.I):
        return None
    if re.search(r"cancel|postpon|abandon|retir|walkover|w\.o\.|delayed|suspend|interrupt|forfeit|awarded|to be determined", str(raw.get("status_text") or ""), re.I):
        return None
    if deporte == "Basketball" and re.search(r"3\s*[x×]\s*3", liga, re.I):
        return None  # no aplicar umbrales de 5x5 a otra modalidad
    if deporte == "Tennis":
        if re.search(r"double|mixed", liga, re.I) or "/" in a or "/" in b:
            return None
        if any(re.search(r"\b(?:R\d{1,3}P\d+|qualifier|finalist|bye)\b", n, re.I) for n in (a, b)):
            return None
    fecha = str(raw.get("time") or "")
    # El contrato es datetime con zona: rechazar fecha sola o zona ausente.
    if not re.search(r"T\d{2}:\d{2}.*(?:Z|[+-]\d{2}:\d{2})$", fecha):
        return None
    f = U._parsear_iso(fecha)
    if not f:
        return None
    ts = f.timestamp()
    edades = U.categoria_equipo(liga)[0]
    if len(edades) > 1:
        return None
    if edades:
        if any(U.categoria_equipo(n)[0] and U.categoria_equipo(n)[0] != edades for n in (a, b)):
            return None
        if U.categoria_equipo(a)[0] == ():
            a += " U" + edades[0]
        if U.categoria_equipo(b)[0] == ():
            b += " U" + edades[0]
    contexto = "sportscore:" + deporte + ":" + U.normalizar(liga)
    prefijo = "ss:" if deporte == "Soccer" else "ss:" + deporte + ":"
    local = {"id": prefijo + U.firma_equipo(a), "nombre": a, "busqueda_nombre": raw["home"]}
    visita = {"id": prefijo + U.firma_equipo(b), "nombre": b, "busqueda_nombre": raw["away"]}
    if local["id"] == visita["id"]:
        return None
    comunes = {"fuente": FUENTE, "deporte": deporte, "torneo": liga, "historial_aislado": True,
               "contexto_competicion": contexto, "femenino_seguro": True, "local": local, "visita": visita,
               "startTimestamp": int(ts)}
    if deporte == "Cricket":
        formato = "T20" if re.search(r"\bT20I?\b", liga, re.I) else "ODI" if re.search(r"\bODI\b", liga, re.I) else None
        if not formato or edades or any(re.search(r"\bA(?: Women)?$", n) for n in (a, b)):
            return None
        internacional = bool(re.search(r"\b(?:ODI|International|World Cup)\b|Series .* vs ", liga, re.I))
        clubes = bool(re.search(r"Spring Challenge|National T20|Big Bash|Super Smash|Premier League", liga, re.I))
        if not internacional and not clubes:
            return None
        comunes.update(formato_cricket=formato, tipo_equipo_cricket="international" if internacional else "club")
    if raw.get("status") == "upcoming" and ahora < ts <= ahora + 86400:
        if any(raw.get(campo) not in (None, "", "0", 0) for campo in ("home_score", "away_score")):
            return None  # marcador ya iniciado pese a status upcoming
        url = str(raw.get("url", ""))
        if not re.fullmatch(r"/" + DEPORTES[deporte] + r"/match/[-a-z0-9]+(?:/[-a-z0-9]+)?/?", url):
            return None
        if f.hour == 0 and f.minute == 0:
            return None  # precisión de medianoche no confirmada en este contrato
        partes = url.strip("/").split("/")
        ident = partes[-1] if len(partes) == 4 else hashlib.sha256(
            (deporte + "|" + contexto + "|" + U.firma_partido(a, b) + "|" + str(int(ts))).encode()).hexdigest()[:24]
        return dict(comunes, id="ss_" + ident, sportscore_url=url,
                    tipo_estado="pre", horario=U.formatear_hora_arg(ts))
    if deporte in ("Tennis", "Cricket"):
        return None  # perfiles/resultados del motor siguen verificados por WTA; no inferir WC ni carrera
    scores = enteros(raw.get("home_score"), raw.get("away_score"))
    if (raw.get("status") != "finished" or not scores or min(scores) < 0 or not ahora - max_dias * 86400 <= ts < ahora
            or deporte == "Basketball" and (scores[0] == scores[1] or max(scores) == 0)):
        return None
    return dict(comunes, sportscore_url=raw.get("url", ""), fecha=U.ts_a_iso_utc(ts), id_local=local["id"], id_visita=visita["id"],
                nom_local=a, nom_visita=b, puntos_local=scores[0], puntos_visita=scores[1])


def obtener_eventos(deporte):
    if deporte not in DEPORTES or not disponible():
        return []
    salida = {}
    for delta in (0, 1):
        dia = (datetime.now(timezone.utc) + timedelta(days=delta)).date().isoformat()
        data = cliente.pedir(BASE + "/api/v1/fixtures/", {"sport": DEPORTES[deporte], "date": dia, "status": "upcoming", "limit": 200}, ttl=3600)
        if not isinstance(data, dict) or data.get("date") != dia:
            continue
        rows = data.get("matches") or []
        if not isinstance(rows, list):
            continue
        if len(rows) >= 200:
            U.log("[sportscore] página al límite: cobertura parcial, no representa todas las ligas")
            import cobertura_radar
            cobertura_radar.actual.truncado(FUENTE, deporte)
        for raw in rows:
            p = normalizar(raw, deporte=deporte)
            if p and p.get("tipo_estado") == "pre":
                salida[p["id"]] = p
    eventos = sin_colisiones(list(salida.values()))
    U.log(f"[sportscore/{deporte}] {len(eventos)} próximos femeninos con fecha verificable")
    return eventos


def sin_colisiones(eventos):
    """Un participante no puede jugar contra dos rivales a la misma hora/competición.

La muestra WNBL duplica UC Capitals/Canberra ante Bendigo. Sin ID canónico que
resuelva la discrepancia, no inventar alias ni producir dos alertas.
"""
    unicos, rivales = {}, {}
    for ev in eventos:
        base = (ev["contexto_competicion"], ev["startTimestamp"])
        a, b = ev["local"]["id"], ev["visita"]["id"]
        unicos.setdefault((base, tuple(sorted((a, b)))), ev)
        rivales.setdefault((base, a), set()).add(b)
        rivales.setdefault((base, b), set()).add(a)
    salida = [ev for (base, (a, b)), ev in unicos.items()
              if len(rivales[(base, a)]) == len(rivales[(base, b)]) == 1]
    if len(salida) != len(eventos):
        U.log(f"[sportscore] {len(eventos)-len(salida)} observaciones duplicadas o con identidad/horario contradictorios omitidas")
    return salida


def _resolver(nombre, deporte="Soccer"):
    if deporte not in DEPORTES:
        return None
    clave = ("identidad", nombre) if deporte == "Soccer" else ("identidad", deporte, nombre)
    hit, slug = _cache.get(clave)
    if hit:
        return slug
    data = cliente.pedir(BASE + "/api/v1/search/", {"sport": DEPORTES[deporte], "q": nombre, "limit": 20}, ttl=6 * 3600)
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
    deporte = evento.get("deporte", "Soccer")
    if deporte not in ("Soccer", "Basketball"):
        return []
    equipo = evento.get(lado) or {}
    nombre = equipo.get("busqueda_nombre") or equipo.get("nombre", "")
    slug = _resolver(nombre, deporte)
    if not slug:
        return []
    data = cliente.pedir(BASE + "/api/widget/team/", {"sport": DEPORTES[deporte], "slug": slug, "limit": 30})
    if not isinstance(data, dict) or U.firma_equipo((data.get("team") or {}).get("name", "")) != U.firma_equipo(nombre):
        return []
    filas = [p for p in (normalizar(r, deporte=deporte) for r in data.get("matches", [])) if p and "fecha" in p]
    return sorted((p for p in filas if p.get("contexto_competicion") == evento.get("contexto_competicion") and
                   equipo.get("id") in (p["id_local"], p["id_visita"])), key=lambda p: p["fecha"], reverse=True)[:10]


def h2h_partido(evento):
    """Meetings fechados; el resumen agregado no tiene ventana de vigencia."""
    deporte = evento.get("deporte")
    if deporte not in ("Soccer", "Basketball"):
        return []
    slugs = [_resolver((evento[l].get("busqueda_nombre") or evento[l]["nombre"]), deporte) for l in ("local", "visita")]
    if not all(slugs) or slugs[0] == slugs[1]:
        return []
    dato = cliente.pedir(BASE + "/api/v1/h2h/", {"sport": DEPORTES[deporte], "team1": slugs[0], "team2": slugs[1], "limit": 50})
    if not isinstance(dato, dict) or not isinstance(dato.get("matches"), list):
        return []
    ids = {evento[l]["id"] for l in ("local", "visita")}
    return [p for r in dato.get("matches", []) if isinstance(r, dict)
            for p in [normalizar(r, deporte=deporte, max_dias=365)] if p and "fecha" in p
            and {p["id_local"], p["id_visita"]} == ids
            and p["contexto_competicion"] == evento.get("contexto_competicion")]


def detalle_verificado(evento):
    """El slug puede apuntar al último cruce: exigir misma pareja, liga y horario."""
    deporte, url = evento.get("deporte"), str(evento.get("sportscore_url", ""))
    if deporte not in DEPORTES or not re.fullmatch(r"/" + DEPORTES[deporte] + r"/match/[-a-z0-9]+(?:/[-a-z0-9]+)?/?", url):
        return None
    slug = url.strip("/").split("/")[2]
    dato = cliente.pedir(BASE + "/api/widget/match/", {"sport": DEPORTES[deporte], "slug": slug}, ttl=900)
    if not isinstance(dato, dict) or dato.get("sport") != DEPORTES[deporte]:
        return None
    raw = (dato or {}).get("match") if isinstance(dato, dict) else None
    if not isinstance(raw, dict) or U.normalizar(raw.get("competition", "")) != U.normalizar(evento.get("torneo", "")):
        return None
    fecha = U._parsear_iso(str(raw.get("time", "")))
    if not fecha or fecha.tzinfo is None or int(fecha.timestamp()) != evento.get("startTimestamp"):
        return None
    if any(U.firma_equipo(raw.get(campo, "")) != U.firma_equipo(evento[lado].get("busqueda_nombre") or evento[lado]["nombre"])
           for campo, lado in (("home", "local"), ("away", "visita"))):
        return None
    return raw


def contexto_alerta(evento):
    """Sólo información confirmada del partido actual, sin puntaje adicional."""
    raw = detalle_verificado(evento)
    if not raw or raw.get("status") != "upcoming":
        return []
    alineacion = raw.get("lineups")
    if evento.get("deporte") == "Soccer" and isinstance(alineacion, dict) and alineacion.get("confirmed") is True:
        equipos = [alineacion.get(k) for k in ("home_xi", "away_xi")]
        if all(isinstance(x, list) and len(x) == 11 and all(isinstance(j, dict) and j.get("name") for j in x) for x in equipos):
            return ["SportScore: alineaciones confirmadas (11 titulares por equipo); no se infieren bajas por ausencia."]
    return []


def permite_alerta(evento):
    raw = detalle_verificado(evento)
    if raw is None:
        return True  # falta de detalle no desautoriza calendario verificado
    return bool(normalizar(raw, deporte=evento["deporte"]) and raw.get("status") == "upcoming")


def contexto_estadistico(evento, historiales):
    """Hasta cuatro detalles recientes; tiros al arco como contexto, no otra familia."""
    if evento.get("deporte") != "Soccer":
        return []
    promedios = []
    for lado, filas in zip(("local", "visita"), historiales):
        equipo = evento[lado]
        valores = []
        for p in filas[:2]:
            if equipo["id"] not in (p.get("id_local"), p.get("id_visita")):
                continue
            raw = detalle_verificado(p)
            if not raw or raw.get("status") != "finished":
                continue
            estadisticas = raw.get("stats")
            if not isinstance(estadisticas, list):
                continue
            stats = [s for s in estadisticas if isinstance(s, dict) and s.get("label") == "Shots on Target"]
            if len(stats) != 1:
                continue
            campo = "home" if equipo["id"] == p["id_local"] else "away"
            valor = stats[0].get(campo)
            if not isinstance(valor, bool) and isinstance(valor, (int, float)) and 0 <= valor <= 30:
                valores.append(valor)
        if len(valores) != 2:
            return []
        promedios.append(sum(valores)/2)
    return [f"Contexto SportScore: tiros al arco por partido {promedios[0]:.1f} / {promedios[1]:.1f} "
            "(local/visitante, dos partidos recientes cada una); no suma puntaje independiente."]


def resultados_evaluacion(evento):
    from resultados_evaluacion import de_historial
    deporte = evento.get('deporte')
    if deporte not in ('Soccer', 'Basketball') or not disponible():
        return []
    if not any(o.get('fuente')==FUENTE for o in evento.get('_observaciones') or [evento]):
        return []
    dia = datetime.fromtimestamp(evento['startTimestamp'], timezone.utc).date().isoformat()
    data = cliente.pedir(BASE + '/api/v1/fixtures/', {'sport': DEPORTES[deporte], 'date': dia, 'status': 'finished', 'limit': 200}, ttl=1800)
    if not isinstance(data, dict) or data.get('date') != dia:
        return []
    rows = data.get('matches') or []
    if len(rows) >= 200:
        import cobertura_radar
        cobertura_radar.actual.truncado(FUENTE, deporte)
    return [r for raw in rows if (p := normalizar(raw, deporte=deporte)) and (r := de_historial(p, deporte, FUENTE))]
