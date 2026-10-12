# Fuentes, cobertura y consumo

Revisión del 12/10/2026. Los límites del bot son defensivos; no equivalen al plan contratado ni a requests realmente consumidos. Las cabeceras y paneles de cada cuenta son la referencia del saldo real. No se consultan cuotas deportivas.

| Fuente | Uso y mejora | Tope propio predeterminado | Cuota del proveedor / precaución |
|---|---|---|---|
| API-Sports | Calendarios e históricos por deporte; fútbol añade tablas si la cobertura de la temporada las habilita. Caché persistente de temporada, cobertura y tablas. | 100/día por API deportiva, reserva 12; ritmo máximo 8/min por API. | Cada API deportiva tiene suscripción independiente. El reinicio diario está asociado a la suscripción, no necesariamente a medianoche UTC. |
| Highlightly | Calendario, últimos cinco, H2H y tablas; corregido el formato plano de básquet/vóley. Historial, IDs, tablas y búsquedas negativas persisten. | 100/día por host, reserva 5; el calendario deja 25 para análisis. All Sports comparte contador. | Confirmar cada suscripción y su ventana en RapidAPI. No se inventa una hora de reinicio. Una página global puede truncar ligas femeninas: configurar IDs verificados en `HIGHLIGHTLY_WOMENS_LEAGUES`. |
| OddsPapi | Fixtures agrupados; ventana de terminados corregida a menos de 48 h. Si no entrega marcadores se pausa ese intento siete días. | 6/día, 35/semana, 180/mes, reserva mensual 20 y saldo real mínimo 25. | La cuenta mostraba plan 250. No se añaden pedidos de scores por partido: consumirían demasiado. La cuenta manda sobre el contador local. |
| The Odds API | Catálogo y eventos; resultados solo dentro del presupuesto. Eventos de coste cero ya no se descuentan como un crédito. | Scores: 6 créditos/día y 150/mes; tope semanal configurable; reserva real 250. | Plan observado 500/mes. `/scores` con `daysFrom` cuesta 2 créditos; `/sports` y `/events` no consumen créditos. Requests y créditos son unidades distintas. |
| TheSportsDB | Calendarios por liga femenina verificada; resultados del día previo alimentan el libro. IDs se reutilizan del calendario. | Cachés y ritmo existente; sin cuota mensual propia. | V1 documenta 30/min y restricciones importantes: `searchteams` gratis no es buscador general; últimos partidos y temporadas pueden estar truncados. Un 200 no demuestra historial completo. |
| ESPN | Respaldo de calendarios y nuevas tablas gratuitas cacheadas por competición; ranking top 150 solo como respaldo fechado. | Cachés; sin cuota mensual publicada verificada. | Cobertura limitada; ausencia del ranking significa desconocido. Tablas deben incluir ambos equipos en el mismo grupo. |
| OpenLigaDB | Calendario/resultados y tabla derivada de temporada de Bundesliga femenina, reutilizando datos existentes. | Caché de temporada 2 h; la tabla no añade consultas. | Datos comunitarios, no garantía de cobertura. Tabla calculada sin sanciones administrativas; no sustituye una tabla oficial. |
| WTA oficial: PDF | Ranking completo validado por fecha, volumen y aliases explícitos. | Caché existente; respaldo validado hasta 14 días. | PDF del 12/10 validado con 1.545 entradas. Un ranking completo no demuestra cobertura completa de resultados. |
| WTA oficial: web | Nuevo calendario, cuadros, WC/Q/LL, superficie, perfiles, historial reciente y mejor ranking. | 100/día, 650/semana, 3.000/mes con reserva 100; máximo 16 requests/ciclo y 4 torneos; 8/min. | Son topes nuestros: el backend público del sitio no publica una cuota/SLA verificada. Prioriza WTA/WTA 125; numerosos cuadros ITF están vacíos. |
| PWHL oficial / HockeyTech | Nuevo calendario y resultados de hockey femenino con fechas UTC verificadas mediante iCal oficial. | 20/día, reserva 2; máximo 8/min. | Topes nuestros, sin cuota comercial verificada. Fuera de temporada puede devolver cero eventos; se omiten fechas que no se puedan verificar. |

Los contadores internos usan día/mes UTC y semana ISO; eso no permite deducir el reinicio comercial de una suscripción. El endpoint `/health` muestra presupuestos propios y, para APIs deportivas/Highlightly, el último saldo observado del proveedor, que puede quedar desactualizado. Redis conserva contadores y cachés; sin persistencia duradera, un reinicio puede perderlos.

