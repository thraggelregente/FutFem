# Contexto deportivo y recomendaciones — 21/10/2026

## Comprobación de producción y fuentes

Northflank confirmó `international-source-depth-v1`, estado ok y primer ciclo completado a las 02:20:33 Argentina. En ese ciclo: vóley 21 análisis, 13 con tabla, 10 con H2H, 3 con cuatro partidos por equipo; el snapshot anterior de la auditoría tenía 5 análisis. No es una comparación controlada: fechas, cuotas y calendario difieren. TAURON cargó 12 equipos y 18 resultados actuales, sin partidos en la ventana de 24 h. La ausencia de alertas de vóley no acredita un fallo: 17 descartes sin señales, 3 sin diferencia de nivel, 1 con puntaje insuficiente.

El contexto consultado provino de FIVB/LVF. Siguen faltando historiales profundos de muchas ligas nacionales; no se atribuye cobertura universal a los agregadores. Highlightly tenía agotados los topes operativos de fútbol/básquet, y LVF/LNV el límite de consulta del día. Este pack no los reinicia ni dispara pedidos adicionales: H2H y rivales comunes de tenis reutilizan perfiles ya descargados.

VBL ofrece una interfaz XML de calendario, resultados y tablas; la documentación indica solicitar clave a vbl-support@volleyball-bundesliga.de (https://www.vbl-wiki.de/wiki/Ergebnisschnittstelle/VBL). La página fue editada en 2020: hay que confirmar vigencia, acceso gratuito, uso permitido y cuota antes de integrar. Sin esa confirmación no se añade un conector vacío como si aportara datos. SportScore sigue documentando fútbol, básquet, cricket y tenis; un MCP sobre el mismo proveedor no sería una fuente independiente (https://sportscore.com/developers/).

## Implementación

- `analisis_deportivo.py`: perfiles de unidades/factores para los 11 deportes. Reutiliza resultados vigentes y documenta elegibilidad/abstención por mercado. Es una primera capa de análisis por deporte, no once modelos predictivos completos.
- `motor_voley.py`: resultados indoor terminados al mejor de cinco; rechaza puntos de rally como sets, partidos incompletos y walkovers. Los umbrales generales del detector se conservan para resultados válidos.
- Tenis: H2H y rivales comunes en 120 días con identidad completa, sin contar dos perspectivas como dos partidos. Fecha semanal solo utilizable una vez terminada la semana. Forma/superficie comparten información y no se tratan como respaldo independiente. Las comparaciones nuevas aportan contexto y restricciones de recomendación, no puntos extra.
- Dobles y simulados explícitos se filtran antes de gastar el cupo de análisis de individuales.
- La auditoría usa `sport-context-v1`; `motor_tenis_legacy.py` conserva el algoritmo anterior exclusivamente para reproducir decisiones archivadas sin reescribirlas.
- Telegram: lectura rápida, datos encontrados, faltantes concretos, recomendaciones y cobertura. Se conserva toda la evidencia; se unifican nombres de fuentes. Las alertas extensas mantienen división HTML sin pérdida de contenido.

## Recomendaciones: reglas explícitas, sin cuotas

No hay porcentajes inventados ni modelo calibrado. Una frecuencia histórica no es la probabilidad del próximo partido. Los picks son orientación deportiva que exige datos concretos; nunca rentabilidad demostrada.

| Deporte | Mercado elegible | Condiciones / límites |
|---|---|---|
| Tenis | Ganadora del partido | Asimetría con forma/superficie comparable favorable y H2H o rivales comunes concordantes. Un candidato de ranking queda sin recomendación. Sin 2–0 ni hándicap de juegos inferido del ranking |
| Vóley | Ganador; eventualmente −1,5 sets | Detector positivo, dos familias y muestras recientes suficientes. Para ganador: ≥75 % de victorias/derrotas en la dirección esperada por separado. Para −1,5: ≥8 partidos por equipo y límite inferior Wilson 95 % de cada frecuencia de margen ≥2 sets por encima del 50 %. Es un filtro descriptivo, no calibración de acierto |
| Básquet / handball | Ganador del partido | Detector positivo, historial reciente, dos familias, calidad suficiente y resultados concordantes. No inventa línea de puntos/goles |
| Fútbol / hielo / rugby / softball / lacrosse / hockey césped | Abstención de mercado automática | Explica orientación deportiva y formato/reglas por verificar: tiempo reglamentario, prórroga, penales, modalidades o personal faltante. Su perfil ya existe; el modelo especializado completo sigue pendiente de datos |
| Cricket | Sin apuesta automática; candidato experimental | Se conserva motor T20/ODI separado, sin mezclar carreras y wickets. La capa de mensajes ya informa la abstención, no promete un mercado validado |

Los factores de plantel, ritmo, lanzadoras, formatos y lesiones no se fabrican cuando las fuentes no los aportan. Queda pendiente el desarrollo predictivo completo de esos deportes y la evaluación prospectiva de cada mercado; no se afirma haberlo terminado con estas reglas.

## Validación y operación

Pruebas offline de insuficiencia, contradicción, duplicación, orientación, tiempos, replay anterior, selección de mercados y HTML; suite completa y compilación antes de publicar. No se envían mensajes reales de prueba ni se consultan proveedores con claves. Revisión de salud prevista: `sport-context-recommendations-v1`. No requiere nuevas variables ni claves. Rollback: commit anterior f192e80396805114dc47915627fb63fc64484522.
