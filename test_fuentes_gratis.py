"""Fuentes públicas, vigencia y ausencia de llamadas a planes medidos; offline."""
import test_radar  # fija DATA_DIR y deshabilita Telegram/Redis reales
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as ET

import fuente_cev as C
import fuente_fivb as F
import fuente_espn as E
import fuente_bbs as BB
import ranking_wta as R
import main as B
import utilidades as U
from fuentes_publicas import xml_seguro


def cev_fila():
    now = datetime.now(timezone.utc)
    return {"CompetitionID": 1, "SeasonID": now.year + 1, "CompetitionName": "Cup Women",
            "MaleNotFemale": False, "IsBeach": False, "IsSnow": False,
            "HomeTeamID": 2, "GuestTeamID": 3, "HomeTeamName": "Equipo A", "GuestTeamName": "Equipo B",
            "MatchID": 4, "MatchDateTime_UTC": U.ts_a_iso_utc(time.time() - 86400),
            "WonSetHome": 3, "WonSetGuest": 1, "Finalized": True, "MatchStatusDescription": "Complete"}


def competiciones():
    year = datetime.now(timezone.utc).year
    return {"1": {"Gender": 0, "SeasonID": year + 1, "CompetitionName": "Cup Women",
                  "DateFrom": f"{year}-01-01", "DateTo": f"{year + 1}-12-31"}}


