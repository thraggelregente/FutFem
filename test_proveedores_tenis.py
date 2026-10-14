"""Regresiones de contratos públicos y casos de tenis; sin red ni credenciales."""
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import test_radar  # Inicializa DATA_DIR temporal y deshabilita Telegram antes de importar fuentes.
import utilidades as U
import fuente_wta as W
import fuente_pwhl as P
import fuente_highlightly as H
import fuente_thesportsdb as S
import fuente_oddspapi as O
import motor_tenis as T
import motor_mismatches as M


def ev(rf=20, rr=300, wc=False):
    return {"local": {"nombre": "Favorita", "ranking": rf, "ranking_fuente": "WTA oficial", "ranking_fecha": "2026-10-12"},
            "visita": {"nombre": "Rival", "ranking": rr, "entry": "WC" if wc else "",
                       "entry_fuente": "WTA cuadro oficial", "ranking_fuente": "WTA oficial", "ranking_fecha": "2026-10-12"},
            "superficie": "Hard"}


def perfil(exp=100, n=10, rank=150, gano=True):
    rows = [{"ts": int(time.time()) - (i + 1) * 86400, "gano": gano, "superficie": "Hard", "ranking_rival": rank}
            for i in range(n)]
    return {"partidos": rows, "recientes": rows[:10], "experiencia_carrera_wta": exp,
            "muestras_2anios": n, "cobertura_completa_2anios": True, "mejor_ranking": None}


class ProveedoresTenisTests(unittest.TestCase):
    def test_wc_debut_documentado_vs_profesional_fuera_top400(self):
        r = T.evaluar(ev(1026, None, True), {M.LOCAL: perfil(60), M.VISITA: perfil(0, 0)})
        self.assertTrue(r["alertar"])
        self.assertEqual(r["tipo"], "ASIMETRÍA TENIS FEMENINO")
        self.assertEqual(r["favorito"], M.LOCAL)

    def test_ausencia_de_datos_no_se_convierte_en_amateur(self):
        p = perfil(0, 0)
        p["cobertura_completa_2anios"] = False
        r = T.evaluar(ev(1026, None, True), {M.LOCAL: perfil(60), M.VISITA: p})
        self.assertFalse(r["alertar"])
        r = T.evaluar(ev(1026, None, True), {M.LOCAL: perfil(60), M.VISITA: None})
        self.assertFalse(r["alertar"])

    def test_wc_profesional_no_es_senal_de_debilidad(self):
        r = T.evaluar(ev(100, 120, True), {M.LOCAL: perfil(100), M.VISITA: perfil(200)})
        self.assertFalse(r["alertar"])

    def test_regreso_ex_top_no_se_trata_como_novata(self):
        rival = perfil(400, 0)
        rival["mejor_ranking"] = 1
        r = T.evaluar(ev(20, 300, True), {M.LOCAL: perfil(), M.VISITA: rival})
        self.assertFalse(r["alertar"])
        self.assertIn("contradice", r["motivo"])

    def test_rivales_no_comparables_no_confirman_forma(self):
        r = T.evaluar(ev(), {M.LOCAL: perfil(rank=1000), M.VISITA: perfil(rank=10, gano=False)})
        self.assertEqual(r["tipo"], "CANDIDATO TENIS FEMENINO — BRECHA DE RANKING")

    def test_contexto_comparable_confirma_y_contradice(self):
        r = T.evaluar(ev(), {M.LOCAL: perfil(gano=True), M.VISITA: perfil(gano=False)})
        self.assertEqual(r["tipo"], "ASIMETRÍA TENIS FEMENINO")
        r = T.evaluar(ev(), {M.LOCAL: perfil(gano=False), M.VISITA: perfil(gano=True)})
        self.assertFalse(r["alertar"])

    def test_score_historial_esta_desde_la_ganadora(self):
        raw = {"s_d_flag": "S", "player_1": "1", "reason_code": "W", "winner": 2,
               "scores": "6-1 6-0", "StartDate": "2026-01-01", "Surface": "HARD", "rank_2": 10}
        p = W.normalizar_historial(raw, "1")
        self.assertFalse(p["gano"])
        self.assertEqual((p["juegos_favor"], p["juegos_contra"]), (1, 12))
        raw["winner"] = 1
        p = W.normalizar_historial(raw, "1")
        self.assertEqual((p["juegos_favor"], p["juegos_contra"]), (12, 1))
        raw["reason_code"] = "R"
        self.assertIsNone(W.normalizar_historial(raw, "1"))

    def test_wta_hora_no_definida_y_dobles_rechazados(self):
        raw = {"DrawMatchType": "S", "MatchState": "U", "Unscheduled": True,
               "MatchTimeStamp": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
               "PlayerIDA": "1", "PlayerIDB": "2", "PlayerNameFirstA": "Nombre", "PlayerNameLastA": "Uno",
               "PlayerNameFirstB": "Nombre", "PlayerNameLastB": "Dos"}
        torneo = {"tournamentGroup": {"id": 1, "name": "Test"}, "year": 2026}
        self.assertIsNone(W.normalizar_evento(raw, torneo))
        raw["Unscheduled"] = False
        self.assertIsNotNone(W.normalizar_evento(raw, torneo))
        raw["DrawMatchType"] = "D"
        self.assertIsNone(W.normalizar_evento(raw, torneo))

    def test_cupo_ciclo_wta_impide_requests(self):
        with patch.object(W, "_ciclo", W.MAX_POR_CICLO), patch.object(W._cache, "get", return_value=(False, None)), \
             patch.object(U, "get_json") as red:
            self.assertIsNone(W._get("/players"))
            red.assert_not_called()

    def test_historial_no_filtrado_no_es_completo(self):
        raw = {"matches": [{"tourn_year": "2016"}], "player": {"id": 1}}
        with patch.object(W, "_get", side_effect=lambda ruta, *args, **kwargs:
                          {"summary": {"Singles_Career_Wins": 0, "Singles_Career_Losses": 0}} if ruta.endswith("performance") else raw):
            p = W.perfil({"nombre": "Una Jugadora", "wta_id": "1"})
        self.assertFalse(p["cobertura_completa_2anios"])
        self.assertFalse(p["sin_resultados_registrados"])

    def test_tabla_highlightly_plana(self):
        f = H._fila_tabla({"team": {"id": 1}, "position": 2, "wins": 8, "loses": 2,
                           "scoredPoints": 30, "receivedPoints": 12})
        self.assertEqual((f["victorias"], f["derrotas"], f["dif_neta"]), (8, 2, 18))

    def test_cache_persistente_comprimida_conserva_negativos(self):
        almacen = {}
        with patch.object(U, "cargar_json", side_effect=lambda nombre, default: almacen.get(nombre, default)), \
             patch.object(U, "guardar_json", side_effect=lambda nombre, datos: almacen.update({nombre: datos}) or True):
            cache = U.CachePersistente("test", 100)
            cache.set(("equipo", 1), {"datos": "x" * 2000})
            cache.set("ausente", None)
            cache.guardar()
            nuevo = U.CachePersistente("test", 100)
            self.assertEqual(nuevo.get(("equipo", 1))[1], {"datos": "x" * 2000})
            self.assertEqual(nuevo.get("ausente"), (True, None))
            self.assertIn("z", almacen[cache.nombre])

    def test_pwhl_uid_no_supone_largo_del_prefijo(self):
        txt = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:91196acd5ab978443353@hockeytech.com\nDTSTART:20261123T025000Z\nEND:VEVENT"
        d = P.parsear_ical(txt, ["353"])
        self.assertEqual(set(d), {"353"})
        self.assertEqual(P.parsear_ical(txt, ["3", "353"]), {})

    def test_tsdb_gratis_no_gasta_busqueda_arsenal(self):
        with patch.object(S, "API_KEY", "123"), patch.object(S._cache_busqueda, "get", return_value=(False, None)), \
             patch.object(S, "_get") as red:
            self.assertIsNone(S._buscar_equipo("Un Equipo Femenino", "Soccer"))
            red.assert_not_called()

    def test_oddspapi_ventana_respeta_documentacion(self):
        with patch.object(O, "disponible", return_value=True), patch.object(U, "cargar_json", return_value={}), \
             patch.object(U, "guardar_json"), patch.object(O.presupuesto, "puede_gastar", return_value=True), \
             patch.object(O, "_get", return_value=[]) as red:
            O._terminados_recientes()
            p = red.call_args.args[1]
        inicio, final = U._parsear_iso(p["from"]), U._parsear_iso(p["to"])
        self.assertLess((final - inicio).total_seconds(), 48 * 3600)


