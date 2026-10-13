# Fuentes, cobertura y consumo

## Ampliación del 13/10/2026: SportScore y cricket

- **SportScore**: H2H fechados en fútbol/básquet, pareja exacta, misma competición, últimos 365 días. Descarta el resumen de toda la carrera y deduplica cruces presentes en la forma. `match` exige pareja, orientación, competición y timestamp exactos: el slug puede devolver un encuentro anterior. Un estado incompatible del mismo partido frena la alerta. Alineaciones confirmadas con 11 titulares por lado son contexto, no lesiones inferidas. En alertas de fútbol con historial SportScore, consulta hasta dos detalles recientes por lado y muestra tiros al arco como contexto, sin puntaje nuevo. Comparte el presupuesto existente de 9.800/24 h móviles y caché persistente.
- **Widgets evaluados y excluidos del motor**: WSL `standings` y `topscorers` entregan datos sin temporada; Champions femenina `bracket` entrega cruces sin fechas/temporada; Wuhan devuelve cuadro vacío; `player` de tenis devuelve 400. `updated` no acredita vigencia de la temporada. `tracker` no aporta señales previas verificadas y no se consulta. No se inventan rankings, WC, bajas ni experiencia desde campos ausentes.
- **Cricket es el 11.º deporte**, calendario SportScore T20/ODI de categorías reconocidas. No llama otras APIs comerciales para este deporte. Sin Test, The Hundred ni juveniles. Motor propio con resultados femeninos Cricsheet, formato y tipo de equipo explícitos; nunca resta runs como goles. Excluye DLS, no-result, empates/super-over y juveniles/reservas. Clubes: misma competición exacta. Selecciones mayores: mismo formato. Ventana 90 días, ≥5 resultados por lado, ≥80% vs ≤20% victorias, ≥2 triunfos amplios (T20 ≥40 runs; ODI ≥80 runs; o ≥7 wickets) y ≥2 H2H recientes ganados. Umbrales exploratorios sin calibración predictiva; Telegram etiqueta experimental y declara que las señales pueden compartir resultados. Sin historial suficiente no alerta.
- **Cricsheet**: fuente nueva gratuita sin key. Descarga en segundo plano el paquete de últimos 30 días y el año UTC actual; añade el año anterior sólo si la ventana de 90 días cruza enero. Caché 24 h, hasta cuatro descargas/día como tope operativo local, límites de tamaño/tiempo, almacenamiento compacto y bloqueo de caché para concurrencia. No bloquea el barrido esperando archivos grandes; hasta completar el índice no inventa resultados. Salud informa resultados indexados y si sigue actualizando. Atribución y licencia ODC-By en Telegram. Archivo 2026 probado: 644 partidos brutos, muchos fuera de la ventana reciente; archivo últimos 30 días: 43. No cubre todo ni se actualiza necesariamente al instante; ausencia de registros no implica inexperiencia.
- **BALLDONTLIE WNBA**: conector opcional de calendario/historial, pendiente de validación autenticada. Activar con `BALLDONTLIE_API_KEY` en Render. Sólo `/wnba/v1/games`, paginación con detección de cursores repetidos, `status_state`, año y fecha UTC. Caché 6 h, 5 requests/min (13 s mínimos entre pedidos). Tope local 1.000/día: **no es una cuota diaria anunciada por el proveedor**. Sin key no llama ni aparece activa. WNBA teams/players/games son gratis; standings/injuries/stats son de pago. NCAAW games no es gratis; no se consulta. WTA rankings son gratis, pero matches/career/H2H son de pago; no reemplaza gratuitamente el perfil WTA. No hace falta activar una prueba de pago.

Fuentes primarias: https://sportscore.com/developers/ ; https://sportscore.com/developers/openapi.yaml ; https://cricsheet.org/downloads/ ; https://cricsheet.org/format/json/ ; https://cricsheet.org/licensing/ ; https://wnba.balldontlie.io/ ; https://ncaaw.balldontlie.io/ ; https://wta.balldontlie.io/ . Live Volleyball API da 100 créditos iniciales y luego compra de créditos: no es una cuota gratuita recurrente, no se integró. Big Balls cricket comparte Free 250/día (500 con GitHub), no se multiplicó su cuota.

Validación: 88 pruebas offline y CI Python 3.11 con descubrimiento de todos los módulos. Muestras del 13/10/2026, no promesas de cobertura permanente.

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


