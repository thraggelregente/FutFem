"""Regresiones de cricket separado, vigencia, detalles ambiguos y acceso gratuito."""
import test_radar
import io
import json
import time
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import fuente_cricsheet as C
import fuente_balldontlie as BD
import fuente_sportscore as S
import motor_cricket as M
import main as B
import utilidades as U
import mensajes


def raw_cricket():
    return {"info": {"gender": "female", "match_type": "T20", "overs": 20,
            "teams": ["Australia", "Bangladesh"], "dates": [(datetime.now(timezone.utc)-timedelta(days=3)).date().isoformat()],
            "event": {"name": "Australia Women vs Bangladesh Women"}, "team_type": "international",
            "outcome": {"winner": "Australia", "by": {"wickets": 8}}}}


def raw_ss():
    return {"home": "Australia Women", "away": "Bangladesh Women", "competition": "ODI Series Australia vs Bangladesh, Women",
            "time": U.ts_a_iso_utc(time.time()+3600), "status": "upcoming", "status_text": "Not started",
            "home_score": None, "away_score": None, "url": "/cricket/match/bangladesh-women-vs-australia-women/"}


class CricketContextoTests(unittest.TestCase):
    def test_resultados_cricsheet_no_confunden_genero_formato_dls_y_empate(self):
        raw = raw_cricket()
        self.assertIsNotNone(C.normalizar(raw, "1"))
        for cambios in ({"gender": "male"}, {"match_type": "Test"}, {"overs": 10},
                         {"event": {"name": "Under 19 Women Cup"}},
                         {"outcome": {"winner": "Australia", "by": {"runs": 40}, "method": "D/L"}},
                         {"outcome": {"result": "tie", "eliminator": "Australia"}},
                         {"outcome": {"winner": "Australia", "by": {"wickets": 11}}}):
            self.assertIsNone(C.normalizar({"info": dict(raw["info"], **cambios)}, "1"))

    def test_zip_lee_solo_json_y_resultados_compactos(self):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("123.json", json.dumps(raw_cricket()))
            z.writestr("README.txt", "Aviso de licencia")
        rows = C.leer_zip(out.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertNotIn("innings", rows[0])
        self.assertEqual(rows[0]["ganadora"], C.identidad("Australia Women"))

    def test_cricsheet_desactivado_no_usa_cache_y_archivo_viejo_expira(self):
        with patch.object(C, "ACTIVO", False), patch.object(C, "_anio") as cargar:
            self.assertEqual(C.historial({}), [])
            cargar.assert_not_called()
        raw = raw_cricket()
        raw["info"]["dates"] = ["2025-01-01"]
        enero_2027 = datetime(2027, 1, 3, tzinfo=timezone.utc).timestamp()
        self.assertIsNone(C.normalizar(raw, "viejo", enero_2027))

    def test_indexacion_grande_no_bloquea_el_radar(self):
        with patch.object(C, "_worker", None), patch.object(C._cache, "get", return_value=(False, None)), \
             patch("fuente_cricsheet.Thread.start") as iniciar, patch.object(C, "_anio") as descargar:
            self.assertEqual(C.historial({}), [])
            iniciar.assert_called_once()
            descargar.assert_not_called()

    def test_calendario_cricket_no_convierte_marcadores_a_puntos(self):
        raw = raw_ss()
        p = S.normalizar(raw, deporte="Cricket")
        self.assertEqual(p["formato_cricket"], "ODI")
        self.assertEqual(p["tipo_equipo_cricket"], "international")
        self.assertIsNone(S.normalizar(dict(raw, status="finished", home_score="222/1", away_score="220/6"), deporte="Cricket"))
        self.assertIsNone(S.normalizar(dict(raw, competition="Test Series Women"), deporte="Cricket"))
        self.assertIsNone(S.normalizar(dict(raw, competition="ODI Women Under 19"), deporte="Cricket"))
        self.assertIn(B._clave_canonica_evento(p), B._claves_equivalentes(p))
        self.assertNotEqual(B._clave_canonica_evento(p), B._clave_canonica_evento(dict(p, formato_cricket="T20")))
        self.assertNotEqual(B._clave_canonica_evento(p), B._clave_canonica_evento(dict(p, startTimestamp=p["startTimestamp"]+3600)))

    def test_motor_cricket_exige_forma_margenes_h2h_y_vigencia(self):
        ev = S.normalizar(raw_ss(), deporte="Cricket")
        a, b = (C.identidad(ev[l]["nombre"]) for l in ("local", "visita"))
        rows = []
        for i in range(6):
            rival = b if i < 2 else "otro"+str(i)
            base = {"id": str(i), "fecha": (datetime.now(timezone.utc)-timedelta(days=i+2)).date().isoformat(),
                    "formato": "ODI", "tipo_equipo": "international", "equipos": [a, rival],
                    "ganadora": a, "unidad": "runs", "margen": 100}
            rows.append(base)
            if i >= 2:
                rows.append(dict(base, id="b"+str(i), equipos=[b, "rival"+str(i)], ganadora="rival"+str(i)))
        self.assertTrue(M.evaluar(ev, rows)["alertar"])
        self.assertFalse(M.evaluar(ev, rows[:2])["alertar"])
        self.assertFalse(M.evaluar(ev, [dict(p, formato="T20") for p in rows])["alertar"])
        self.assertFalse(M.evaluar(ev, [dict(p, fecha="2020-01-01") for p in rows])["alertar"])
        self.assertFalse(M.evaluar(ev, [dict(p, fecha="2099-01-01") for p in rows])["alertar"])
        self.assertFalse(M.evaluar(ev, [dict(p, margen=1) for p in rows])["alertar"])
        self.assertFalse(M.evaluar(ev, rows[:1]*50)["alertar"])
        club = dict(ev, tipo_equipo_cricket="club", temporada_cricket="2026")
        club_rows = [dict(p, tipo_equipo="club", competicion=ev["torneo"], temporada="2026") for p in rows]
        self.assertTrue(M.evaluar(club, club_rows)["alertar"])
        self.assertFalse(M.evaluar(club, [dict(p, temporada="2025") for p in club_rows])["alertar"])
        club.pop("temporada_cricket")
        self.assertFalse(M.evaluar(club, club_rows)["alertar"])

    def test_clubes_no_mezclan_competiciones(self):
        ev = S.normalizar(raw_ss(), deporte="Cricket")
        ev["tipo_equipo_cricket"] = "club"
        self.assertFalse(M.evaluar(ev, [dict(p, tipo_equipo="club", competicion="Otra liga")
                                     for p in [C.normalizar(raw_cricket(), "1")]])["alertar"])

    def test_cricket_usa_motor_propio_y_no_historial_comercial(self):
        ev = S.normalizar(raw_ss(), deporte="Cricket")
        ev["torneo"] = raw_ss()["competition"]
        with patch.object(B, "_ya_alertado", return_value=False), patch.object(C, "historial", return_value=[]), \
             patch.object(B, "_historial_equipo") as general, patch.object(B.motor_mismatches, "evaluar_mismatch") as motor:
            self.assertTrue(B._procesar_evento(ev, B._nuevo_stat(), time.time()))
            general.assert_not_called()
            motor.assert_not_called()

    def test_detalle_mismo_slug_de_otro_dia_no_se_usa(self):
        raw = raw_ss()
        ev = S.normalizar(raw, deporte="Cricket")
        with patch.object(S.cliente, "pedir", return_value={"sport": "cricket", "match": dict(raw, time=U.ts_a_iso_utc(time.time()-86400))}):
            self.assertIsNone(S.detalle_verificado(ev))
        with patch.object(S.cliente, "pedir", return_value={"sport": "cricket", "match": dict(raw, home="Otro Women")}):
            self.assertIsNone(S.detalle_verificado(ev))
        with patch.object(S.cliente, "pedir", return_value={"sport": "cricket", "match": dict(raw, status_text="Canceled")}):
            self.assertFalse(S.permite_alerta(ev))

    def test_h2h_usa_cruces_fechados_no_resumen_de_carrera(self):
        raw = dict(raw_ss(), home="A Women", away="B Women", competition="Liga Women",
                   time=U.ts_a_iso_utc(time.time()-150*86400), status="finished", status_text="Finished", home_score=3, away_score=0)
        ev = S.normalizar(dict(raw, time=U.ts_a_iso_utc(time.time()+3600), status="upcoming", home_score=None, away_score=None,
                              url="/football/match/a-women-vs-b-women/"))
        with patch.object(S, "_resolver", side_effect=["a-women", "b-women"]), \
             patch.object(S.cliente, "pedir", return_value={"matches": [raw, dict(raw, competition="Otra Women"), dict(raw, away="C Women")],
                                                          "summary": {"team1_wins": 100}}):
            self.assertEqual(len(S.h2h_partido(ev)), 1)

    def test_estadisticas_usan_lado_correcto_y_no_datos_parciales(self):
        ev = {"deporte": "Soccer", "local": {"id": "a"}, "visita": {"id": "b"}}
        hf = [{"id_local": "a", "id_visita": "x"}]*2
        hr = [{"id_local": "x", "id_visita": "b"}]*2
        raw = {"status": "finished", "stats": [{"label": "Shots on Target", "home": 8, "away": 2}]}
        with patch.object(S, "detalle_verificado", return_value=raw):
            evidencia = S.contexto_estadistico(ev, (hf, hr))
            self.assertIn("8.0 / 2.0", evidencia[0])
            self.assertEqual(S.contexto_estadistico(ev, (hf[:1], hr)), [])
        with patch.object(S, "detalle_verificado", return_value=dict(raw, status="upcoming")):
            self.assertEqual(S.contexto_estadistico(ev, (hf, hr)), [])

    def test_alineacion_confirmada_no_infiere_bajas(self):
        ev = S.normalizar(raw_ss(), deporte="Cricket")
        ev["deporte"] = "Soccer"
        raw = dict(raw_ss(), lineups={"confirmed": True, "home_xi": [{"name": str(i)} for i in range(11)],
                                    "away_xi": [{"name": str(i)} for i in range(11)]})
        with patch.object(S, "detalle_verificado", return_value=raw):
            self.assertEqual(len(S.contexto_alerta(ev)), 1)
        with patch.object(S, "detalle_verificado", return_value=dict(raw, lineups={"confirmed": False})):
            self.assertEqual(S.contexto_alerta(ev), [])

    def test_balldontlie_sin_key_no_pide_y_final_no_es_programado(self):
        with patch.object(BD, "API_KEY", ""), patch.object(U, "get_json") as red:
            self.assertEqual(BD.obtener_eventos("Basketball"), [])
            self.assertEqual(BD.obtener_eventos("Cricket"), [])
            red.assert_not_called()
        raw = {"id": 1, "date": U.ts_a_iso_utc(time.time()+3600), "season": datetime.now(timezone.utc).year,
               "status_state": "scheduled", "home_team": {"id": 1, "full_name": "Liberty"},
               "visitor_team": {"id": 2, "full_name": "Aces"}, "home_score": 0, "away_score": 0}
        self.assertIsNotNone(BD.normalizar(raw))
        self.assertIsNone(BD.normalizar(dict(raw, status_state="in_progress")))
        self.assertIsNone(BD.normalizar(dict(raw, status_state="canceled")))
        self.assertIsNone(BD.normalizar(dict(raw, season=2000)))

    def test_atribucion_y_etiqueta_experimental(self):
        texto = mensajes.alerta("Cricket", "Liga", "A", "B", "Hoy", ["Historial parcial"], "A", "Experimental",
                                ["sportscore", "cricsheet"], "CANDIDATO CRICKET — EXPERIMENTAL")
        self.assertIn("evaluación experimental", texto)
        self.assertIn("ODC-By", texto)
        self.assertIn("Powered by SportScore", texto)


if __name__ == "__main__":
    unittest.main()
