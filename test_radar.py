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

ESCENARIOS = ["espn_futbol", "espn_tenis", "api_sports", "cuota_agotada", "dedupe_y_repeticion", "filtros"]


def iso(horas=0, dias=0, z=True):
    d = datetime.now(timezone.utc) + timedelta(hours=horas, days=dias)
    return d.strftime("%Y-%m-%dT%H:%MZ") if z else d.isoformat()


def preparar():
    os.environ["PORT"] = "0"
    os.environ["DATA_DIR"] = tempfile.mkdtemp()
    for k in ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "ODDS_API_KEY"):
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
