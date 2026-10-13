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

## Ampliación gratuita y vigencia — 12/10/2026

El radar tiene diez deportes configurados: fútbol, básquet, tenis, hockey sobre hielo, handball, vóley, rugby, softball, lacrosse y hockey sobre césped. Los tres últimos consultan exclusivamente los scoreboards femeninos verificados de ESPN. El motor usa umbrales explícitos por deporte y los presenta como evaluación experimental: no se afirma una precisión calibrada.

Los deportes nuevos tienen bloqueadas las rutas de calendario, búsqueda por nombre, tablas y H2H de los proveedores medidos. No se modificaron sus presupuestos. Su historial se filtra por temporada; no usa el libro global ni Elo hasta disponer de un esquema que conserve todas las identidades de partidos. En particular, dos partidos de softball entre los mismos equipos en una doble jornada tienen claves de evento/alerta distintas.

| Fuente nueva | Estado | Uso y consumo |
|---|---|---|
| FIVB/VIS | Activa sin clave, desactivable con `FIVB_ACTIVO=0` | Un pedido público agrupado de partidos de los últimos 90 días y próximos dos, caché 6 h. Verifica género del torneo por fila (W/1), fechas de inicio/fin, UTC, IDs y resultado normal. Tope propio 30/día con reserva 2 y 6/min; consumo base alrededor de 4/día. |
| CEV Live Scores | Activa sin clave, desactivable con `CEV_ACTIVO=0` | Proxy público oficial: catálogo 24 h y partidos 6 h, alrededor de 5 consultas/día. Tope propio 30/día con reserva 2 y 6/min. Gender=0 y MaleNotFemale=false deben concordar; exige SeasonID, fechas de competición, UTC y caché remota de hasta 24 h. Beach/snow y modalidades contradictorias se omiten. |
| Big Balls Sports Data, WNBA | Conector preparado; pendiente de prueba autenticada | `BBS_API_KEY` opcional en Render. Documenta plan Free de 250/día (500 vinculando GitHub), temporada actual y más reciente; nuestro tope inicial es 250/día y sube a 500 solo si la cabecera del bucket diario lo confirma, ritmo 8/min y caché 6 h. Solo `/v1/matches?sport=basketball&league=wnba`, hasta tres páginas de 200; no llama mercados ni H2H de pago. Rechaza NBA, años distintos, horas de precisión solo fecha y caché sin edad verificable. No se afirma cobertura completa sin verificar con una key real. |
| FIBA GDAP | No integrada | No se confirmó un plan gratuito utilizable por este proyecto. La documentación exige revisión de registro, acuerdo y autorización/suscripción; no equivale a registrarse y recibir una key gratuita inmediata. La web de competiciones respondió 403. |

Los historiales de FIVB, CEV y BBS quedan separados por competición/temporada, con IDs propios. No se mezclan con históricos de otras fuentes ni se cuentan como evidencia independiente por multiplicar proveedores. La caché persistente de ESPN evita repetir descargas tras un deploy; cuando un rango no funciona o está fuera de temporada, consulta como máximo siete días de partidos anunciados, no 45 días vacíos. Las tablas ESPN solo se utilizan si su temporada coincide con la del evento.

El PDF WTA ya vencía a los 14 días. Una regresión simula enero de 2027 y comprueba que una lista de diciembre de 2025 se rechaza. Los torneos pueden tener un nombre nominal del año siguiente y fechas vigentes: se verifican límites de fechas y IDs, no se descartan por comparar únicamente el texto del título.

Comprobaciones públicas reales: FIVB devolvió un próximo partido de TAURON Liga Kobiet y 638 resultados normales; CEV, 146 resultados dentro de las validaciones. Los scoreboards individuales de ESPN devolvieron 32 resultados de softball, cuatro de lacrosse y 31 de hockey sobre césped; la lectura de historial de este último produjo 108 partidos de 84 equipos. Estos números describen la comprobación, no prometen igual disponibilidad en cada ciclo.

Validación actual: `python -m unittest -v test_radar test_proveedores_tenis test_fuentes_gratis`, 50 pruebas offline. CI utiliza Python 3.11.

Fuentes primarias adicionales:

