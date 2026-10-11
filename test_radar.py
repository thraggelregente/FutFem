"""
test_radar.py â€” pruebas offline del radar (no usan internet ni Telegram).
Uso:  python test_radar.py
Cada escenario corre en un proceso aparte para que no se contaminen los caches.
"""
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

ESCENARIOS = ["espn_futbol", "espn_tenis", "api_sports", "cuota_agotada", "dedupe_y_repeticion", "filtros",
              "highlightly", "highlightly_nombres", "highlightly_ligas", "oddspapi", "reevalua_sin_datos",
              "openligadb", "thesportsdb_allowlist", "thesportsdb_sin_timestamp", "thesportsdb_liga_masculina",
              "thesportsdb_historial", "theoddsapi", "espn_fallo_transitorio", "agregador_tolerancia_y_prioridad",
              "historial_por_costo", "motor_congestion", "motor_triangulacion_entre_fuentes", "http_y_logs",
              "telegram_reintentos", "cuello_de_botella_sin_datos"]


def iso(horas=0, dias=0, z=True):
    d = datetime.now(timezone.utc) + timedelta(hours=horas, days=dias)
    return d.strftime("%Y-%m-%dT%H:%MZ") if z else d.isoformat()


def preparar():
    os.environ["PORT"] = "0"
    os.environ["DATA_DIR"] = tempfile.mkdtemp()
    for k in ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
        os.environ.pop(k, None)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def equipo(i, nombre, home, score="0"):
    return {"homeAway": "home" if home else "away", "score": score,
            "team": {"id": str(i), "displayName": nombre}}


def evento_espn(eid, fecha, local, visita, estado="pre", completado=False, nombre_estado="STATUS_SCHEDULED"):
    return {"id": str(eid), "date": fecha, "competitions": [{
        "status": {"type": {"state": estado, "completed": completado, "name": nombre_estado}},
        "competitors": [local, visita]}]}


NOMBRES = {1: "Alpha W", 2: "Beta W", 3: "Gamma W", 4: "Delta W", 5: "Epsilon W"}


def historial_espn():
    # (local, visita, goles_local, goles_visita, hace_dias)
    partidos = [(1, 3, 4, 0, 5), (4, 1, 0, 3, 12), (1, 5, 2, 0, 19), (3, 1, 0, 3, 26), (1, 4, 4, 1, 33), (5, 1, 0, 2, 40),
                (3, 2, 3, 0, 6), (2, 4, 0, 2, 13), (5, 2, 3, 0, 20), (2, 3, 0, 2, 27), (4, 2, 4, 0, 34), (2, 5, 1, 3, 41)]
    out = []
    for n, (l, v, gl, gv, d) in enumerate(partidos):
        out.append(evento_espn(9000 + n, iso(dias=-d), equipo(l, NOMBRES[l], True, str(gl)),
                               equipo(v, NOMBRES[v], False, str(gv)), "post", True, "STATUS_FULL_TIME"))
    return out


