"""
test_radar.py — pruebas offline del radar (no usan internet ni Telegram).
Uso:  python test_radar.py
Cada escenario corre en un proceso aparte para que no se contaminen los caches.
"""
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ESCENARIOS = ["espn_futbol", "espn_tenis", "api_sports", "cuota_agotada", "dedupe_y_repeticion", "filtros",
              "highlightly", "highlightly_nombres", "oddspapi"]


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
    ok(len(alertas) == 1, f"1 alerta de fútbol (hubo {len(alertas)})")
    ok("Alpha W" in alertas[0] and "Favorito:</b> Alpha W" in alertas[0], "el favorito es Alpha W (local)")
    ok("Triangulación" in alertas[0] and "Forma" in alertas[0], "incluye forma y triangulación")
    ok("Momentum" not in alertas[0], "el momentum no se cuenta dos veces")
    ok("Estado del mercado" not in alertas[0], "la alerta no trae sección de cuotas")
    ok("ðŸ" not in alertas[0] and "🚨" in alertas[0], "los emojis salen bien")


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
    ok("Bayern Frauen" in alertas[0] and "Bayern vs" not in alertas[0], "se analizó la liga femenina y NO la masculina")
    fixtures_por_fecha = [c for c in llamadas if "date" in c[1]]
    fixtures_por_liga = [c for c in llamadas if "league" in c[1]]
    ok(len(fixtures_por_fecha) == 2, f"2 pedidos de listado (hoy y mañana), hubo {len(fixtures_por_fecha)}")
    ok(len(fixtures_por_liga) == 1, f"1 pedido de historial para toda la liga (antes: 3 por partido), hubo {len(fixtures_por_liga)}")
    ok(len(llamadas) == 3, f"3 requests en total para el barrido completo ({len(llamadas)})")
    ok(main.fuente_api_football.DEPORTES_ACTIVOS == ["Soccer"], "API-Sports consulta solo Soccer por defecto")
    ok(main.fuente_api_football.MAX_LIGAS_POR_DEPORTE == 2, "máximo 2 ligas por deporte")


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
    ok(len(llamadas) == 1, f"tras el error de cuota no vuelve a pedir en todo el día (pedidos: {len(llamadas)})")
    ok(main.fuente_api_football.presupuesto.restantes() == 0, "el presupuesto queda en 0 hasta mañana")

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
    ok(hay and fav == M.LOCAL and pts == 3 and "🔴" in det, "tenis: top 8 vs fuera del ranking = 3 pts, emoji OK")
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
    ok("H2H" in alertas[0] and "Forma" in alertas[0] and "Triangulación" in alertas[0], "incluye forma, triangulación y H2H")
    ok("Estado del mercado" not in alertas[0], "sin sección de cuotas")
    ok(all(h.get("x-rapidapi-key") == "clave-falsa" for _, _, h in llamadas), "autentica con el header x-rapidapi-key")
    ok(all("/v1/" not in u for u, _, _ in llamadas), "usa las rutas actuales (sin /v1/)")
    ok(sum(1 for u, _, _ in llamadas if u.endswith("/matches")) == 2, "1 pedido de partidos por fecha (hoy y mañana)")

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
       "el H2H usa los ids del evento y conserva quién fue local ese día (Beta local perdió 0-2 con Alpha)")
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
    ok(len(soccer) == 1 and soccer[0]["local"]["nombre"] == "Barcelona", f"1 evento femenino de fútbol (hubo {len(soccer)}): La Liga masculina, +24 h y terminados se ignoran")
    ok(len(voley) == 1, "1 evento femenino de vóley")
    ok(len(llamadas) == 1, f"1 solo pedido para todos los deportes (hubo {len(llamadas)})")
    ok("sportId" not in llamadas[0][1] and llamadas[0][2].get("X-API-Key") == "clave-falsa", "sin sportId y con header X-API-Key")
    ok(op.obtener_h2h(soccer[0]) == [] and op.historial_equipo(soccer[0], "local") == [], "forma y H2H apagados por defecto (no gastan cuota)")
    ok(len(llamadas) == 1, "forma / H2H apagados no hacen pedidos")


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