## Qué cambia en tenis

- Una WC se considera confirmada solo cuando aparece en el cuadro oficial y se identifica a las dos jugadoras. El ingreso WC no añade puntos de debilidad.
- El motor consulta perfiles cuando existe brecha de ranking o WC verificada, dentro del límite por ciclo. Compara forma/superficie solo frente a bandas de rivales con muestras suficientes; no equipara victorias frente a rivales débiles con victorias frente a la élite.
- Las partidas WTA se filtran por año, identidad, individuales y resultado normal. Se excluyen walkovers, retiros, byes y resultados incompletos. El marcador viene orientado a la ganadora y se convierte a la perspectiva correcta.
- El historial da fechas de semana de torneo: no se usa para inferir horas de descanso. La paginación completada indica cobertura del feed consultado durante dos años, **no** una reconstrucción completa de todos los torneos ITF ni una prueba de condición amateur.
- Experiencia de carrera, mejor ranking y muestras evitan tratar automáticamente a una ex top 100 como debutante. Sin perfil completo, falta de partidos significa desconocido. La señal de experiencia exige WC oficial, pocos resultados registrados y una rival con experiencia y actividad verificadas; se describe con estos límites.
- Las dobles faltas se muestran solo si la estadística oficial dispone de al menos cinco partidos; no suman puntos ni garantizan derrotas. Brecha sin contexto suficiente sigue siendo candidato, no superioridad confirmada.
- El antiguo CSV inaccesible no interviene en el motor nuevo. No se eluden bloqueos de ITF; NCAA y ligas públicas vacías no se activaron sin datos comprobables.

## Consumo esperado y comprobación

El máximo por ciclo no es consumo diario estimado: las cachés evitan repetir requests. WTA refresca calendario cada 12 h, cuadros cada 4 h, resultados cada 24 h y perfiles cada 7 días; añade consultas de perfiles solo para candidatos. PWHL cachea HTML/bootstrap 24 h, calendarios 6 h e iCal 24 h. Las cachés se comprimen y guardan una vez al terminar el barrido.

OddsPapi mantiene aproximadamente tres listados/día más como máximo un feed de terminados/día antes de cachés/pausas: hasta ~120/mes en ese escenario, bajo sus topes y reserva. The Odds API puede consumir hasta 150 créditos/mes en scores; con coste 2 equivale a hasta 75 llamadas, sujeto además al saldo real y reparto temporal. Para las fuentes de análisis por equipo el consumo depende de candidatos, ligas y cachés: se mide después del despliegue, no se presume.

Para verificar saldos faltantes, basta con una captura del contador y del período/fecha de renovación, sin claves. La hora que muestra API-Sports para tu cuenta tiene prioridad. No hace falta facilitar tokens nuevos para WTA, PWHL, ESPN ni OpenLigaDB.

## Documentación y fuentes primarias revisadas

- API-Sports: https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide y https://www.api-football.com/terms
- Highlightly: https://highlightly.net/documentation/football/ y https://highlightly.net/documentation/basketball/
- OddsPapi: https://docs.oddspapi.io/ — fixtures, cuenta, scores y límites de ventana.
- The Odds API: https://the-odds-api.com/liveapi/guides/v4/ — créditos por endpoint.
- TheSportsDB: https://www.thesportsdb.com/documentation
- OpenLigaDB: https://api.openligadb.de/index.html
- WTA: https://www.wtatennis.com/tournaments y https://wtafiles.wtatennis.com/pdf/rankings/Singles_Numeric.pdf ; rutas/semántica comprobadas contra los scripts públicos oficiales `tournament-player-service.js`, `player-matches.js` y `tennis.js`.
- PWHL: https://www.thepwhl.com/en/stats/schedule ; widget HockeyTech e iCal enlazados por esa página.

## Pruebas

`python -m unittest -v test_radar test_proveedores_tenis`: 31 pruebas offline, sin Telegram ni claves privadas. Incluyen WC profesional, debut registrado, ranking desconocido, regreso ex top, rivales comparables, orientación del marcador, paginación por año, horarios fiables, caché comprimida, fechas iCal, restricciones de TheSportsDB y ventana OddsPapi. Además se probaron rutas públicas reales de WTA, ESPN y PWHL. CI ejecuta Python 3.11.