## Reemplazos verificados — 13/10/2026, tarde Argentina

Render estaba operativo al inicio de esta revisión: 71 barridos, último de 10,8 s y 40 evaluaciones. API-Sports no figuraba activa. SportScore había llegado a 998/1.000 del tope local; eso no demuestra que el proveedor agotara su cuota. La caché de solo 96 entradas compartía identidades de siete días con feeds de seis horas: por prioridad de vencimiento podía expulsar históricos todavía válidos. Se amplía a 4.096 entradas y se corrige el TTL de búsquedas negativas: seis horas, no siete días.

SportScore publica aproximadamente 10.000/24 h/IP, sin key. Ahora dispone de un presupuesto persistente **móvil de 24 horas**, predeterminado 9.800 y configurable mediante `SPORTSCORE_LIMIT_24H` hasta 10.000; 30/min y un segundo mínimo entre llamadas. Cambiar de día UTC no renueva el margen. La migración conserva conservadoramente el consumo del contador anterior; `/health` etiqueta esta ventana por separado. El saldo local no equivale al saldo real de una IP compartida en Render. Sigue sin afirmarse cobertura completa ni tabla vigente sin datos de temporada. Prueba actual: cuatro próximos eventos femeninos en dos llamadas; fixtures pueden alcanzar 200 y truncarse.

Se reparó OpenLigaDB: el contrato público actual es camelCase (`team1`, `matchIsFinished`), mientras nuestro lector esperaba PascalCase. La conversión acepta ambos contratos, incluida caché persistida, y verifica shortcut, temporada y nombre femenino por fila. La descarga de `ffb1/2026` contiene 182 fixtures y 42 terminados; el lector recupera seis resultados recientes de Bayern. No se añadieron ligas por su mera presencia en el catálogo: `ffb2/2026` está vacío y Regionalliga West solo tiene nueve terminados de 240 fixtures.

World Rugby se incorpora sin key para **mujeres XV**, `sport=WRU/wru`. El contrato se comprobó en el HTML y JS oficiales de https://www.world.rugby/tournaments/fixtures-results y en su API pública `https://api.wr-rims-prod.pulselive.com/rugby/v3/match`. Rechaza varones, seven, juveniles ambiguos, estado no terminado, vencedor incompatible, fechas fuera del evento y horas inconsistentes con GMT offset/label. El epoch es UTC: no se aplica de nuevo el offset. Consulta últimos 90 días y próximos dos; alerta solo en la ventana de 24 h. El historial queda aislado por ID de competición y participante. No consulta APIs comerciales, ranking, mercados ni tablas calculadas.

Prueba real World Rugby: 86 registros de muestra, 77 resultados válidos después de filtros. Competencias: WXV, Farah Palmer Cup, Premiership Womens Rugby Cup, Super Rugby Women, Super Rugby Aupiki, internacionales femeninos, O'Reilly Cup y Women's Rugby’s Greatest Rivalry. Una consulta agrupada produjo esos 77 resultados. La búsqueda a 33 días encontró 23 futuros, de los que 22 identifican WRU explícitamente; la siguiente fecha verificada es 16/10. Ningún evento entra en próximas 24 h en esta comprobación. No se promete cobertura mundial de clubes. Caché seis horas, normalmente cuatro llamadas/día si basta una página, máximo cuatro páginas por refresco y tope propio 30/día con reserva dos y 6/min. El proveedor no publica una cuota comercial verificada. Desactivable mediante `WORLD_RUGBY_ACTIVO=0`.

Alternativas contrastadas y no activadas:
- Sportmonks Free: solo Danish Superliga y Scottish Premiership masculinas. Fútbol femenino es de pago. https://www.sportmonks.com/football-api/free-plan/
- football-data.org Free: 12 competiciones del catálogo gratuito, sin ligas femeninas identificadas; 10/min y datos retrasados. https://www.football-data.org/coverage y https://www.football-data.org/pricing
- FootyStats Free: PL solamente, 180/h. No sustituye la cobertura femenina. https://footystats.org/api
- Football Web Pages: diez/min, pero acceso gratuito limitado a webs oficiales de clubes no profesionales; no se presume autorización para nuestro bot. https://www.footballwebpages.co.uk/api
- ScoreBat: feed gratis limitado de vídeos y partidos seleccionados/antiguos, no historial/calendario integral. https://www.scorebat.com/video-api/docs/
- SportAPI.ai: documenta 2.000/día/key, reinicio 00 UTC, todos sus endpoints y ligas. Hace falta una key Free para comprobar sus ligas femeninas y resultados. La consulta sin key responde 401, y la ruta interna de la web restringe su uso con 403; no se elude esa restricción. No se activa por una promesa de marketing. https://sportapi.ai/pricing y https://sportapi.ai/docs
- TheSportsDB PWR 5166: género Female comprobado, metadata de temporada 2025-2026; consulta 2026-2027 devuelve `events: null`. No se toma esa respuesta 200 como calendario vigente.

