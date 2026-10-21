"""Regresiones de datos, presupuestos y decisiones; sin claves ni servicios externos."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = _tmp.name
for _key in ("TELEGRAM_TOKEN", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
    os.environ.pop(_key, None)

os.environ["LVF_ACTIVO"] = "0"
os.environ["LNV_ACTIVO"] = "0"
os.environ["TAURON_ACTIVO"] = "0"

import utilidades as U
import motor_mismatches as M
import ranking_wta as R
import fuente_api_football as A
import fuente_highlightly as H
with patch("threading.Thread.start"):
    import main as B


def partido(local="a", visita="b", dias=1, pl=4, pv=1):
    return {"fecha": (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat(),
            "id_local": local, "id_visita": visita, "puntos_local": pl, "puntos_visita": pv}


def evento(nombre="A", deporte="Soccer", rank=10):
    return {"id": nombre, "fuente": "espn", "deporte": deporte, "femenino_seguro": True,
            "tipo_estado": "pre", "startTimestamp": int(__import__("time").time()) + 3600,
            "local": {"nombre": nombre, "id": nombre, "ranking": rank},
            "visita": {"nombre": "Rival " + nombre, "id": "r" + nombre, "ranking": rank}}


class RadarTests(unittest.TestCase):
    def test_identidad_categorias_y_deportes(self):
        self.assertNotEqual(U.firma_equipo("Barcelona Women"), U.firma_equipo("Barcelona Women U19"))
        self.assertNotEqual(U.firma_equipo("Barcelona Women"), U.firma_equipo("Barcelona Women B"))
        self.assertFalse(U.nombres_coinciden("Barcelona Women", "Barcelona Women U19"))
        self.assertEqual(U.categoria_equipo("Barcelona Under 19"), U.categoria_equipo("Barcelona U19"))
        self.assertNotEqual(B._clave_canonica_evento(evento()), B._clave_canonica_evento(evento(deporte="Basketball")))

    def test_historial_ajeno_futuro_y_duplicado(self):
        p = partido()
        forma = M.evaluar_rendimiento_reciente([partido("x", "y"), partido(dias=-1), p, p], "a", "Soccer")
        self.assertEqual(forma["muestras"], 1)
        self.assertEqual(forma["victorias"], 1)
        self.assertEqual(M.evaluar_rendimiento_reciente([partido("x", "y")], "a", "Soccer")["muestras"], 0)

    def test_presupuestos_individuales_y_all_sports(self):
        self.assertIsNot(A._presupuesto("Soccer"), A._presupuesto("Basketball"))
        self.assertIsNot(H._presupuesto("Soccer"), H._presupuesto("Basketball"))
        self.assertIs(H._presupuesto("Soccer", H.BASE_TODOS), H._presupuesto("Basketball", H.BASE_TODOS))

    def test_brynas_conserva_asimetria(self):
        # Solo señales previas de la captura; el 4-1 final nunca se usa.
        local = {"dif_prom": -0.33, "victorias": 2, "derrotas": 3, "muestras": 5}
        visita = {"dif_prom": 3.07, "victorias": 5, "derrotas": 0, "muestras": 5}
        tri = {"visita": [{"rival": "Skelleftea", "dif_a": 4, "dif_b": -2, "brecha": 6},
                           {"rival": "Otro", "dif_a": 3, "dif_b": -1, "brecha": 4}]}
        r = M.evaluar_mismatch("Ice Hockey", local, visita, tri, None)
        self.assertTrue(r["hay_mismatch"])
        self.assertEqual(r["favorito"], M.VISITA)
        self.assertEqual(r["puntaje"], 4)
        self.assertEqual(r["grupos_independientes"], 1)

    def test_calendario_y_bajas_no_crean_superioridad(self):
        vacio = {"dif_prom": 0, "victorias": 0, "derrotas": 0, "muestras": 0}
        r = M.evaluar_mismatch("Soccer", vacio, vacio, {}, None, datos_extra={
            "descanso": {"favorito": M.LOCAL, "detalle": "descanso"},
            "plantel": {"favorito": M.LOCAL, "puntos": 2, "detalle": "bajas"}, "racha_local": 6})
        self.assertFalse(r["hay_mismatch"])
        self.assertIsNone(M.evaluar_plantel({"fuera": 0, "inferido": True}, {"fuera": 5}, "Soccer"))

    def test_senales_relacionadas_tienen_tope(self):
        local = {"dif_prom": 4, "victorias": 6, "derrotas": 0, "muestras": 6}
        visita = {"dif_prom": -4, "victorias": 0, "derrotas": 6, "muestras": 6}
        tri = {"local": [{"rival": str(i), "dif_a": 4, "dif_b": -4, "brecha": 8} for i in range(3)]}
        r = M.evaluar_mismatch("Soccer", local, visita, tri,
            {"reciente": [{"ganador": M.LOCAL, "dif": 3}] * 3},
            datos_extra={"elo": {"favorito": M.LOCAL, "puntos": 3, "detalle": "Elo"}})
        self.assertEqual(r["puntaje"], 4)

    def test_tenis_ranking_desconocido_no_es_fuera(self):
        self.assertFalse(M.evaluar_mismatch_tenis("A", "B", 5, None, fuera_visita=True, corte_ranking=150)[0])
        self.assertTrue(M.evaluar_mismatch_tenis("A", "B", 20, 85)[0])
        self.assertTrue(M.evaluar_mismatch_tenis("A", "B", 250, 900)[0])
        self.assertFalse(M.evaluar_mismatch_tenis("A", "B", 40, 80)[0])

    def test_alias_y_vigencia(self):
        self.assertEqual(R.clave_nombre("Catherine McNally"), R.clave_nombre("MCNALLY, CATY"))
        s = {"fecha": (datetime.now(timezone.utc) - timedelta(days=20)).date().isoformat(),
             "jugadoras": {str(i): {} for i in range(1000)}}
        self.assertFalse(R.vigente(s))

    def test_pdf_incompleto_rechazado(self):
        with self.assertRaises(Exception):
            R.parsear_pdf(b"no es PDF")

    def test_salud_no_oculta_barrido_detenido(self):
        antiguo = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with patch.dict(B.ESTADO, {"ultimo_barrido_utc": antiguo}):
            self.assertEqual(B.estado_salud(), "degraded")
        with patch.dict(B.ESTADO, {"ultimo_barrido_utc": datetime.now(timezone.utc).isoformat()}):
            self.assertEqual(B.estado_salud(), "ok")

    def test_h2h_ajeno_no_suma(self):
        r = M.analizar_h2h_extendido([partido("a", "c"), partido("b", "c")], "a", "b")
        self.assertEqual(r["reciente"], [])

    def test_historial_fuentes_localia_invertida_e_ids_solapados(self):
        ev = evento("Equipo A")
        ev["local"]["id"], ev["visita"]["id"] = "2", "1"
        obs = evento("Rival Equipo A")
        obs["local"] = {"nombre": "Rival Equipo A", "id": "2"}
        obs["visita"] = {"nombre": "Equipo A", "id": "1"}
        ev["_observaciones"] = [obs]
        hist = [partido("2", "1", dias=i + 1) for i in range(4)]
        with patch.object(U, "historial_desde_fuentes", return_value=hist) as llamada:
            salida = B._historial_equipo(ev, "local")
        self.assertEqual(llamada.call_args.args[1], "visita")
        self.assertEqual(salida[0]["id_local"], "1")
        self.assertEqual(salida[0]["id_visita"], "2")

    def test_descarga_fallida_conserva_snapshot_vigente(self):
        fecha = datetime.now(timezone.utc).date().isoformat()
        s = {"fecha": fecha, "jugadoras": {str(i): {} for i in range(1000)}}
        with patch.object(R, "_cache", U.CacheTTL(1)), patch.object(U, "cargar_json", return_value=s), \
             patch.object(R.requests, "get", side_effect=RuntimeError("red")):
            self.assertEqual(R.obtener(), s)

    def test_tenis_sin_rank_no_ocupa_limite_y_cola_rota(self):
        sin_rank = [evento("Sin" + str(i), "Tennis", None) for i in range(60)]
        utiles = [evento("Util" + str(i), "Tennis", 20) for i in range(4)]
        procesados = []
        def procesar(ev, st, ahora):
            procesados.append(ev["id"])
            st["analizados"] += 1
            return True
        with patch.object(B, "_recolectar_eventos", return_value=sin_rank + utiles), \
             patch.object(B, "_procesar_evento", side_effect=procesar), \
             patch.object(B, "_ya_alertado", return_value=False), patch.object(B, "_enfriamiento", {}), \
             patch.object(B, "_ultimo_intento", {}), patch.object(B, "MAX_ANALISIS_POR_CICLO", 2), \
             patch.object(B, "_imprimir_resumen"), patch.object(B, "_avisar_si_esta_ciego"), \
             patch.object(B, "_resumen_presupuestos", return_value={"wta": "hoy 51/100, semana 195/650, mes 195/2900"}):
            B.ejecutar_barrido_radar()
            B.ejecutar_barrido_radar()
        self.assertEqual(set(procesados), {"Util" + str(i) for i in range(4)})

    def test_presupuesto_multiple_contrato_numerico_y_texto_legacy(self):
        with patch.object(U, "cargar_json", return_value={}):
            p = U.PresupuestoMultiple("test_contrato", mensual=150, semanal=34, diario=6)
        p.d, p.s, p.m = 1, 3, 5
        row = p.resumen_datos()
        self.assertEqual(row["disponibles_bot"], p.permitido_ahora())
        self.assertEqual(row["dia"]["usadas"], 1)
        self.assertEqual(row["semana"]["usadas"], 3)
        self.assertEqual(row["mes"]["usadas"], 5)
        self.assertEqual(row["resumen"], p.resumen())
        saldos = B.planificador.saldos_disponibles({"wta": row, "legacy": p.resumen(),
                                                   "invalid": {"disponibles_bot": None}})
        self.assertEqual(saldos, {"wta": p.permitido_ahora(), "invalid": 0})


if __name__ == "__main__":
    unittest.main()