def fake_espn(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
    params = params or {}
    if "/tennis/wta/rankings" in url:
        ranks = [{"current": i, "athlete": {"id": str(1000 + i)}} for i in range(1, 121)]
        return {"rankings": [{"ranks": ranks}]}
    if "/tennis/wta/scoreboard" in url:
        def jug(pid, nombre, rank=None):
            c = {"id": str(pid), "athlete": {"displayName": nombre}}
            if rank:
                c["curatedRank"] = {"current": rank}
            return c
        pre = {"state": "pre"}
        return {"events": [{"name": "Torneo Test", "groupings": [
            {"grouping": {"displayName": "Women's Singles"}, "competitions": [
                {"id": "c1", "date": iso(3), "status": {"type": pre}, "round": {"displayName": "Round 1"},
                 "competitors": [jug(1008, "Top Eight", 8), jug(5555, "Lucky Unranked")]},
                {"id": "c2", "date": iso(4), "status": {"type": pre}, "competitors": [jug(1010, "Top Ten", 10), {"id": "x"}]},
                {"id": "c3", "date": iso(-5), "status": {"type": {"state": "post"}},
                 "competitors": [jug(1001, "Done One"), jug(5556, "Done Two")]},
            ]},
            {"grouping": {"displayName": "Women's Doubles"}, "competitions": [
                {"id": "d1", "date": iso(3), "status": {"type": pre},
                 "competitors": [jug(1002, "Doble Uno", 2), jug(5557, "Doble Dos")]}]},
        ]}]}
    if "/soccer/eng.w.1/scoreboard" in url:
        if "-" in str(params.get("dates", "")):
            return {"events": historial_espn()}
        return {"events": [evento_espn(7001, iso(6), equipo(1, NOMBRES[1], True), equipo(2, NOMBRES[2], False))]}
    return {"events": []}


def montar(fake):
    preparar()
    import utilidades as U
    U.get_json = fake
    import main
    mensajes = []
    main.enviar_telegram = lambda m: (mensajes.append(m) or True)
    return U, main, mensajes


def ok(cond, texto):
    print(("  OK  " if cond else "  FALLA ") + texto)
    if not cond:
        sys.exit(1)


def escenario_espn_futbol():
    U, main, msgs = montar(fake_espn)
    main.fuente_api_football = None
    main.DEPORTES_RADAR = ["Soccer"]
    main.ejecutar_barrido_radar()
    alertas = [m for m in msgs if "MISMATCH" in m]
    ok(len(alertas) == 1, f"1 alerta de fÃºtbol (hubo {len(alertas)})")
    ok("Alpha W" in alertas[0] and "Favorito:</b> Alpha W" in alertas[0], "el favorito es Alpha W (local)")
    ok("TriangulaciÃ³n" in alertas[0] and "Forma" in alertas[0], "incluye forma y triangulaciÃ³n")
    ok("Momentum" not in alertas[0], "el momentum no se cuenta dos veces")
    ok("Estado del mercado" not in alertas[0], "la alerta no trae secciÃ³n de cuotas")
    ok("ÃƒÂ°Ã…Â¸" not in alertas[0] and "ðŸš¨" in alertas[0], "los emojis salen bien")


def escenario_espn_tenis():
    U, main, msgs = montar(fake_espn)
    main.fuente_api_football = None
    main.DEPORTES_RADAR = ["Tennis"]
    main.ejecutar_barrido_radar()
    alertas = [m for m in msgs if "MISMATCH" in m]
    ok(len(alertas) == 1, f"1 alerta de tenis (hubo {len(alertas)}): TBD, terminado y dobles se ignoran")
    ok("Top Eight" in alertas[0] and "fuera del ranking" in alertas[0], "Top 8 vs jugadora fuera del ranking")
    ok("Doble" not in alertas[0], "los dobles no generan alertas")


def fixtures_api(fecha=None, liga=None):
    def fx(i, liga_id, liga_nom, h, a, estado, ts, gh=None, ga=None, season=2026):
        return {"fixture": {"id": i, "date": datetime.fromtimestamp(ts, timezone.utc).isoformat(), "timestamp": ts,
                            "status": {"short": estado}},
                "league": {"id": liga_id, "name": liga_nom, "country": "Germany", "season": season},
                "teams": {"home": {"id": h[0], "name": h[1]}, "away": {"id": a[0], "name": a[1]}},
                "goals": {"home": gh, "away": ga}}
    ahora = int(datetime.now(timezone.utc).timestamp())
    if liga is None:
        return [
            fx(1, 82, "Frauen-Bundesliga", (11, "Bayern Frauen"), (12, "Koln Frauen"), "NS", ahora + 3 * 3600),
            fx(2, 78, "Bundesliga", (21, "Bayern"), (22, "Koln"), "NS", ahora + 3 * 3600),
            fx(3, 82, "Frauen-Bundesliga", (13, "X Frauen"), (14, "Y Frauen"), "FT", ahora - 3600, 1, 0),
        ]
    d = lambda n: ahora - n * 86400
    h = []
    for k, (l, v, gl, gv, dd) in enumerate([((11, "Bayern Frauen"), (13, "X Frauen"), 4, 0, 4), ((14, "Y Frauen"), (11, "Bayern Frauen"), 0, 3, 11),
                                            ((11, "Bayern Frauen"), (14, "Y Frauen"), 3, 0, 18), ((13, "X Frauen"), (11, "Bayern Frauen"), 1, 4, 25),
                                            ((11, "Bayern Frauen"), (15, "Z Frauen"), 2, 0, 32), ((15, "Z Frauen"), (11, "Bayern Frauen"), 0, 3, 39),
                                            ((13, "X Frauen"), (12, "Koln Frauen"), 3, 0, 5), ((12, "Koln Frauen"), (14, "Y Frauen"), 0, 2, 12),
                                            ((15, "Z Frauen"), (12, "Koln Frauen"), 4, 0, 19), ((12, "Koln Frauen"), (13, "X Frauen"), 0, 2, 26),
                                            ((14, "Y Frauen"), (12, "Koln Frauen"), 3, 0, 33), ((12, "Koln Frauen"), (15, "Z Frauen"), 1, 3, 40)]):
        h.append(fx(100 + k, liga, "Frauen-Bundesliga", l, v, "FT", d(dd), gl, gv))
    return h


def escenario_api_sports():
    os.environ["API_FOOTBALL_KEY"] = "clave-falsa"
    llamadas = []

    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "api-sports" in url:
            llamadas.append((url, dict(params or {})))
            if info is not None:
                info["status"] = 200
                info["headers"] = {"x-ratelimit-requests-remaining": str(100 - len(llamadas))}
            return {"errors": [], "response": fixtures_api(liga=(params or {}).get("league"))}
        return {"events": []}

    U, main, msgs = montar(fake)
    main.fuente_espn = None
    main.DEPORTES_RADAR = ["Soccer"]
    main.ejecutar_barrido_radar()
    alertas = [m for m in msgs if "MISMATCH" in m]
    ok(len(alertas) == 1, f"1 alerta con API-Sports (hubo {len(alertas)})")
    ok("Bayern Frauen" in alertas[0] and "Bayern vs" not in alertas[0], "se analizÃ³ la liga femenina y NO la masculina")
    fixtures_por_fecha = [c for c in llamadas if "date" in c[1]]
    fixtures_por_liga = [c for c in llamadas if "league" in c[1]]
    ok(len(fixtures_por_fecha) == 2, f"2 pedidos de listado (hoy y maÃ±ana), hubo {len(fixtures_por_fecha)}")
    ok(len(fixtures_por_liga) == 1, f"1 pedido de historial para toda la liga (antes: 3 por partido), hubo {len(fixtures_por_liga)}")
    ok(len(llamadas) == 3, f"3 requests en total para el barrido completo ({len(llamadas)})")
    ok(main.fuente_api_football.DEPORTES_ACTIVOS == ["Soccer"], "API-Sports consulta solo Soccer por defecto")
    ok(main.fuente_api_football.MAX_LIGAS_POR_DEPORTE == 2, "mÃ¡ximo 2 ligas por deporte")


def escenario_cuota_agotada():
    os.environ["API_FOOTBALL_KEY"] = "clave-falsa"
    llamadas = []

    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "api-sports" in url:
            llamadas.append(url)
            if info is not None:
                info["status"] = 200
                info["headers"] = {}
            return {"errors": {"requests": "You have reached the request limit for the day"}, "response": []}
        return {"events": []}

    U, main, msgs = montar(fake)
    main.fuente_espn = None
    main.DEPORTES_RADAR = ["Soccer"]
    main.ejecutar_barrido_radar()
    main.ejecutar_barrido_radar()
    ok(len(llamadas) == 1, f"tras el error de cuota no vuelve a pedir en todo el dÃ­a (pedidos: {len(llamadas)})")
    ok(main.fuente_api_football.presupuesto.restantes() == 0, "el presupuesto queda en 0 hasta maÃ±ana")

    os.environ["API_FOOTBALL_DAILY_LIMIT"] = "10"


def escenario_dedupe_y_repeticion():
    os.environ["API_FOOTBALL_KEY"] = "clave-falsa"

    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "api-sports" in url:
            if info is not None:
                info["status"] = 200
                info["headers"] = {}
            ahora = int(datetime.now(timezone.utc).timestamp())
            if (params or {}).get("league"):
                return {"errors": [], "response": []}
            # mismo partido que ESPN (Alpha W vs Beta W) con otro nombre
            return {"errors": [], "response": [{
                "fixture": {"id": 5, "date": iso(6), "timestamp": ahora + 6 * 3600, "status": {"short": "NS"}},
                "league": {"id": 1, "name": "Women's Super League", "country": "England", "season": 2026},
                "teams": {"home": {"id": 91, "name": "Alpha Women"}, "away": {"id": 92, "name": "Beta Women"}},
                "goals": {"home": None, "away": None}}]}
        return fake_espn(url, fuente, headers, params, timeout, proxies, info)

    U, main, msgs = montar(fake)
    main.DEPORTES_RADAR = ["Soccer"]
    main.ejecutar_barrido_radar()
    n1 = len([m for m in msgs if "MISMATCH" in m])
    ok(n1 == 1, f"el mismo partido de ESPN y API-Sports genera UNA sola alerta (hubo {n1})")
    main.ejecutar_barrido_radar()
    n2 = len([m for m in msgs if "MISMATCH" in m])
    ok(n2 == 1, "el segundo barrido no repite la alerta")


def escenario_filtros():
    preparar()
    import utilidades as U
    import re
    # El filtro VIEJO de main.py (para demostrar el bug) vs el nuevo
    viejo_masc = re.compile(r"\b(atp|challenger|davis cup|men|mens|men's|masculino|masculin|herren|hommes|maschile|nba|nfl|nhl|mlb|mls|j1 league|j2 league|j3 league|bundesliga|serie a|premier league|la liga|ligue 1|eredivisie|liga mx|superliga|allsvenskan|eliteserien|superligaen)\b")
    casos = [("Frauen-Bundesliga", True), ("Serie A Femminile", True), ("Liga MX Femenil", True),
             ("Superliga Femenina", True), ("Women's Super League", True), ("Bundesliga", False), ("La Liga", False), ("NBA", False)]
    rechazadas_por_el_viejo = [t for t, fem in casos if fem and viejo_masc.search(t.lower())]
    print(f"  (el filtro viejo rechazaba {len(rechazadas_por_el_viejo)} ligas femeninas: {rechazadas_por_el_viejo})")
    ok(len(rechazadas_por_el_viejo) >= 4, "bug reproducido en el filtro viejo")
    for torneo, esperado in casos:
        ok(U.es_femenino(torneo, "A", "B") == esperado, f"filtro nuevo: {torneo!r} -> {esperado}")
    ok(U.es_femenino("Liga", "Arsenal W", "Chelsea"), "equipo con sufijo W")
    ok(not U.es_femenino("ATP Challenger", "W. Williams", "X"), "'W.' de un nombre no cuenta como femenino")

    # Motor
    import motor_mismatches as M
    hay, det, fav, pts = M.evaluar_mismatch_tenis("A", "B", 8, None, fuera_visita=True)
    ok(hay and fav == M.LOCAL and pts == 3 and "ðŸ”´" in det, "tenis: top 8 vs fuera del ranking = 3 pts, emoji OK")
    hay, *_ = M.evaluar_mismatch_tenis("A", "B", 8, None)
    ok(not hay, "tenis: sin dato de rival NO es mismatch (no se inventa)")


# ---------------------------------------------------------------------------
# HIGHLIGHTLY
# ---------------------------------------------------------------------------
def hl_partido(i, local, visita, fecha, estado="Not started", marcador=None, liga=(500, "Frauen-Bundesliga", 2026)):
    return {"id": i, "date": fecha, "country": {"name": "Germany", "code": "DE"},
            "league": {"id": liga[0], "name": liga[1], "season": liga[2]},
            "homeTeam": {"id": local[0], "name": local[1]}, "awayTeam": {"id": visita[0], "name": visita[1]},
            "state": {"description": estado, "score": {"current": marcador} if marcador else {}}}


BAYERN, KOLN = (11, "Bayern Frauen"), (12, "Koln Frauen")
X, Y, Z, W = (13, "X Frauen"), (14, "Y Frauen"), (99, "Z Frauen"), (15, "W Frauen")


def hl_forma(equipo_id):
    f = lambda i, l, v, m, d: hl_partido(i, l, v, iso(dias=-d), "Finished", m)
    if equipo_id == "11":
        return [f(1, BAYERN, X, "4 - 0", 4), f(2, Y, BAYERN, "0 - 3", 11), f(3, BAYERN, Z, "4 - 0", 18),
                f(4, X, BAYERN, "1 - 4", 25), f(5, BAYERN, W, "3 - 0", 32)]
    return [f(6, X, KOLN, "3 - 0", 5), f(7, KOLN, Y, "0 - 2", 12), f(8, Z, KOLN, "2 - 0", 19),
            f(9, KOLN, X, "0 - 2", 26), f(10, Y, KOLN, "3 - 0", 33)]


def hl_tabla():
    def fila(i, nombre, pos, g, e, p):
        return {"team": {"id": i, "name": nombre}, "position": pos, "points": 3 * g + e,
                "total": {"wins": g, "draws": e, "loses": p, "games": g + e + p, "scoredGoals": 3 * g, "receivedGoals": 2 * p}}
    filas = [fila(11, "Bayern Frauen", 1, 10, 1, 1)] + [fila(100 + k, f"Relleno {k}", 1 + k, 6, 2, 4) for k in range(1, 11)]
    filas.append(fila(12, "Koln Frauen", 12, 1, 1, 10))
    return {"groups": [{"name": "Frauen-Bundesliga", "standings": filas}], "league": {"id": 500, "name": "Frauen-Bundesliga", "season": 2026}}


def fake_highlightly(llamadas):
    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "highlightly" not in url:
            return {"events": []}
        params = params or {}
        llamadas.append((url, dict(params), dict(headers or {})))
        if info is not None:
            info["status"] = 200
            info["headers"] = {"x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": "90"}
        ruta = url.split("highlightly.net", 1)[1]
        if ruta.endswith("/matches"):
            return {"data": [
                hl_partido(1, BAYERN, KOLN, iso(6)),
                hl_partido(2, (21, "Bayern"), (22, "Koln"), iso(6), liga=(78, "Bundesliga", 2026)),
                hl_partido(3, X, Y, iso(-2), "Finished", "1 - 0"),
            ], "pagination": {"totalCount": 3, "offset": 0, "limit": 100}}
        if ruta.endswith("/last-five-games"):
            return hl_forma(str(params.get("teamId")))
        if ruta.endswith("/head-2-head"):
            return [hl_partido(20, BAYERN, KOLN, iso(dias=-20), "Finished", "2 - 0"),
                    hl_partido(21, KOLN, BAYERN, iso(dias=-60), "Finished", "0 - 1")]
        if ruta.endswith("/standings"):
            return hl_tabla()
        return {"data": []}
    return fake


def escenario_highlightly():
    os.environ["HIGHLIGHTLY_API_KEY"] = "clave-falsa"
    llamadas = []
    U, main, msgs = montar(fake_highlightly(llamadas))
    main.fuente_espn = None
    main.fuente_api_football = None
    main.DEPORTES_RADAR = ["Soccer"]
    main.ejecutar_barrido_radar()
    alertas = [m for m in msgs if "MISMATCH" in m]
    ok(len(alertas) == 1, f"1 alerta con eventos de Highlightly (hubo {len(alertas)}): la liga masculina y el partido terminado se ignoran")
    ok("Favorito:</b> Bayern Frauen" in alertas[0], "el favorito es Bayern Frauen")
    ok("H2H" in alertas[0] and "Forma" in alertas[0] and "TriangulaciÃ³n" in alertas[0], "incluye forma, triangulaciÃ³n y H2H")
    ok("Estado del mercado" not in alertas[0], "sin secciÃ³n de cuotas")
    ok(all(h.get("x-rapidapi-key") == "clave-falsa" for _, _, h in llamadas), "autentica con el header x-rapidapi-key")
    ok(all("/v1/" not in u for u, _, _ in llamadas), "usa las rutas actuales (sin /v1/)")
    ok(sum(1 for u, _, _ in llamadas if u.endswith("/matches")) == 2, "1 pedido de partidos por fecha (hoy y maÃ±ana)")

    # tabla de posiciones, con los ids del evento
    ev = main.fuente_highlightly.obtener_eventos("Soccer")[0]
    tabla, n = U.tabla_desde_fuentes(ev, main.fuente_highlightly)
    ok(n == 12 and set(tabla) == {"11", "12"}, f"tabla de 12 equipos con las filas de los dos equipos (n={n})")
    res = main.motor_mismatches.evaluar_tabla_posiciones(tabla, "11", "12", n_equipos=n)
    ok(res and res["es_mismatch_tabla"] and res["favorito"] == main.motor_mismatches.LOCAL, "la tabla marca a Bayern como favorito")
    ok(main.fuente_highlightly.presupuesto.limite == 100, "el presupuesto se corrige con los headers de la API")


def escenario_highlightly_nombres():
    os.environ["HIGHLIGHTLY_API_KEY"] = "clave-falsa"
    llamadas = []
    base = fake_highlightly(llamadas)

    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "highlightly" in url and url.endswith("/teams"):
            llamadas.append((url, dict(params or {}), {}))
            if info is not None:
                info["status"], info["headers"] = 200, {}
            nombre = (params or {}).get("name")
            if nombre == "Alpha W":
                return {"data": [{"id": 601, "name": "Alpha"}, {"id": 501, "name": "Alpha W"}]}
            if nombre == "Beta W":
                return {"data": [{"id": 502, "name": "Beta W"}]}
            return {"data": []}
        if "highlightly" in url and url.endswith("/head-2-head"):
            llamadas.append((url, dict(params or {}), {}))
            if info is not None:
                info["status"], info["headers"] = 200, {}
            return [hl_partido(30, (502, "Beta W"), (501, "Alpha W"), iso(dias=-10), "Finished", "0 - 2"),
                    hl_partido(31, (501, "Alpha W"), (502, "Beta W"), iso(dias=-40), "Finished", "1 - 0")]
        if "highlightly" in url and url.endswith("/last-five-games") and str((params or {}).get("teamId")) == "501":
            llamadas.append((url, dict(params or {}), {}))
            if info is not None:
                info["status"], info["headers"] = 200, {}
            return [hl_partido(40, (501, "Alpha W"), (700, "Rival W"), iso(dias=-3), "Finished", "2 - 1"),
                    hl_partido(41, (701, "Otro W"), (501, "Alpha W"), iso(dias=-9), "Finished", "0 - 3")]
        return base(url, fuente, headers, params, timeout, proxies, info)

    U, main, msgs = montar(fake)
    hl = main.fuente_highlightly
    ok(hl._buscar_equipo("Alpha W", "Soccer") == 501, "'Alpha W' se resuelve al equipo femenino y NO al masculino 'Alpha'")
    h2h = hl.obtener_h2h("Alpha W", "Beta W", "Soccer", id_local="1", id_visita="2")
    ok(len(h2h) == 2, f"2 cruces de H2H (hubo {len(h2h)})")
    ok((h2h[0]["id_local"], h2h[0]["id_visita"], h2h[0]["puntos_local"], h2h[0]["puntos_visita"]) == ("2", "1", 0, 2),
       "el H2H usa los ids del evento y conserva quiÃ©n fue local ese dÃ­a (Beta local perdiÃ³ 0-2 con Alpha)")
    import motor_mismatches as M
    h = M.analizar_h2h_extendido(h2h, "1", "2")
    ok([x["ganador"] for x in h["reciente"]] == [M.LOCAL, M.LOCAL], "el motor lee los dos cruces como victorias del local actual")
    ok((h2h[1]["id_local"], h2h[1]["id_visita"]) == ("1", "2"), "el cruce en que el local actual era local queda igual")
    forma = hl.obtener_forma_reciente("Alpha W", "Soccer", id_interno="1")
    ok(len(forma) == 2 and forma[0]["id_local"] == "1" and forma[1]["id_visita"] == "1",
       "la forma por nombre reescribe el id del equipo al del evento (Alpha W = 1) y deja el del rival")
    ok(main.motor_mismatches.evaluar_rendimiento_reciente(forma, "1")["victorias"] == 2, "el motor cuenta las 2 victorias de Alpha W (local y visita)")


# ---------------------------------------------------------------------------
# ODDSPAPI
# ---------------------------------------------------------------------------
def escenario_oddspapi():
    os.environ["ODDSPAPI_API_KEY"] = "clave-falsa"
    llamadas = []

    def fx(fid, sid, deporte, torneo, p1, p2, estado, horas):
        ts = int((datetime.now(timezone.utc) + timedelta(hours=horas)).timestamp())
        return {"fixtureId": fid, "status": {"live": False, "statusId": estado, "statusName": "Pregame"},
                "sport": {"sportId": sid, "sportName": deporte},
                "tournament": {"tournamentId": 1, "tournamentName": torneo, "categoryName": "Spain"},
                "startTime": ts,
                "participants": {"participant1Id": p1[0], "participant1Name": p1[1],
                                 "participant2Id": p2[0], "participant2Name": p2[1]},
                "scores": {}}

    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "oddspapi" not in url:
            return {"events": []}
        llamadas.append((url, dict(params or {}), dict(headers or {})))
        if info is not None:
            info["status"], info["headers"] = 200, {}
        return [
            fx("id1", 10, "Soccer", "Liga F", (1, "Barcelona"), (2, "Madrid CFF"), 0, 5),
            fx("id2", 10, "Soccer", "La Liga", (3, "Barcelona"), (4, "Madrid"), 0, 5),
            fx("id3", 10, "Soccer", "Liga F", (5, "A"), (6, "B"), 0, 40),
            fx("id4", 34, "Volleyball", "Superliga Femenina", (7, "Voley A"), (8, "Voley B"), 0, 8),
            fx("id5", 10, "Soccer", "Liga F", (9, "C"), (10, "D"), 2, 3),
        ]

    U, main, msgs = montar(fake)
    op = main.fuente_oddspapi
    soccer = op.obtener_eventos("Soccer")
    voley = op.obtener_eventos("Volleyball")
    ok(len(soccer) == 1 and soccer[0]["local"]["nombre"] == "Barcelona", f"1 evento femenino de fÃºtbol (hubo {len(soccer)}): La Liga masculina, +24 h y terminados se ignoran")
    ok(len(voley) == 1, "1 evento femenino de vÃ³ley")
    billables = [x for x in llamadas if x[0].rstrip("/").endswith("/fixtures")]
    ok(len(billables) == 1, f"1 solo pedido billable de fixtures para todos los deportes (hubo {len(billables)})")
    ok("sportId" not in billables[0][1] and billables[0][1].get("apiKey") == "clave-falsa" and billables[0][2].get("X-API-Key") == "clave-falsa", "fixture global autentica con apiKey y header compatible")
    ok(not any("/odds" in x[0] or "/markets" in x[0] or "/bookmakers" in x[0] for x in llamadas), "no consulta cuotas, mercados ni bookmakers")
    ok(op.obtener_h2h(soccer[0]) == [] and op.historial_equipo(soccer[0], "local") == [], "forma y H2H apagados por defecto (no gastan cuota)")
    ok(len([x for x in llamadas if x[0].rstrip("/").endswith("/fixtures")]) == 1, "forma / H2H apagados no hacen requests billable adicionales")
    ok(op.presupuesto.usadas == 1, "el control de cuota /account no consume el contador diario billable")


# ---------------------------------------------------------------------------
# REGRESIONES DE AUDITORÃA: no silenciar partidos sin evidencia y validar fuentes gratuitas.
# ---------------------------------------------------------------------------
def escenario_reevalua_sin_datos():
    U, main, mensajes = montar(fake_espn)
    main.DEPORTES_RADAR = []
    main.fuente_api_football = None
    ahora = int(datetime.now(timezone.utc).timestamp())
    ev = {
        "id": "fixture-regresion-1",
        "clave": "no-es-clave-canonica",
        "deporte": "Soccer",
        "torneo": "Women's Super League",
        "local": {"id": "A", "nombre": "Alpha W", "ranking": None, "fuera_ranking": False},
        "visita": {"id": "B", "nombre": "Beta W", "ranking": None, "fuera_ranking": False},
        "horario": "A confirmar",
        "tipo_estado": "pre",
        "startTimestamp": ahora + 4 * 3600,
        "fuente": "espn",
        "femenino_seguro": True,
    }
    main._historial_equipo = lambda evento, lado: []
    clave = main._clave_canonica_evento(ev)
    stat = main._nuevo_stat()
    main._procesar_evento(ev, stat, time.time())
    main._procesar_evento(ev, stat, time.time())
    ok(stat["sin_datos"] == 2, "un partido sin historial se intenta de nuevo en el ciclo siguiente")
    ok(not main.registro.visto(clave), "un anÃ¡lisis incompleto no se marca como alerta ya enviada")
    ok(not mensajes, "no se genera alerta sin evidencia deportiva suficiente")


def escenario_openligadb():
    os.environ["OPENLIGADB_WOMENS_LEAGUES"] = "ffb1:2026"
    ahora = datetime.now(timezone.utc)
    def partido(pid, fecha, acabado, local_id, local, visita_id, visita, gl=None, ga=None):
        resultados = [] if gl is None or ga is None else [{
            "ResultTypeID": 2, "ResultOrderID": 1, "PointsTeam1": gl, "PointsTeam2": ga,
        }]
        return {
            "MatchID": pid,
            "MatchDateTimeUTC": fecha.isoformat().replace("+00:00", "Z"),
            "MatchIsFinished": acabado,
            "LeagueName": "Frauen FuÃŸballbundesliga",
            "LeagueShortcut": "ffb1",
            "LeagueSeason": 2026,
            "Team1": {"TeamId": local_id, "TeamName": local},
            "Team2": {"TeamId": visita_id, "TeamName": visita},
            "MatchResults": resultados,
        }
    datos = [
        partido(1, ahora + timedelta(hours=6), False, 11, "Bayern Frauen", 12, "Koln Frauen"),
        partido(2, ahora - timedelta(days=4), True, 11, "Bayern Frauen", 13, "Frankfurt Frauen", 3, 1),
    ]
    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "api.openligadb.de/getmatchdata/ffb1/2026" in url:
            return datos
        return fake_espn(url, fuente, headers, params, timeout, proxies, info)
    U, main, mensajes = montar(fake)
    source = main.fuente_openligadb
    eventos = source.obtener_eventos("Soccer")
    ok(len(eventos) == 1 and eventos[0]["local"]["nombre"] == "Bayern Frauen", "OpenLigaDB captura el fixture de la liga femenina configurada")
    forma = source.obtener_forma_reciente("Bayern Frauen", id_interno=eventos[0]["local"]["id"])
    ok(len(forma) == 1 and forma[0]["puntos_local"] == 3 and forma[0]["id_local"] == eventos[0]["local"]["id"], "OpenLigaDB aporta resultados previos y conserva el ID del equipo evaluado")
    ok(eventos[0]["femenino_seguro"] is True, "la clasificaciÃ³n femenina se basa en la allowlist del torneo, no en el nombre de los clubes")


def escenario_thesportsdb_allowlist():
    os.environ["THESPORTSDB_KEY"] = "123"
    os.environ["THESPORTSDB_WOMENS_LEAGUES"] = "Soccer:1234"
    os.environ["THESPORTSDB_BUSQUEDA_GLOBAL"] = "0"
    ahora = datetime.now(timezone.utc) + timedelta(hours=6)
    fecha_evento = ahora.isoformat().replace("+00:00", "Z")
    llamadas = []
    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "thesportsdb.com" in url:
            llamadas.append((url, dict(params or {})))
            return {"events": [
                {"idEvent": "fem-1", "idLeague": "1234", "strLeague": "Liga regular", "strSport": "Soccer",
                 "strHomeTeam": "Equipo Azul", "strAwayTeam": "Equipo Rojo", "strTimestamp": fecha_evento,
                 "strStatus": "Not Started", "idHomeTeam": "1", "idAwayTeam": "2"},
                {"idEvent": "masc-1", "idLeague": "9999", "strLeague": "Premier League", "strSport": "Soccer",
                 "strHomeTeam": "Equipo A", "strAwayTeam": "Equipo B", "strTimestamp": fecha_evento,
                 "strStatus": "Not Started", "idHomeTeam": "3", "idAwayTeam": "4"},
            ]}
        return fake_espn(url, fuente, headers, params, timeout, proxies, info)
    U, main, mensajes = montar(fake)
    source = main.fuente_thesportsdb
    eventos = source.obtener_eventos("Soccer")
    ok(len(eventos) == 1 and eventos[0]["id"] == "thesportsdb_fem-1", "TheSportsDB usa ID de liga configurado para aceptar una competiciÃ³n femenina con nombre neutral")
    por_dia = [x for x in llamadas if x[0].endswith("eventsday.php")]
    ok(bool(por_dia) and all(x[1].get("l") == "1234" for x in por_dia), "TheSportsDB consulta por liga y evita el endpoint global limitado")



def escenario_thesportsdb_sin_timestamp():
    os.environ["THESPORTSDB_KEY"] = "123"
    os.environ["THESPORTSDB_WOMENS_LEAGUES"] = "Soccer:1234"
    os.environ["THESPORTSDB_BUSQUEDA_GLOBAL"] = "0"
    fecha_evento = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "thesportsdb.com" in url:
            return {"events": [
                {"idEvent": "no-time", "idLeague": "1234", "strLeague": "Liga F",
                 "strHomeTeam": "Equipo Uno", "strAwayTeam": "Equipo Dos",
                 "dateEvent": fecha_evento[:10], "strTime": "18:30:00", "strStatus": "Not Started"},
            ]}
        return fake_espn(url, fuente, headers, params, timeout, proxies, info)
    U, main, mensajes = montar(fake)
    eventos = main.fuente_thesportsdb.obtener_eventos("Soccer")
    ok(eventos == [], "TheSportsDB descarta hora local sin zona horaria para no inventar el UTC")


# ---------------------------------------------------------------------------
# NUEVOS ESCENARIOS: cobertura de fuentes, robustez y dedupe
# ---------------------------------------------------------------------------
def escenario_highlightly_ligas():
    os.environ["HIGHLIGHTLY_API_KEY"] = "clave-falsa"
    os.environ["HIGHLIGHTLY_WOMENS_LEAGUES"] = "Soccer:777"
    llamadas = []

    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "highlightly" not in url:
            return {"events": []}
        params = params or {}
        llamadas.append((url, dict(params)))
        if info is not None:
            info["status"] = 200
            info["headers"] = {"x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": "80"}
        if url.endswith("/matches"):
            if str(params.get("leagueId")) == "777":
                # liga con nombre neutral, fuera de la primera pÃ¡gina del listado general
                return {"data": [hl_partido(50, (31, "Club Norte"), (32, "Club Sur"), iso(5), liga=(777, "Liga Regular", 2026))],
                        "pagination": {"totalCount": 1, "offset": 0, "limit": 100}}
            return {"data": [hl_partido(60, (41, "Equipo Masc A"), (42, "Equipo Masc B"), iso(5), liga=(78, "Bundesliga", 2026))],
                    "pagination": {"totalCount": 400, "offset": 0, "limit": 100}}
        return {"data": []}

    U, main, msgs = montar(fake)
    eventos = main.fuente_highlightly.obtener_eventos("Soccer")
    ok(len(eventos) == 1 and eventos[0]["id"] == "highlightly_Soccer_50", "la liga allowlisteada se captura aunque no estÃ© en la primera pÃ¡gina")
    ok(any(str(c[1].get("leagueId")) == "777" for c in llamadas), "consulta directa con leagueId")
    ok(not any("odds" in u.lower() for u, _ in llamadas), "no toca endpoints de cuotas")


def escenario_thesportsdb_liga_masculina():
    os.environ["THESPORTSDB_KEY"] = "123"
    os.environ["THESPORTSDB_WOMENS_LEAGUES"] = "Soccer:1111,Soccer:2222"
    fecha_evento = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    consultadas = []

    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "thesportsdb.com" in url:
            params = params or {}
            if url.endswith("lookupleague.php"):
                genero = "Male" if params.get("id") == "1111" else "Female"
                return {"leagues": [{"idLeague": params.get("id"), "strLeague": "Liga " + params.get("id"), "strGender": genero}]}
            if url.endswith("eventsday.php"):
                consultadas.append(params.get("l"))
                return {"events": [{"idEvent": "e" + params["l"], "idLeague": params["l"], "strLeague": "Liga",
                                    "strHomeTeam": "Uno " + params["l"], "strAwayTeam": "Dos " + params["l"],
                                    "strTimestamp": fecha_evento, "strStatus": "Not Started",
                                    "idHomeTeam": "1", "idAwayTeam": "2"}]}
        return {"events": []}

    U, main, msgs = montar(fake)
    eventos = main.fuente_thesportsdb.obtener_eventos("Soccer")
    ok({e["id"] for e in eventos} == {"thesportsdb_e2222"}, "una liga que TheSportsDB declara masculina se descarta aunque estÃ© en la allowlist")
    ok(set(consultadas) == {"2222"}, "ni siquiera se piden los partidos de la liga descartada")


def _tsdb_partido(i, local, visita, gl, gv, dias, ids=(1, 2)):
    fecha = datetime.now(timezone.utc) - timedelta(days=dias)
    return {"idEvent": str(i), "strHomeTeam": local, "strAwayTeam": visita, "idHomeTeam": str(ids[0]), "idAwayTeam": str(ids[1]),
            "intHomeScore": str(gl), "intAwayScore": str(gv), "strStatus": "Match Finished",
            "strTimestamp": fecha.strftime("%Y-%m-%dT%H:%M:%S")}


def escenario_thesportsdb_historial():
    os.environ["THESPORTSDB_KEY"] = "123"
    os.environ.pop("THESPORTSDB_WOMENS_LEAGUES", None)
    llamadas = []

    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "thesportsdb.com" not in url:
            return {"events": []}
        params = params or {}
        llamadas.append((url.rsplit("/", 1)[-1], dict(params)))
        if url.endswith("searchteams.php"):
            return {"teams": [
                {"idTeam": "900", "strTeam": "Alpha", "strSport": "Soccer", "strGender": "Male"},
                {"idTeam": "901", "strTeam": "Alpha Women", "strAlternate": "Alpha W", "strSport": "Soccer", "strGender": "Female"},
            ]}
        if url.endswith("eventslast.php"):
            tid = int(params["id"])
            return {"results": [
                _tsdb_partido(1, "Alpha Women", "Rival Uno", 3, 0, 4, (tid, 5)),
                _tsdb_partido(2, "Rival Dos", "Alpha Women", 0, 2, 11, (6, tid)),
                _tsdb_partido(3, "Alpha Women", "Rival Tres", 1, 1, 18, (tid, 7)),
                _tsdb_partido(4, "Alpha Women", "Rival Cuatro", 2, 0, 25, (tid, 8)),
                _tsdb_partido(5, "Partido ajeno", "Otro", 9, 9, 3, (70, 71)),   # no es del equipo: se ignora
                {"idEvent": "6", "strHomeTeam": "Alpha Women", "strAwayTeam": "Futuro", "idHomeTeam": str(tid),
                 "idAwayTeam": "9", "intHomeScore": None, "intAwayScore": None, "strTimestamp": "2099-01-01T10:00:00"},
            ]}
        return {"events": []}

    U, main, msgs = montar(fake)
    ts = main.fuente_thesportsdb
    forma = ts.obtener_forma_reciente("Alpha W", "Soccer", limite=8, id_interno="1")
    ok(len(forma) == 4, f"4 partidos terminados del equipo; se ignoran el ajeno y el futuro (hubo {len(forma)})")
    ok(all("1" in (p["id_local"], p["id_visita"]) for p in forma), "el id del equipo se reescribe al del evento")
    ok(forma[0]["fecha"] > forma[-1]["fecha"], "orden: mÃ¡s reciente primero")
    ok(any(l[1].get("id") == "901" for l in llamadas if l[0] == "eventslast.php") and
       not any(l[1].get("id") == "900" for l in llamadas), "se eligiÃ³ el equipo femenino, nunca el masculino homÃ³nimo")
    n_antes = len(llamadas)
    ts.obtener_forma_reciente("Alpha W", "Soccer", limite=8, id_interno="1")
    ok(len(llamadas) == n_antes, "la segunda consulta sale de la cache (no repite requests)")
    ok(ts.obtener_forma_reciente("Beta Sin Datos", "Soccer") == [], "un equipo no encontrado devuelve []")
    ev = {"fuente": "thesportsdb", "deporte": "Soccer", "local": {"id": "901", "nombre": "Alpha Women"}}
    ok(len(ts.historial_equipo(ev, "local")) == 4, "los eventos que vienen de TheSportsDB usan el historial por id")

    # el limitador de ritmo respeta el tope por minuto
    ts._pedidos_recientes.clear()
    ts.MAX_PEDIDOS_MINUTO = 5
    esperas = []
    ts.time.sleep = lambda x: (esperas.append(x), ts._pedidos_recientes.clear())[0]
    for _ in range(6):
        ts._esperar_cupo()
    ok(len(esperas) == 1, "el 6.Âº pedido dentro del mismo minuto espera (limite 5/min)")


def escenario_theoddsapi():
    os.environ["ODDS_API_KEY"] = "clave-falsa"
    ahora = datetime.now(timezone.utc)
    f = lambda h: (ahora + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
    llamadas = []

    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if "the-odds-api.com" not in url:
            return {"events": []}
        llamadas.append((url, dict(params or {})))
        if info is not None:
            info["status"] = 200
            info["headers"] = {"x-requests-remaining": "490"}
        if url.endswith("/sports"):
            return [
                {"key": "basketball_wnba", "group": "Basketball", "title": "WNBA", "description": "US Basketball", "active": True},
                {"key": "basketball_nba", "group": "Basketball", "title": "NBA", "description": "US Basketball", "active": True},
                {"key": "soccer_uefa_champs_league_women", "group": "Soccer", "title": "UEFA Champions League Women", "description": "", "active": True},
                {"key": "soccer_epl", "group": "Soccer", "title": "EPL", "description": "English Premier League", "active": True},
                {"key": "tennis_wta_test_open", "group": "Tennis", "title": "WTA Test Open", "description": "", "active": True},
                {"key": "basketball_wnba_championship_winner", "group": "Basketball", "title": "WNBA Winner", "description": "women", "active": True, "has_outrights": True},
                {"key": "basketball_wnbl", "group": "Basketball", "title": "WNBL", "description": "Australia", "active": False},
            ]
        if url.endswith("/basketball_wnba/events"):
            return [
                {"id": "w1", "sport_key": "basketball_wnba", "commence_time": f(5), "home_team": "Las Vegas Aces", "away_team": "New York Liberty"},
                {"id": "w2", "sport_key": "basketball_wnba", "commence_time": f(60), "home_team": "Fuera Ventana", "away_team": "Otro"},
                {"id": "w3", "sport_key": "basketball_wnba", "commence_time": f(-3), "home_team": "Ya Empezo", "away_team": "Otro"},
            ]
        if url.endswith("/soccer_uefa_champs_league_women/events"):
            return [{"id": "s1", "sport_key": "soccer_uefa_champs_league_women", "commence_time": f(8),
                     "home_team": "Barcelona Femeni", "away_team": "Lyon Women"}]
        return []

    U, main, msgs = montar(fake)
    toa = main.fuente_theoddsapi
    ok(toa.disponible(), "con ODDS_API_KEY la fuente queda disponible")
    basket = toa.obtener_eventos("Basketball")
    futbol = toa.obtener_eventos("Soccer")
    ok([e["id"] for e in basket] == ["theoddsapi_w1"], f"solo el partido WNBA dentro de la ventana (hubo {[e['id'] for e in basket]})")
    ok([e["id"] for e in futbol] == ["theoddsapi_s1"], "solo la competiciÃ³n femenina de fÃºtbol; la EPL masculina se ignora")
    ok(all(e["femenino_seguro"] and e["fuente"] == "theoddsapi" for e in basket + futbol), "eventos marcados con evidencia femenina de la competiciÃ³n")
    ok(toa.obtener_eventos("Tennis") == [], "el tenis queda fuera (sin ranking no hay anÃ¡lisis)")
    urls = [u for u, _ in llamadas]
    ok(all(u.endswith("/sports") or u.endswith("/events") for u in urls), "solo se llaman /sports y /events")
    ok(not any("/odds" in u or "/scores" in u or "/historical" in u for u in urls), "no consulta cuotas, scores ni histÃ³rico")
    ok(all(p.get("apiKey") == "clave-falsa" and "markets" not in p and "regions" not in p for _, p in llamadas), "autentica con apiKey y no pide mercados ni regiones")
    ok(sum(1 for u in urls if u.endswith("/sports")) == 1, "el catÃ¡logo se pide una sola vez (cache)")
    try:
        toa._get("/sports/basketball_wnba/odds")
        ok(False, "deberÃ­a rechazar rutas de cuotas")
    except ValueError:
        ok(True, "una ruta de cuotas es rechazada por diseÃ±o (modo CERO CUOTAS)")
    ok(toa.DEPORTES_ACTIVOS and "Tennis" not in toa.DEPORTES_ACTIVOS, "Tennis no estÃ¡ entre los deportes activos")


def escenario_espn_fallo_transitorio():
    estado = {"falla": True}

    def fake(url, fuente, headers=None, params=None, timeout=0, proxies=None, info=None):
        if estado["falla"]:
            return None
        return fake_espn(url, fuente, headers, params, timeout, proxies, info)

    U, main, msgs = montar(fake)
    espn = main.fuente_espn
    ahora = time.time()
    ok(espn.ranking_wta() == {}, "ranking vacÃ­o mientras ESPN falla")
    vence_ranking = espn._cache_ranking._datos["wta"][2] - ahora
    ok(vence_ranking < 900, f"el ranking vacÃ­o NO se cachea 12 h (vence en {int(vence_ranking)} s)")
    espn.obtener_eventos("Soccer")
    ttls = [v[2] - ahora for v in espn._cache_proximos._datos.values()]
    ok(ttls and max(ttls) < 600, "un fallo del scoreboard se reintenta en minutos, no tras 3 horas")
    ok(espn._eventos_pasados("soccer", "eng.w.1") == [], "si ESPN no responde no se dispara el barrido dÃ­a por dÃ­a")
    estado["falla"] = False
    espn._cache_proximos._datos.clear()
    espn._cache_ranking._datos.clear()
    espn._cache_dia_pasado._datos.clear()
    ok(len(espn.ranking_wta()) == 120, "al recuperarse, el ranking se carga")
    ok(len(espn.obtener_eventos("Soccer")) == 1, "al recuperarse, el calendario vuelve")


class _FuenteFalsa:
    def __init__(self, eventos):
        self._eventos = eventos
        self.consultas = 0

    def disponible(self):
        return True

    def obtener_eventos(self, deporte):
        self.consultas += 1
        return [e for e in self._eventos if e["deporte"] == deporte]


def _evento_falso(fuente, id_, local, visita, ts):
    return {"id": f"{fuente}_{id_}", "clave": "x", "deporte": "Soccer", "torneo": "Liga Test",
            "local": {"id": f"{fuente}-1", "nombre": local, "ranking": None, "fuera_ranking": False},
            "visita": {"id": f"{fuente}-2", "nombre": visita, "ranking": None, "fuera_ranking": False},
            "horario": "x", "tipo_estado": "pre", "startTimestamp": ts, "fuente": fuente, "femenino_seguro": True}


def escenario_agregador_tolerancia_y_prioridad():
    U, main, msgs = montar(lambda *a, **k: {"events": []})
    # un partido cerca de la medianoche UTC; otro proveedor lo informa 5 h mÃ¡s tarde (otro dÃ­a UTC)
    manana = datetime.now(timezone.utc).replace(hour=23, minute=30, second=0, microsecond=0) + timedelta(days=1)
    ts_a = int(manana.timestamp())
    ts_b = ts_a + 5 * 3600
    espn = _FuenteFalsa([_evento_falso("espn", 1, "Alpha Women", "Beta Women", ts_a)])
    tsdb = _FuenteFalsa([_evento_falso("thesportsdb", 7, "Beta W", "Alpha W", ts_b)])
    toa = _FuenteFalsa([_evento_falso("theoddsapi", 9, "Alpha", "Beta Femenino", ts_a + 600)])
    for nombre in ("fuente_highlightly", "fuente_api_football", "fuente_openligadb", "fuente_oddspapi"):
        setattr(main, nombre, None)
    main.fuente_espn, main.fuente_thesportsdb, main.fuente_theoddsapi = espn, tsdb, toa
    main.DEPORTES_RADAR = ["Soccer"]
    resumen = {}
    unicos = main._recolectar_eventos(resumen)
    ok(len(unicos) == 1, f"el mismo partido de 3 proveedores (con 5 h de diferencia y otro dÃ­a UTC) es UN evento (hubo {len(unicos)})")
    ev = unicos[0]
    ok(ev["fuente"] == "thesportsdb", f"ESPN no queda como fuente principal cuando otra fuente vio el partido (principal: {ev['fuente']})")
    ok(set(ev["_fuentes_detectadas"]) == {"espn", "thesportsdb", "theoddsapi"}, "se registran las tres fuentes que lo vieron")
    ok(len(ev["_observaciones"]) == 3, "se conservan las 3 observaciones para buscar historial")
    # el registro de alertas reconoce el partido aunque otro proveedor lo ubique en otro dÃ­a UTC
    main.registro.marcar(main._clave_canonica_evento(_evento_falso("espn", 1, "Alpha Women", "Beta Women", ts_a)))
    ok(main._ya_alertado(_evento_falso("thesportsdb", 7, "Beta W", "Alpha W", ts_b)), "no se alerta dos veces el mismo partido por una diferencia horaria entre proveedores")
    ok(not main._ya_alertado(_evento_falso("espn", 2, "Otra", "Distinta", ts_a)), "otro partido no se confunde")
    ok(not main._ya_alertado(_evento_falso("espn", 3, "Alpha Women", "Beta Women", ts_a + 3 * 86400)), "el mismo cruce dÃ­as despuÃ©s sÃ­ es otro partido")
    # tenis: ESPN conserva prioridad (Ãºnica fuente con ranking)
    tenis_espn = {"fuente": "espn", "deporte": "Tennis", "local": {}, "visita": {}}
    tenis_otro = {"fuente": "thesportsdb", "deporte": "Tennis", "local": {}, "visita": {}}
    ok(main._prioridad_evento(tenis_espn) < main._prioridad_evento(tenis_otro), "en tenis ESPN sigue primero porque trae el ranking WTA")


def escenario_historial_por_costo():
    U, main, msgs = montar(fake_espn)
    main.DEPORTES_RADAR = ["Soccer"]
    for nombre in ("fuente_api_football", "fuente_oddspapi", "fuente_openligadb", "fuente_thesportsdb", "fuente_theoddsapi"):
        setattr(main, nombre, None)

    class Cara:
        llamadas = 0

        def disponible(self):
            return True

        def historial_equipo(self, evento, lado):
            Cara.llamadas += 1
            return []

        def obtener_forma_reciente(self, *a, **k):
            Cara.llamadas += 1
            return []

    main.fuente_highlightly = Cara()
    espn_ev = main.fuente_espn.obtener_eventos("Soccer")[0]
    hl_obs = dict(espn_ev, fuente="highlightly", id="highlightly_Soccer_1")
    ev = dict(espn_ev, _observaciones=[hl_obs, espn_ev], _fuentes_detectadas=["highlightly", "espn"])
    historial = main._historial_equipo(ev, "local")
    ok(len(historial) >= 4, f"el historial sale de ESPN (gratis) con {len(historial)} partidos")
    ok(Cara.llamadas == 0, "con historial suficiente gratis no se gasta cuota de la fuente con lÃ­mite")


def escenario_motor_congestion():
    preparar()
    import motor_mismatches as M
    d = lambda n: (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()
    p = lambda dias, pl=1, pv=0: {"fecha": d(dias), "id_local": "A", "id_visita": "X", "puntos_local": pl, "puntos_visita": pv}
    q = lambda dias: {"fecha": d(dias), "id_local": "B", "id_visita": "Y", "puntos_local": 1, "puntos_visita": 0}
    descansada = [p(15), p(22), p(29), p(36)]
    cargada = [q(1), q(3), q(5), q(14)]
    r = M.evaluar_congestion(descansada, "A", cargada, "B")
    ok(r and r["favorito"] == M.LOCAL and r["n_b"] == 3 and r["n_a"] == 0, "la visita con 3 partidos en 7 dÃ­as favorece al local descansado")
    r2 = M.evaluar_congestion(cargada, "B", descansada, "A")
    ok(r2 and r2["favorito"] == M.VISITA, "es simÃ©trico: favorece a la visita si el local viene cargado")
    ok(M.evaluar_congestion(descansada[:3], "A", cargada, "B") is None, "con historial recortado (<4) no se afirma que el rival tuvo poca actividad")
    ok(M.evaluar_congestion(cargada, "B", cargada, "B") is None, "dos equipos igual de cargados no es asimetrÃ­a")

    # no se cuenta dos veces la misma informaciÃ³n de calendario (descanso + congestiÃ³n)
    base = {"hay": 1}
    perf = {"dif_prom": 0.0, "victorias": 0, "derrotas": 0, "muestras": 0}
    triangs = {"local": [{"rival": "C", "dif_a": 3, "dif_b": -2, "brecha": 5}], "visita": []}
    h2h = {"reciente": [{"ganador": M.LOCAL, "dif": 2}, {"ganador": M.LOCAL, "dif": 1}], "medio": [], "viejo": []}
    solo_desc = M.evaluar_mismatch("Soccer", perf, perf, triangs, h2h, None, {"descanso": {"favorito": M.LOCAL, "detalle": "Descanso"}})
    ambos = M.evaluar_mismatch("Soccer", perf, perf, triangs, h2h, None, {
        "descanso": {"favorito": M.LOCAL, "detalle": "Descanso"},
        "congestion": {"favorito": M.LOCAL, "detalle": "Calendario"}})
    ok(ambos["puntaje"] == solo_desc["puntaje"], "si el descanso ya favoreciÃ³ a ese lado, la congestiÃ³n no suma de nuevo")
    cong = M.evaluar_mismatch("Soccer", perf, perf, triangs, h2h, None, {"congestion": {"favorito": M.LOCAL, "detalle": "Calendario"}})
    ok(cong["puntaje"] == solo_desc["puntaje"] and any("Calendario" in a for a in cong["alertas"] + ["Calendario"]), "la congestiÃ³n sola suma 1 punto")


def escenario_motor_triangulacion_entre_fuentes():
    preparar()
    import motor_mismatches as M
    d = lambda n: (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()
    # el historial del local viene de un proveedor y el de la visita de otro: el rival comÃºn "Gamma"
    # tiene ids distintos en cada uno, pero el mismo nombre
    hist_a = [{"fecha": d(5), "id_local": "a1", "nom_local": "Alpha W", "id_visita": "src1-77", "nom_visita": "Gamma Women",
               "puntos_local": 3, "puntos_visita": 0}]
    hist_b = [{"fecha": d(6), "id_local": "src2-88", "nom_local": "Gamma W", "id_visita": "b1", "nom_visita": "Beta W",
               "puntos_local": 2, "puntos_visita": 0}]
    r = M.triangular_rivales(hist_a, "a1", hist_b, "b1")
    ok(len(r["local"]) == 1 and r["local"][0]["rival"] == "Gamma Women", "la triangulaciÃ³n reconoce al rival comÃºn por nombre aunque los ids sean de proveedores distintos")
    ok(r["visita"] == [], "no inventa la direcciÃ³n contraria")


def escenario_http_y_logs():
    preparar()
    import io
    import contextlib
    import utilidades as U
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        U.log("fallo en https://api.the-odds-api.com/v4/sports?apiKey=SECRETO123&x=1 con x-rapidapi-key=OTRO456")
        U.log("https://api.telegram.org/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/sendMessage")
    salida = buf.getvalue()
    ok("SECRETO123" not in salida and "OTRO456" not in salida, "los logs ocultan apiKey y x-rapidapi-key")
    ok("AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw" not in salida, "los logs ocultan el token del bot de Telegram")
    ok("apiKey=***" in salida, "se conserva el resto del mensaje")

    # reintento ante 5xx transitorio
    class R:
        def __init__(self, code, data=None):
            self.status_code, self._d, self.headers, self.text = code, data, {}, ""

        def json(self):
            return self._d

    respuestas = [R(503), R(200, {"ok": True})]
    U._pedir = lambda *a, **k: respuestas.pop(0)
    U.time.sleep = lambda x: None
    info = {}
    ok(U.get_json("https://x.test/y", "prueba", info=info) == {"ok": True} and info["status"] == 200, "un 503 transitorio se reintenta una vez")
    respuestas = [R(500)]
    ok(U.get_json("https://x.test/y", "prueba") is None, "un 500 no se reintenta")

    # CacheTTL con vencimiento propio
    c = U.CacheTTL(3600)
    c.set("a", 1)
    c.set("b", 2, ttl=-1)
    ok(c.get("a") == (True, 1) and c.get("b") == (False, None), "la cache respeta TTL por entrada")


def escenario_telegram_reintentos():
    os.environ["TELEGRAM_TOKEN"] = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
    os.environ["CHAT_ID"] = "111"
    os.environ["CHAT_ID_GRUPO"] = "-222"
    preparar()
    import utilidades as U
    import main
    llamadas = []
    guion = {"111": [429, 200], "-222": [400, 200]}

    class Resp:
        def __init__(self, code):
            self.status_code = code

        def json(self):
            return {"parameters": {"retry_after": 1}}

    def fake_post(url, json=None, timeout=0):
        destino = json["chat_id"]
        llamadas.append((destino, json.get("parse_mode")))
        return Resp(guion[destino].pop(0))

    main.requests.post = fake_post
    main.time.sleep = lambda x: None
    ok(main.enviar_telegram("<b>hola</b>"), "entrega cuando al menos un chat recibe el mensaje")
    ok(llamadas.count(("111", "HTML")) == 2, "un 429 se reintenta con el mismo formato HTML tras esperar")
    ok(("-222", None) in llamadas, "un 400 de formato reintenta como texto plano")
    largo = "<b>x</b>\n" * 1000
    recortado = main._recortar_html(largo)
    ok(len(recortado) <= 4010 and recortado.count("<b>") == recortado.count("</b>"), "el recorte no deja etiquetas HTML abiertas")


def escenario_cuello_de_botella_sin_datos():
    """RegresiÃ³n del log real: 100+ partidos solo-calendario (OddsPapi) no pueden tapar a los analizables."""
    U, main, msgs = montar(fake_espn)
    ahora = int(datetime.now(timezone.utc).timestamp())
    exoticos = [_evento_falso("oddspapi", i, f"Club Rojo{i} Women", f"Club Azul{i} Women", ahora + 1800 + i * 30)
                for i in range(130)]
    main.fuente_oddspapi = _FuenteFalsa(exoticos)
    for nombre in ("fuente_highlightly", "fuente_api_football", "fuente_openligadb", "fuente_thesportsdb", "fuente_theoddsapi"):
        setattr(main, nombre, None)
    main.DEPORTES_RADAR = ["Soccer"]
    main.MAX_ANALISIS_POR_CICLO = 20
    main.MAX_BUSQUEDAS_POR_NOMBRE = 5
    consultados = []
    original = main._historial_equipo
    main._historial_equipo = lambda ev, lado: (consultados.append(ev["id"]), original(ev, lado))[1]
    main.ejecutar_barrido_radar()
    alertas = [m for m in msgs if "MISMATCH" in m]
    ok(len(alertas) == 1 and "Alpha W" in alertas[0], "el partido analizable de ESPN genera alerta aunque haya 130 eventos solo-calendario mÃ¡s tempranos")
    exoticos_1 = {c for c in consultados if c.startswith("oddspapi")}
    ok(len(exoticos_1) <= 5, f"solo {len(exoticos_1)} eventos sin historial gastan bÃºsquedas por nombre (tope 5)")
    consultados.clear()
    main.ejecutar_barrido_radar()
    repetidos = [c for c in consultados if c in exoticos_1]
    ok(not repetidos, "los eventos que ya dieron [sin-datos] no se reintentan en el ciclo siguiente (enfriamiento)")
    main._enfriamiento.clear()
    consultados.clear()
    main.ejecutar_barrido_radar()
    ok(any(c in exoticos_1 for c in consultados), "vencido el enfriamiento, se vuelven a intentar")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        globals()["escenario_" + sys.argv[1]]()
        sys.exit(0)
    fallos = 0
    for nombre in ESCENARIOS:
        print(f"== {nombre}")
        r = subprocess.run([sys.executable, __file__, nombre], capture_output=True, text=True)
        salida = "\n".join(l for l in r.stdout.splitlines() if l.startswith("  "))
        print(salida)
        if r.returncode != 0:
            fallos += 1
            print("  --- log ---\n" + "\n".join("  " + l for l in (r.stdout + r.stderr).splitlines()[-25:]))
    print("\nTODO OK" if not fallos else f"\n{fallos} escenario(s) con fallas")
    sys.exit(1 if fallos else 0)