- FIVB consulta pública y filtros: https://www.fivb.org/VisSDK/VisWebService/GetVolleyMatchList.html y https://www.fivb.org/VisSDK/VisWebService/VolleyMatchFilter.html
- Género FIVB: https://www.fivb.org/VisSDK/VisWebService/EventGender.html
- CEV: https://livescores.cev.eu/ y su cliente público https://livescores.cev.eu/app.js
- NCAA softball femenino: https://www.ncaa.org/championship/division-i/softball/
- FIBA registro y condiciones: https://gdap-portal.fiba.basketball/sign-up y https://gdap-portal.fiba.basketball/terms-of-services
- Big Balls Sports Data: https://bigballsdata.com/wnba-api y https://bigballsdata.com/openapi.json

Para activar BBS, crear una key del plan Free para basketball en su panel, guardarla como `BBS_API_KEY` en Render y verificar después saldo, acceso WNBA y respuestas. No publicar la key en chats, commits ni capturas. No hace falta ninguna key adicional para las fuentes ya activadas en esta ampliación.


## Cuenta suspendida y respaldo — 13/10/2026

El usuario confirmó la suspensión de su cuenta API-Football. `API_SPORTS_ACTIVO=0` es ahora el valor predeterminado: no se hacen llamadas con esa cuenta en ninguno de sus hosts deportivos. No se atribuye una causa sin una respuesta del proveedor. Si el proveedor restablece la cuenta, se puede reactivar explícitamente con `API_SPORTS_ACTIVO=1`. Un error de suspensión en el cuerpo también detiene todos los hosts durante el proceso.

SportScore se integra como respaldo parcial de fútbol femenino sin clave. Consulta fixtures de hoy/mañana UTC, dos llamadas cada hora como máximo antes de caché; solo analiza eventos a menos de 24 h, con género positivo y hora verificable. Resuelve identidad exacta de equipo y consulta su widget, separando resultados por competición y últimos 90 días. No deduce tabla, Elo ni historial completo del widget: puede incluir muchos futuros y pocos terminados. El límite de 200 fixtures puede truncar cobertura y se informa en logs. Tope propio 1.000/día, caché y 6/min; el proveedor indica aproximadamente 10.000/24 h por IP. `SPORTSCORE_ACTIVO=0` permite desactivarlo. Telegram incluye el crédito visible requerido por sus términos.

Comprobación pública: el catálogo de BBS anuncia nueve deportes (fútbol, básquet, fútbol americano, béisbol, hockey sobre hielo, cricket, MMA, boxeo y F1). El catálogo consultado contiene WNBA y 287 entradas femeninas de cricket, incluyendo ligas, torneos y series históricas: no son 287 ligas activas ni una promesa de acceso Free a todo el archivo. No se encontraron ligas femeninas de fútbol identificadas. La documentación MMA dice UFC y resultados/perfiles aún pendientes, aunque el catálogo también enumera PFL: esa contradicción impide afirmar cobertura completa. Boxeo tiene resultados limitados a comisiones estadounidenses, principalmente Nevada, y records de carrera aún nulos. No se activan alertas de combate ni cricket con un motor sin adaptación.

BBS comparte cuota diaria entre deportes: 250/500 requests y 100/min, reinicio a medianoche UTC (21:00 Argentina). El catálogo público `/v1/sports` y `/v1/coverage` no necesita key. La key del usuario ya figura configurada en Render, pero la presencia en `/health` no prueba integridad de resultados ni saldo real. Nuestro conector sigue exclusivamente en WNBA.

La sustitución es combinada, no equivalente: fútbol conserva Highlightly/ESPN/OpenLigaDB y añade SportScore; básquet dispone de Highlightly/ESPN/BBS WNBA; vóley de Highlightly/FIVB/CEV; hockey de Highlightly/PWHL/ESPN; handball de Highlightly. Rugby pierde su principal conector de historial y sigue pendiente de respaldo equivalente comprobado.

Fuentes primarias: https://sportscore.com/developers/ , https://sportscore.com/developers/openapi.yaml , https://sportscore.com/terms/ , https://bigballsdata.com/pricing , https://bigballsdata.com/docs/rate-limits , https://api.bigballsdata.com/v1/coverage , https://bigballsdata.com/mma-api , https://bigballsdata.com/boxing-api .
