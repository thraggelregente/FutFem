with open("main.py", "r") as f:
    content = f.read()

import re

old_block = """class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        payload = {
            "service": "radar-femenino",
            "revision": "repo-cleanup-v1",
            "status": estado_salud(),
            "analysis_last_sweep": ESTADO["analizados"],
            "budgets": ESTADO["presupuestos"],
            "http_last_sweep": ESTADO.get("http_last_sweep", {}),
            "persistence": U.modo_persistencia(),
            "sports_scope": "women_only",
            "market_data": False,
            "uptime_seconds": int(time.time() - ESTADO["inicio"]),
            "sweeps": ESTADO["barridos"],
            "last_sweep_utc": ESTADO["ultimo_barrido_utc"],
            "last_sweep_seconds": ESTADO["ultimo_barrido_segundos"],
            "unique_events_last_sweep": ESTADO["eventos_unicos"],
            "sources": list(ESTADO["fuentes"]),
            "results_ledger": ESTADO["libro_resultados"],
        }
        cricsheet = globals().get("fuente_cricsheet")
        if cricsheet and "cricsheet" in payload["budgets"]:
            payload["budgets"] = dict(payload["budgets"])
            payload["budgets"]["cricsheet"] = dict(payload["budgets"]["cricsheet"], **cricsheet.estado())
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(503 if payload["status"] == "degraded" else 200)"""

new_block = """class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/cobertura") and globals().get("cobertura"):
            payload = cobertura.reporte()
            status_code = 200
        else:
            payload = {
                "service": "radar-femenino",
                "revision": "repo-cleanup-v1",
                "status": estado_salud(),
                "analysis_last_sweep": ESTADO["analizados"],
                "budgets": ESTADO["presupuestos"],
                "http_last_sweep": ESTADO.get("http_last_sweep", {}),
                "persistence": U.modo_persistencia(),
                "sports_scope": "women_only",
                "market_data": False,
                "uptime_seconds": int(time.time() - ESTADO["inicio"]),
                "sweeps": ESTADO["barridos"],
                "last_sweep_utc": ESTADO["ultimo_barrido_utc"],
                "last_sweep_seconds": ESTADO["ultimo_barrido_segundos"],
                "unique_events_last_sweep": ESTADO["eventos_unicos"],
                "sources": list(ESTADO["fuentes"]),
                "results_ledger": ESTADO["libro_resultados"],
            }
            cricsheet = globals().get("fuente_cricsheet")
            if cricsheet and "cricsheet" in payload["budgets"]:
                payload["budgets"] = dict(payload["budgets"])
                payload["budgets"]["cricsheet"] = dict(payload["budgets"]["cricsheet"], **cricsheet.estado())
            status_code = 503 if payload["status"] == "degraded" else 200

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open("main.py", "w") as f:
        f.write(content)
    print("Patch applied successfully.")
else:
    print("Could not find the block to replace.")
