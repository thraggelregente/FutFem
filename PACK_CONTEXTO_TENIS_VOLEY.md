# Pack de contexto de tenis y vóley

Revisión `tennis-volley-context-v1`, 14/10/2026. Extiende las rutas existentes; mantiene los umbrales deportivos de emisión.

## Tenis

- Tennis API sigue compartiendo 50 solicitudes en ventana móvil de 24 horas. Contexto: máximo 28/24h, seis solicitudes nuevas por barrido, con ocho solicitudes disponibles reservadas para calendario/resultados. El calendario y el recolector siguen dentro de la misma bolsa; no se crean cuotas independientes que permitan sobrepasar 50.
- Copia el ID Tennis API únicamente desde una observación con nombre exacto y único. Perfiles: ID y nombre deben coincidir. Prioriza hasta dos consultas nuevas de ranking faltante por barrido; los demás huecos se recorren en barridos siguientes. Caché 24h; negativos 1h.
- WTA conserva prioridad. El ranking auxiliar debe tener fecha con antigüedad máxima de 14 días; no se inventa ranking cuando es null. Una discrepancia numérica para la misma fecha deja el encuentro sin evaluación hasta resolverla. Fechas distintas se conservan como observaciones distintas.
- Perfil e historial factual WTA/ITF; individuales, dos años de calendario consultados y hasta dos páginas de 500 resultados. Descarta datos futuros, identidad ajena, años no solicitados, retiros, walkovers y marcadores incompletos. Player1 en resultados es la ganadora; los juegos se orientan al ID consultado.
- El historial alternativo se incorpora al snapshot y al texto. Si hay perfil WTA, no se suman dos muestras posiblemente duplicadas. Si no lo hay, el historial alternativo proporciona actividad/contexto, pero no certifica carrera completa ni poca experiencia WTA. No usa el ranking actual de una rival como ranking histórico; por tanto no suma apoyo por bandas comparables cuando ese campo falta.
- Una cantidad observada de resultados ITF por encima del límite de poca experiencia ya existente impide etiquetar una WC como debutante documentada por ausencia de historial WTA. No cambia los umbrales de puntaje.
- Los campos de cuotas/predicciones se eliminan antes de cachear tanto perfiles como resultados. Métricas de contexto en `/health.budgets.tennis_api`.

## FIVB/VIS

- Calendario solicita NoPool y puntos por set además de los campos existentes. Los parciales se conservan sólo cuando cantidad, ganador y reglas de puntuación son compatibles con el marcador final.
- Tabla oficial por grupo: valida el vínculo grupo → torneo, participantes, posición y edición. Reutiliza cachés; hasta dos grupos por barrido, no dos eventos del mismo grupo.
- Vigencia conservadora: el inicio del torneo debe estar dentro de la ventana de 90 días que cubre nuestro historial. Los contadores de victorias, derrotas y diferencia de sets de cada equipo deben reconciliarse exactamente con los resultados normalizados del grupo. Una tabla pública que no permite esa comprobación se rechaza, aunque responda HTTP 200.
- Conserva el presupuesto operativo público existente de 30 solicitudes/día con reserva; no consume Highlightly/OddsPapi. Estado de tablas en `/health.budgets.fivb`.

## Fuentes oficiales nacionales nuevas

### LVF: Serie A1 femenina italiana

Descubre la edición seleccionada del sitio oficial, exige temporada actual 2026/27 según calendario deportivo y tabla A1. Lee posiciones, victorias, derrotas, sets y puntos; comprueba coherencia de partidos jugados. La matriz de resultados identifica la pareja y el ID de match-center. El detalle debe coincidir en ambos nombres, marcador, fecha de la edición y parciales completos. Horas publicadas en Italia se convierten con Europe/Rome; no se infieren fixtures desde una fecha sola.

### LNV: D1F francesa

Descubre el ID vigente desde el widget de la sección femenina oficial y la fase desde los enlaces de esa edición. No fija el ID de una temporada antigua. Tabla y matriz deben tener resultados recientes. Descubre IDs de partidos en el calendario público y verifica nombres/alias del mismo catálogo, timestamp, marcador y puntos por set con el detalle. Horas publicadas en Francia se convierten con Europe/Paris. La edición es el ID oficial descubierto; no se inventa una temporada numérica que el HTML no declare.

### Integración

- Dos fuentes de **contexto**, no calendarios nuevos. Cada una usa límite operativo propio de 24 solicitudes/día con reserva y caché 6h para listados/24h para detalles. Descarga hasta cuatro detalles nuevos por barrido y reutiliza los anteriores.
- Sólo respaldan eventos con competición nacional explícita y ambos equipos resueltos por nombre exacto o alias explícito y único del catálogo. Rechazan copa, competición internacional, juvenil y reserva; no mezclan IDs de proveedores por parecido.
- Añaden tabla a la ruta actual y, si falta historial suficiente en la ruta general, ofrecen resultados nacionales remapeando los dos participantes. Mantienen la protección de historiales aislados de FIVB/CEV.
- Para resultados posteriores, la vinculación alternativa exige la competición compatible, los dos equipos verificados y timestamp UTC idéntico. Localía invertida se conserva en orientación original y se normaliza para evaluar. Ambigüedades quedan pendientes.
- Puntos por set se registran y permiten informar margen descriptivo, pero no introducen un nuevo umbral de dominio ni alteran la puntuación de alertas. Sin parciales completos no se inventa margen de puntos.
- Se atribuye LVF/LNV en alertas cuando su tabla o historial realmente intervienen. La capacidad aparece como contexto, no calendario. Vóley pasa de seis a ocho fuentes habilitadas, con cobertura nacional específica; no son ocho respaldos para cada liga.

## Operación y límites

No se requieren claves nuevas. `LVF_ACTIVO=0` y `LNV_ACTIVO=0` deshabilitan cada fuente al reiniciar. Tennis API requiere la key que ya está configurada. No se incorpora esports en este pack. No se cambian mercados ni recomendaciones de apuestas.

Italia y Francia están comenzando temporada: dos o tres partidos no alcanzan los mínimos existentes de cuatro para forma y cinco para tabla. Las fuentes pueden aportar contexto sin generar nuevas alertas todavía. No se importan silenciosamente resultados de otra temporada para superar esos mínimos.

Estado de fuentes, tablas, resultados y requests en `/health`. Ante layout desconocido, datos ausentes, incoherencia o pausa, se conserva el radar y queda visible que falta contexto.

## Referencias

- https://docs.tennis-api.com/players
- https://www.fivb.org/VisSDK/VisWebService/GetVolleyPool.html
- https://www.fivb.org/VisSDK/VisWebService/GetVolleyPoolRanking.html
- https://www.fivb.org/VisSDK/VisWebService/VolleyPoolRankingEntry.html
- https://www.fivb.org/VisSDK/VisWebService/VolleyMatch.html
- https://www.legavolleyfemminile.it/classifica/
- https://www.lnv.fr/d1f/statistiques

Rollback: volver al commit anterior `1db2d6f33f512d357033089a99634e82057f4629`. Los caches/presupuestos nuevos están en namespaces separados; no borrar Redis ni reiniciar contadores.