`/health` incluye los códigos HTTP agregados del último barrido, sin keys ni datos personales, para distinguir fuentes configuradas de respuestas efectivamente recibidas. Los contadores vacíos pueden indicar lectura desde caché, no caída. No se alteran los presupuestos de Highlightly, OddsPapi, The Odds API ni BBS.


## SportAPI.ai autenticada — 13/10/2026

La key Free proporcionada por el operador se usó solo en headers y pruebas de memoria; no se guarda en este repositorio. Primer response autenticado confirmó `Limit=2000`, `Remaining=1999` y reset 00 UTC. Nueve llamadas totales de comprobación dejaron 1.991, salvo uso concurrente posterior. Se verificaron catálogo, tres ligas, WSL standings, fixtures de hoy/mañana y Arsenal, más WSL2 desde el conector.

Catálogo: 117 competiciones, 13 femeninas identificadas: AFC Women's Asian Cup (96), English WSL 2 (80), Women's FA Cup (90), Women's League Cup (95), Women's Super League (59), WSL/WSL2 Play-off (17341), UEFA Women's Champions League (67), UEFA Women's Nations League (111), UEFA Women's Under 19 Championship (14023), Women's European World Cup Qualifiers (125), Welsh Premier Women's League (73), FIFA Women's Champions Cup (109), Internationals Women (93). No hay NWSL ni ligas femeninas de Alemania/España identificadas en este catálogo. Presencia no implica cobertura completa ni actividad actual.

Conector opcional `fuente_sportapi.py`, key solo vía `SPORTAPI_API_KEY` en Render. Sin key no realiza requests y no figura como activo. Hace una lectura de catálogo cacheada 24 h y dos o tres fechas cada hora (alrededor de 49–73 requests/día antes de históricos). Historial por ID de equipo solo para eventos/candidatos, caché 6 h; ritmo propio 20/min, cupo 2.000/día UTC con reserva 10, corregido con saldo real observado. No cambia quotas de otras fuentes y no consulta mercados. Respeta 429/reset/Retry-After y detiene accesos 401/403.

Prueba: cuatro eventos femeninos a menos de 24 h con kickoff UTC y cinco resultados WSL recientes de Arsenal. La consulta de liga limita recent_results a 20 globales; no se usa como historial completo del equipo. Los perfiles también incluyen futuros y pueden truncar resultados: falta de datos no prueba debilidad. El historial queda aislado por league ID y exige participantes, estado FT, marcador válido y últimos 90 días. Rechaza PENS/AET, aplazados, masculino y fechas futuras; añade U19 a ambos equipos si el torneo lo especifica. El alias exacto United States→USA coincide con el nombre de SportScore y evita duplicar ese partido.

Se encontró una diferencia temporal real: US–España y Brasil–Argentina tienen date 13/10, datetime CET 14/10 01:00/01:30 y kickoff_utc 13/10 23:00/23:30. Se consultan las fronteras UTC y CET y se deduplica por ID. Solo kickoff_utc decide hora/ventana; nunca se interpreta datetime como UTC. En los perfiles de equipo solo se proporciona día: se conserva esa precisión y se deshabilitan señales de descanso/congestión que requieren calendario completo. La tabla WSL devuelve 14 equipos, pero sin una temporada explícita verificable, por lo que no se incorpora al motor. Contrato: https://sportapi.ai/docs ; cuota: https://sportapi.ai/pricing .

Activación pendiente de que el operador guarde `SPORTAPI_API_KEY` en las variables de Render. El código está preparado, pero una prueba local con key no acredita activación en producción. Validación: 69 pruebas offline, más respuestas autenticadas actuales; no se publican credenciales.


## SportScore multideporte — 13/10/2026