class FuentesGratisTests(unittest.TestCase):
    def test_bbs_sin_clave_no_hace_requests(self):
        with patch.object(BB, "API_KEY", ""), patch.object(U, "get_json") as red:
            self.assertEqual(BB.obtener_eventos("Basketball"), [])
            red.assert_not_called()

    def test_bbs_solo_wnba_y_anio_del_evento(self):
        year = datetime.now(timezone.utc).year
        raw = {"id": "match", "sport": "basketball", "league": "WNBA", "kickoff_utc": U.ts_a_iso_utc(time.time()-3600),
               "status": "finished", "home": {"id": "a", "name": "Equipo A"},
               "away": {"id": "b", "name": "Equipo B"}, "score": {"home": 77, "away": 87}}
        self.assertIsNotNone(BB.normalizar(raw, year))
        self.assertIsNone(BB.normalizar(dict(raw, league="NBA"), year))
        self.assertIsNone(BB.normalizar(raw, year + 1))
        self.assertIsNone(BB.normalizar(dict(raw, time_precision="date"), year))
        self.assertIsNone(BB.normalizar(dict(raw, score={"home": 0, "away": 0}), year))

    def test_historial_espn_fuera_de_temporada_no_dispara_45_dias(self):
        with patch.object(E, "_scoreboard", return_value={"leagues": [{"calendar": []}], "events": []}) as red:
            self.assertEqual(E._eventos_pasados("field-hockey", "womens-college-field-hockey"), [])
            self.assertEqual(red.call_count, 1)

    def test_coleccion_nuevos_deportes_no_pide_proveedores_medidos(self):
        comercial = SimpleNamespace(disponible=lambda: True, obtener_eventos=lambda d: [])
        with patch.object(comercial, "obtener_eventos", return_value=[]) as pedidos, \
             patch.object(B, "fuente_api_football", comercial), patch.object(B, "fuente_highlightly", comercial), \
             patch.object(B, "fuente_oddspapi", comercial), patch.object(B, "fuente_theoddsapi", comercial), \
             patch.object(B, "fuente_thesportsdb", None), patch.object(B, "fuente_openligadb", None), \
             patch.object(B, "fuente_espn", None), patch.object(B, "fuente_wta", None), \
             patch.object(B, "fuente_pwhl", None), patch.object(B, "fuente_bbs", None), \
             patch.object(B, "fuente_cev", None), patch.object(B, "fuente_fivb", None):
            B._recolectar_eventos({})
            self.assertFalse({c.args[0] for c in pedidos.call_args_list} & B.DEPORTES_SIN_CUPO_COMERCIAL)

    def test_cev_temporada_nominal_siguiente_es_valida(self):
        self.assertIsNotNone(C.normalizar(cev_fila(), competiciones()))

    def test_cev_descarta_genero_modalidad_y_temporada_contradictorios(self):
        for cambio in ({"MaleNotFemale": True}, {"IsBeach": True}, {"IsSnow": True},
                       {"SeasonID": 1900}, {"CompetitionName": "Beach Women"}):
            self.assertIsNone(C.normalizar(dict(cev_fila(), **cambio), competiciones()))
        self.assertIsNone(C.normalizar(cev_fila(), {"1": dict(competiciones()["1"], Gender=1)}))

    def test_cev_no_inventa_utc_desde_hora_local(self):
        raw = cev_fila()
        raw.pop("MatchDateTime_UTC")
        raw["MatchDateTime"] = U.ts_a_iso_utc(time.time())
        self.assertIsNone(C.normalizar(raw, competiciones()))

    def test_cev_fuente_recien_descargada_pero_cache_remota_vieja(self):
        self.assertFalse(C.respuesta_vigente({"data": [], "meta": {"CacheTime": "2025-01-01T00:00Z"}}))
        self.assertTrue(C.respuesta_vigente({"data": [], "meta": {"CacheTime": U.ts_a_iso_utc(time.time())}}))

    def test_cev_historial_aisla_temporada_y_competicion(self):
        p = C.normalizar(cev_fila(), competiciones())
        otro = dict(p, contexto_competicion="otra temporada")
        ev = dict(p, local=p["local"])
        with patch.object(C, "_historial", [p, otro]):
            self.assertEqual(len(C.historial_equipo(ev, "local")), 1)

    def test_vis_verifica_genero_real_aunque_filtro_fuera_ignorado(self):
        n = ET.Element("VolleyballMatch", No="1", NoTournament="2", DateTimeUtc=U.ts_a_iso_utc(time.time()-3600),
                       Status="25", NoTeamA="3", NoTeamB="4", TeamAName="País A", TeamBName="País B",
                       MatchPointsA="3", MatchPointsB="0", ResultType="0")
        torneo = ET.SubElement(n, "Tournament", No="2", Gender="0", Name="Women U19")
        self.assertIsNone(F.normalizar(n))
        torneo.set("Gender", "1")
        self.assertIn("U19", F.normalizar(n)["nom_local"])
        n.set("ResultType", "2")
        self.assertIsNone(F.normalizar(n))

    def test_vis_rechaza_xml_con_entidades(self):
        self.assertIsNone(xml_seguro('<!DOCTYPE x [<!ENTITY e "hola">]><x>&e;</x>'))

    def test_pdf_de_2025_no_es_vigente_en_2027(self):
        snapshot = {"fecha": "2025-12-29", "jugadoras": {str(n): {} for n in range(1100)}}
        with patch.object(R, "datetime", wraps=datetime) as reloj:
            reloj.now.return_value = datetime(2027, 1, 2, tzinfo=timezone.utc)
            self.assertFalse(R.vigente(snapshot))

    def test_espn_tabla_de_otra_temporada_no_se_usa(self):
        ev = test_radar.evento("A")
        ev.update(liga_ref=("soccer", "usa.nwsl"), season_ref=2027)
        with patch.object(E._cache_tablas, "get", return_value=(True, {"season": {"year": 2025}})):
            self.assertEqual(E.tabla_partido(ev), (None, 0))

    def test_espn_historial_rechaza_temporada_distinta(self):
        with patch.object(E._cache_historial, "get", return_value=(False, None)), \
             patch.object(E, "_eventos_pasados", return_value=[{"season": {"year": 2025}}]), \
             patch.object(E, "_partido_terminado") as parsear:
            self.assertEqual(E._historial_liga("field-hockey", "womens-college-field-hockey", 2027), {})
            parsear.assert_not_called()

    def test_nuevo_deporte_sin_historial_no_busca_por_nombre_medido(self):
        ev = test_radar.evento("A", deporte="Softball")
        with patch.object(U, "historial_desde_fuentes", return_value=[]) as resolver, \
             patch.object(B.libro_resultados, "historial_equipo") as libro:
            self.assertEqual(B._historial_equipo(ev, "local"), [])
            self.assertEqual(resolver.call_count, 1)
            self.assertIsNone(resolver.call_args.args[3])
            self.assertIsNone(resolver.call_args.args[4])
            self.assertIsNone(resolver.call_args.args[5])
            libro.assert_not_called()

    def test_doble_jornada_softball_no_colapsa_ni_comparte_alerta(self):
        a = test_radar.evento("A", deporte="Softball")
        b = dict(a, id="otro partido", startTimestamp=a["startTimestamp"]+7200)
        self.assertNotEqual(B._clave_canonica_evento(a), B._clave_canonica_evento(b))
        self.assertFalse(B._claves_equivalentes(a) & B._claves_equivalentes(b))
        self.assertFalse(B._coincide_con_candidato(a, B._firma_evento(b), b["startTimestamp"], b))


if __name__ == "__main__":
    unittest.main()