class PresentacionTests(unittest.TestCase):
    def test_candidato_no_afirma_ventaja_deportiva(self):
        import mensajes
        texto = mensajes.alerta("Tennis", "Torneo", "A", "B", "13/10 11:30 ARG", ["Falta contexto"],
                                "B", "Magnitud: moderada; calidad: limitada", ["wta", "WTA oficial", "espn"],
                                "CANDIDATO TENIS — BRECHA DE RANKING")
        self.assertIn("Jugadora mejor posicionada", texto)
        self.assertNotIn("Favorito", texto)
        self.assertNotIn("Ventaja observada", texto)
        self.assertIn("Fuentes: WTA · ESPN", texto)

    def test_html_de_fuentes_y_evidencia_se_escapa(self):
        import mensajes
        texto = mensajes.alerta("Soccer", "Copa & Liga", "<A>", "B", "Hoy", ["Marcador <4", "Marcador <4"],
                                "<A>", "Fuerte", ["<fuente>"], "ASIMETRÍA")
        self.assertIn("&lt;A&gt;", texto)
        self.assertIn("&lt;fuente&gt;", texto)
        self.assertEqual(texto.count("Marcador &lt;4"), 1)

    def test_inicio_enumera_alcance_sin_confundir_cobertura(self):
        import mensajes
        texto = mensajes.inicio(["WTA oficial (cuadros, WC e historial)", "PWHL oficial"],
                                list(mensajes.DEPORTES), 900)
        self.assertIn("11 deportes", texto)
        self.assertIn("Hockey sobre hielo", texto)
        self.assertIn("15 min", texto)
        self.assertIn("cobertura varía", texto)


if __name__ == "__main__":
    unittest.main()