El operador señaló correctamente que estábamos limitando el conector a fútbol. La revisión autenticada en Render confirmó primero SportAPI.ai activa, nueve HTTP 200 y saldo observado 1.982. Luego se contrastaron los cuatro deportes públicos de SportScore, no solo el catálogo comercial.

El conector ahora consulta Soccer, Basketball y Tennis; comparten el mismo límite móvil de 9.800/24 h, no un cupo por deporte. Dos fechas/hora por deporte significan como máximo unas 144 llamadas base/día más perfiles de equipos, sujetas a caché. Mantiene atribución visible, límites y prioridades WTA/ESPN/Highlightly anteriores. Cricket no se activa con un motor que compararía mal 183/4 vs 182/8 y mezclaría T20 con ODI sin contexto de entradas/overs/DLS.

Básquet: página de 17/10 devuelve 137 próximos, 19 con evidencia femenina antes de filtro temporal/duplicados. Entre las ligas están WNBL Australia, Turquía, Finlandia, Dinamarca, Suecia y República Checa. El catálogo web tiene muchas más, pero no se presume actividad por figurar allí. Fenerbahce Women resuelve a una identidad única: widget con 19 registros, cuatro resultados válidos recientes (tres de liga y uno de SuperCup); historial usado solo en la misma competición. Benfica Women, Armann Women y Tapiolan Honka Women presentan identidades duplicadas; se omiten en búsquedas ambiguas. Armann widget devolvió cero pese a que la página de su ID canónico muestra resultados: web y API no son equivalentes. WNBL duplica UC Capitals/Canberra ante Bendigo a la misma hora; se omiten cruces con rivales contradictorios hasta resolver ID/alias, no se generan dos alertas. No hay backend de tablas verificado: EuroLeague Women standings respondió 404.

Tenis: 14/10 devuelve 90 próximos totales, 37 femeninos incluyendo tres dobles; 32 individuales pasaron género, participantes y ventana durante la prueba. WTA Wuhan y WTA 125 Mallorca/Rovereto/Lisboa están presentes. Se filtran SRL/simulaciones, dobles, placeholders R16P1, participantes no resueltos, scores ya iniciados y estados cancelado/retirado/aplazado. Se observó `status=finished` con `status_text=Canceled`, por lo que no basta el estado genérico. La búsqueda incluye ITF en catálogo, pero no se demostró calendario ITF completo ni activo. El widget Swiatek tiene 30 filas/28 terminados y pocos meses: no prueba carrera completa; player stats para tennis responde 400 no disponible. Match detail devuelve incidentes/stats vacíos y no WC. Por ello el motor sigue usando PDF/perfiles WTA oficial para ranking, WC y experiencia; SportScore amplía calendario y nunca convierte ausencia de historial en amateur.

Cricket: cuatro próximos femeninos en la muestra de 14/10, T20 Spring Challenge, ODI Australia–Bangladesh y National T20. Un terminado femenino de Spring Challenge devolvió marcador tipado en texto runs/wickets. Es un candidato para un motor específico, no se reutilizan umbrales de básquet/fútbol.

Soccer mantiene IDs existentes, cachés y búsquedas. Básquet/tenis usan namespaces separados; URLs sin ID canónico derivan una clave de participantes/competición/hora, diferenciando repeticiones de un mismo cruce. Cada perfil se resuelve por deporte. El historial permanece aislado y la nueva modalidad no gasta cuotas de otras APIs. Todos los deportes de SportScore excluyen partidos simulados y estados incompatibles. No se usa 3x3 bajo umbrales de 5x5.

Prueba real del conector ampliado: 32 próximos de tenis y uno de básquet, cuatro requests compartidos. Validación: 74 pruebas offline, respuestas públicas API y contraste de página canónica. Fuentes: https://sportscore.com/developers/ , https://sportscore.com/developers/openapi.yaml , https://sportscore.com/tennis/ , https://sportscore.com/basketball/ y https://sportscore.com/cricket/ . No se promete cobertura completa por estos snapshots.

Comprobación adicional de tabla: `football`/`english-fa-womens-super-league` devuelve HTTP 200 y tabla WSL. EuroLeague Women se resolvió por búsqueda exacta a `euroleague-women`, y con ese slug sigue devolviendo 404. La tabla WSL no publica temporada explícita: no se añade al motor como tabla vigente por la mera fecha de actualización. La web conserva información más rica que algunos widgets, por ejemplo el ID canónico Armann.
