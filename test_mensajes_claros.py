"""Claridad, nombres, conservación de evidencia y entrega de alertas largas."""
import test_radar
import html
import re
import unittest
from html.parser import HTMLParser
from unittest.mock import patch

import main as B
import mensajes as S
import motor_tenis as T
import motor_mismatches as M


class TextoHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pila, self.textos = [], []

    def handle_starttag(self, tag, attrs):
        self.pila.append(tag)

    def handle_endtag(self, tag):
        assert self.pila.pop() == tag

    def handle_data(self, data):
        self.textos.append(data)


class MensajesClarosTests(unittest.TestCase):
    def test_historial_tenis_identifica_favorita_y_rival(self):
        ev = {"local": {"nombre": "Guo Hanyu", "ranking": 240}, "visita": {"nombre": "Elina Svitolina", "ranking": 6}}
        perfiles = {M.LOCAL: {"muestras_2anios": 94, "partidos": [], "recientes": []},
                    M.VISITA: {"muestras_2anios": 106, "partidos": [], "recientes": []}}
        res = T.evaluar(ev, perfiles)
        hist = next(e for e in res["evidencia"] if e.startswith("Historial oficial"))
        self.assertIn("Elina Svitolina 106 partidos", hist)
        self.assertIn("Guo Hanyu 94 partidos", hist)
        self.assertIn("semana del torneo", hist)
        self.assertEqual(res["favorito"], M.VISITA)
        self.assertEqual(res["puntaje"], M.evaluar_mismatch_tenis("Guo Hanyu", "Elina Svitolina", 240, 6)[3])

    def test_handball_conserva_margenes_y_muestras_con_nombres(self):
        texto = S.alerta("Handball", "Liga", "Elda", "Gran Canaria", "15:00", [
            "Triangulación vs Málaga: ganó por +3 y el rival cayó por -3 (2 rival/es en común)",
            "Calendario: visita jugó 3 partidos en 7 días vs 1 del local",
            "Elo: Local 1551 vs 1442 (ajuste de localía; 5/6 partidos en el libro)"],
            "Elda", "Magnitud: Moderada; calidad: Suficiente; 2 familia(s) de señales, sin independencia garantizada",
            ["highlightly"], "ASIMETRÍA")
        for palabra in ["Elda ganó por 3 (margen +3)", "Gran Canaria perdió por 3 (margen -3)", "2 rivales compartidas", "Gran Canaria jugó 3 encuentros en 7 días",
                        "5 partidos de Elda", "6 de Gran Canaria", "1551", "1442", "ajuste de localía", "Pueden compartir información"]:
            self.assertIn(palabra, texto)
        self.assertIn("Magnitud del desnivel", texto)
        self.assertIn("Respaldo de los datos", texto)
        self.assertIn("Pendientes de evaluación", texto)

    def test_elo_visitante_no_invierte_muestras_de_local_y_visita(self):
        texto = S.evidencia_clara("Elo: Visitante 1600 vs 1500 (ajuste de localía; 5/9 partidos en el libro)", "Local A", "Visita B", "Visita B")
        self.assertIn("Visita B 1600", texto)
        self.assertIn("Local A 1500", texto)
        self.assertIn("5 partidos de Local A y 9 de Visita B", texto)

    def test_forma_racha_h2h_y_bajas_identifican_lados(self):
        casos = [
            ("Forma: Visitante +3.07 por partido (5V en 5) vs rival -0.33 (3D en 5)", ["B, diferencia media ajustada +3.07", "5 victorias", "A, -0.33", "3 derrotas"]),
            ("H2H: Visitante ganó 4 cruces (2 recientes, 1 6-18m, 1 +18m) vs 1 del rival", ["B ganó 4", "6 a 18 meses", "más de 18 meses", "A ganó 1"]),
            ("Momentum: Visitante 5 victorias seguidas", ["B acumula 5"]),
            ("Plantel: Local con 4 bajas confirmadas vs 1 de Visitante", ["A tiene 4", "B, 1"]),
        ]
        for original, esperados in casos:
            texto = S.evidencia_clara(original, "A", "B", "B")
            for esperado in esperados:
                self.assertIn(esperado, texto)

    def test_evidencia_desconocida_y_mas_de_diez_items_se_conservan(self):
        evidencias = [f"Dato nuevo {i} <{i}> & {i}" for i in range(15)]
        texto = S.alerta("Soccer", "Liga", "A", "B", "Hoy", evidencias, "A", "Texto de evaluación propio", ["sportscore"], "ASIMETRÍA")
        for e in evidencias:
            self.assertIn(html.escape(e), texto)
        self.assertIn("Texto de evaluación propio", texto)
        self.assertIn("Powered by SportScore", texto)

    def test_partes_html_preservan_texto_entidades_y_emojis(self):
        original = "<b>🎾 " + html.escape("<&>🟢"*2000) + "</b>\n<i>Fuente</i>\n<a href=\"https://sportscore.com/\">SportScore</a>"
        partes = S.dividir_html(original)
        self.assertGreater(len(partes), 1)
        reconstruido = []
        for parte in partes:
            self.assertLessEqual(len(parte.encode("utf-16-le"))//2, 4000)
            limpia = re.sub(r"^<i>Alerta · parte \d+/\d+</i>\n", "", parte)
            parser = TextoHTML()
            parser.feed(limpia)
            self.assertEqual(parser.pila, [])
            reconstruido.extend(parser.textos)
        parser = TextoHTML()
        parser.feed(original)
        self.assertEqual("".join(reconstruido), "".join(parser.textos))

    def test_entrega_parcial_no_se_declara_completa(self):
        with patch.object(B, "TELEGRAM_TOKEN", "test"), patch.object(B, "CHAT_ID", "chat"), patch.object(B, "CHAT_ID_GRUPO", ""), \
             patch.object(B, "_post_telegram", side_effect=[(200, 0), (500, 0)]) as post:
            self.assertFalse(B.enviar_telegram("<b>"+"texto "*1500+"</b>"))
            self.assertEqual(post.call_count, 2)
        with patch.object(B, "TELEGRAM_TOKEN", "test"), patch.object(B, "CHAT_ID", "chat"), patch.object(B, "CHAT_ID_GRUPO", "grupo"), \
             patch.object(B, "_post_telegram", side_effect=[(200, 0), (500, 0), (500, 0)]):
            self.assertFalse(B.enviar_telegram("<b>"+"texto "*1500+"</b>"))

    def test_entrega_completa_usa_partes_sin_perder_final(self):
        with patch.object(B, "TELEGRAM_TOKEN", "test"), patch.object(B, "CHAT_ID", "chat"), patch.object(B, "CHAT_ID_GRUPO", ""), \
             patch.object(B, "_post_telegram", return_value=(200, 0)) as post:
            self.assertTrue(B.enviar_telegram("<b>"+"texto "*1500+"FINAL</b>"))
            self.assertIn("FINAL", post.call_args.args[1]["text"])
            self.assertGreater(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
