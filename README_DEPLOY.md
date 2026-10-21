# Radar de asimetrías deportivas femeninas — despliegue

## Despliegue actual: Northflank

SportsAPI.app multideporte y control mensual de SportAPI.ai: [SPORTSAPI_APP_INTEGRACION.md](SPORTSAPI_APP_INTEGRACION.md). Clave `SPORTSAPI_APP_API_KEY`; cuota compartida de 100/día para siete deportes compatibles.

Contexto por deporte y nueva sección de recomendaciones: [MOTORES_RECOMENDACIONES.md](MOTORES_RECOMENDACIONES.md). Revisión `sport-context-recommendations-v1`; conserva los umbrales del detector y se abstiene de recomendar cuando falta evidencia.

El bot corre como servicio en Northflank, con instalación `pip install -r requirements.txt`, inicio `python -u main.py` y ruta de salud `/health`. La configuración y los secretos se mantienen en Environment del servicio. El servicio de Render fue retirado; se elimina su manifiesto obsoleto. No hace falta UptimeRobot para mantener activo este servicio. Upstash Redis conserva el estado entre despliegues.

Último pack de fuentes y validación: [FUENTES_PASOS_2_3.md](FUENTES_PASOS_2_3.md). Las referencias posteriores a Render describen el despliegue anterior.


Mensajes del 14/10/2026: separan magnitud y respaldo de los datos, identifican los nombres en muestras/márgenes/Elo y explican resultados frente a rivales comunes, calendario, forma, H2H y rachas. Conservan todas las evidencias; una alerta larga se envía en partes con HTML balanceado y sólo se considera entregada si un destino recibe todas las partes. La sección **Recomendaciones** queda pendiente de evaluación, sin picks ni mercados automáticos. No cambia el puntaje ni los umbrales del motor.

La investigación de las cinco mejoras siguientes está en [PLAN_MEJORAS.md](PLAN_MEJORAS.md), como especificación **no implementada**. Incluye requisitos, costes, pruebas de aceptación y la fuente opcional Tennis API Free a validar con suscripción.

Ampliación 13/10/2026: cricket femenino T20/ODI es el 11.º deporte, con calendario SportScore e historial Cricsheet sin clave (`CRICSHEET_ACTIVO=0` permite desactivarlo). Alertas experimentales sólo con historial reciente suficiente; no usa cuotas de los demás proveedores. Archivos Cricsheet dinámicos por año, caché 24 h, hasta cuatro descargas/día. SportScore añade H2H fechados y contexto verificado de alineaciones/tiros al arco, dentro del presupuesto compartido existente. No se usan tablas/cuadros/goleadoras sin temporada o fecha verificable.

Conector opcional nuevo **BALLDONTLIE WNBA**: crear una cuenta Free en https://app.balldontlie.io/ y guardar su clave en Render como `BALLDONTLIE_API_KEY`. No pegar claves en GitHub ni en mensajes. No activar prueba de pago: el conector sólo consulta games WNBA gratis. NCAAW games requiere plan pago y no está integrado. Respeta cinco requests/min; el tope operativo local 1.000/día no representa una cuota publicada por el proveedor. Sin la variable, no hace pedidos. La validación autenticada se realiza tras agregar la clave.

## Qué hace esta versión

- Analiza exclusivamente competiciones con evidencia positiva de ser femeninas: nombre femenino explícito o ID de competición agregado a una lista permitida.
- Combina Highlightly, API-Sports, OpenLigaDB, TheSportsDB V1, OddsPapi (solo fixtures) y ESPN, además de los nuevos datos oficiales WTA y PWHL. ESPN ya no gana por ser la primera fuente; se priorizan los proveedores con más contexto deportivo.
- Deduplica por nombres de equipos normalizados y día UTC, manteniendo las observaciones de todas las fuentes para buscar historial alternativo.
- No bloquea un partido porque un análisis haya quedado incompleto o todavía no tenga historial. Solo registra una clave al entregar la alerta a Telegram.
- No consulta, calcula, almacena ni muestra cuotas, mercados, bookmakers ni probabilidades implícitas.
- Evita el endpoint de ITF que había devuelto 403/404. No intenta eludir su WAF; se integran los cuadros públicos WTA cuando tienen horario verificable, con ESPN como respaldo. La cobertura ITF sigue siendo incompleta.

## Archivos

Northflank construye el repositorio desde GitHub. Los comandos de instalación e inicio están indicados arriba. Ejecutá localmente para validar:

```bash
python -m pip install -r requirements.txt
python -m py_compile *.py
python -m unittest discover -v
```

Los tests son offline: no envían mensajes reales a Telegram ni consumen las cuotas de las API. Que los tests pasen no prueba que una clave o el plan del proveedor estén autorizados ni garantiza que un feed contenga partidos el día de la prueba.

## Variables obligatorias en Render

- `TELEGRAM_TOKEN`: token de BotFather.
- `CHAT_ID`: chat privado, grupo o canal donde el bot tenga permiso de publicar; también se puede usar `CHAT_ID_GRUPO` para un segundo destino.
- `UPSTASH_REDIS_REST_URL` y `UPSTASH_REDIS_REST_TOKEN`: recomendados para persistir alertas y presupuesto entre reinicios. El bot puede iniciar sin ellos, pero Render Free tiene filesystem efímero y no se deben considerar persistentes sus archivos locales.

## Variables opcionales de proveedores

- `HIGHLIGHTLY_API_KEY`: clave RapidAPI de Highlightly. Se empieza con una página por fecha y cuatro horas de caché. El límite local es 100 requests/día con reserva de 25 para análisis; ajustá `HIGHLIGHTLY_CACHE_MINUTES`, `HIGHLIGHTLY_RESERVA_ANALISIS` y `HIGHLIGHTLY_MAX_PAGINAS` solo tras observar el contador real del proveedor.
- `API_SPORTS_ACTIVO`: predeterminado `0` por cuenta suspendida. Reactivar con `1` únicamente cuando el proveedor restablezca el acceso.
- `API_FOOTBALL_KEY`: clave API-Sports. Límite local conservador de 100/día por API deportiva y reserva de 12. `API_SPORTS_DEPORTES` limita las disciplinas consultadas. Usá `API_SPORTS_WOMENS_LEAGUES` para añadir IDs de ligas cuya denominación no deja claro que sean femeninas; sintaxis `Soccer:ID;Basketball:ID`.
- `ODDSPAPI_API_KEY`: opcional. Por defecto el código usa únicamente `GET /v4/fixtures` y un chequeo de cuenta documentado como no facturable. No llama `/odds`, `/markets` ni `/bookmakers`. Los topes defensivos configurados son 6 llamadas billables/día y 180/mes; la cuota restante reportada por el proveedor se protege con `ODDSPAPI_RESERVA_CUOTA_REAL=25`. `ODDSPAPI_PROFUNDIDAD=0` deja apagados pedidos extra de forma/H2H.
- `THESPORTSDB_KEY=123`: API V1 gratis. `THESPORTSDB_WOMENS_LEAGUES` viene con IDs de fútbol femenino identificados en el directorio de TheSportsDB: `Soccer:5106,Soccer:4521,Soccer:3541,Soccer:3717,Soccer:3712,Soccer:3330`. Significan las competiciones listadas como Liga F de España, NWSL de EE. UU., Alemania Women Bundesliga, Francia Division 1 Féminine, Italia Serie A Women y Brasil Brasileiro Women. Si algún ID deja de existir o una liga cambia de ID, eliminá o sustituí ese identificador. Los IDs de competición se tratan como femeninos porque los verificaste/configuraste explícitamente; no expandas la lista sin verificarla.
- `OpenLigaDB`: no requiere clave. Por defecto consulta `ffb1:2026` (Frauen Fußballbundesliga, temporada 2026 según su listado oficial). Revisá `OPENLIGADB_WOMENS_LEAGUES` al cambiar la temporada.
- ESPN no requiere clave; se conserva como fuente de respaldo, especialmente para WTA y ranking disponible. Su falta de ligas/eventos en una competición no es un error que el resto de fuentes pueda resolver automáticamente.

## Render Free: dos limitaciones críticas

1. Render hace spin-down de un Web Service Free tras 15 minutos sin tráfico entrante. El bucle interno de 15 minutos NO evita ese sleep y un health check por sí solo no equivale a un ping externo continuo. Para un bot que debe correr día y noche, configurá un monitor externo como UptimeRobot para solicitar `https://TU-SERVICIO.onrender.com/health` cada 5 minutos, o usá una instancia siempre activa. El primer request después del sleep puede demorarse en despertarlo.
2. El filesystem local se pierde en reinicios, spin-down y redeploys. Configurá Upstash Redis REST para que las claves de alertas y los contadores diarios/mensuales sobrevivan. Al pasar de la versión vieja a esta se usa `alertas_enviadas.json` en vez del registro histórico `notificados.json`; es intencional para que las antiguas claves de análisis no bloqueen el radar. En la primera versión desplegada podrían volver a notificarse eventos antiguos todavía programados.

## Presupuestos y alcance real

Los contadores propios son topes de seguridad, no una promesa de cuota garantizada por un proveedor. La cuota real puede cambiar según suscripción y endpoint. Mirá los logs `[api_sports]`, `[highlightly]`, `[oddspapi]` y `HTTP ...` al menos durante el primer día. Si un plan devuelve 403/404/errores de acceso, el módulo entra en enfriamiento y deja de repetir el mismo request en cada ciclo. TheSportsDB V1 limita bastante algunos endpoints en el plan gratuito, aunque la API responda HTTP 200; por eso el calendario usa consultas por ID de liga, no una búsqueda global poco útil.

## Filtro femenino y calidad de señal

La lista blanca de ligas es la opción preferida cuando el nombre de la competición o de los equipos es ambiguo. No agregues IDs masculinos a los campos `*_WOMENS_*`. Los partidos con timestamp ausente o ambiguo se descartan en vez de inventar una hora. En fútbol/básquet/vóley/hockey y demás deportes de equipo el motor exige suficiente historial comparable antes de alertar; si no existen datos, el fixture permanece apto para reintento en el ciclo siguiente, mientras que los fixtures y calendarios permanecen cacheados para cuidar requests.

## Fuentes y documentación

- TheSportsDB V1: https://www.thesportsdb.com/documentation
- OpenLigaDB API y ligas disponibles: https://api.openligadb.de/index.html y https://beta.openligadb.de/Leagues?season=2026
- OddsPapi API: https://oddspapi.io/
- Render Free y filesystem efímero: https://render.com/docs/free


## Correcciones de calidad y consumo

- API-Sports conserva contadores por API deportiva. Highlightly separa los hosts deportivos y comparte un contador solo para All Sports. Los contadores nuevos usan claves `v2`; no se borra Redis. Las cabeceras del proveedor corrigen el saldo disponible después de cada respuesta.
- En endpoints medidos no hay reintentos HTTP automáticos ocultos. Los intentos sin respuesta se reservan conservadoramente; el saldo del proveedor sigue siendo la referencia final.
- El orden de análisis rota por último intento persistido. Participantes indefinidos y tenis sin ambos rankings ni WC oficial no consumen el máximo de análisis. Las búsquedas por nombre mantienen su tope y enfriamiento.
- Las identidades distinguen deporte, juveniles y reservas. Los historiales deben contener al equipo, estar terminados, no ser futuros y pasar la ventana temporal. El libro reconstruye las firmas desde los nombres almacenados; no puede recuperar nombres previamente truncados ni identidades ambiguas entre países.
- Forma, triangulación, H2H, rachas y Elo comparten un máximo de cuatro puntos. Se exige evidencia de diferencia de nivel. Calendario y bajas no bastan por sí solos. Las familias de señales no se presentan como estadísticamente independientes. La magnitud y la calidad temporal/muestral se muestran por separado; no son probabilidades calibradas.
- La tabla se consulta también como evidencia inicial y como posible contradicción, priorizando ESPN y tablas derivadas de OpenLigaDB, después API-Sports y Highlightly. Para eventos de Highlightly se utiliza su liga/temporada y se exige que ambos equipos estén en el mismo grupo.

## Tenis

`ranking_wta.py` descarga el PDF oficial de individuales WTA y valida fecha, volumen, cobertura superior a mil posiciones y ausencia de nombres ambiguos. Se guarda el último snapshot validado; si falla una descarga se permite respaldo de hasta 14 días. ESPN queda como respaldo fechado del top 150. Un nombre ausente siempre es ranking desconocido. El alias Catherine/Caty McNally es explícito y verificable.

Las brechas de ranking generan **candidatos**, no una afirmación de mismatch confirmado sin contexto reciente. Los cortes siguen siendo heurísticos y requieren evaluación histórica antes de afirmar precisión. El umbral general de equipos sigue siendo cuatro puntos.

El nuevo motor utiliza perfiles e historial del sitio oficial WTA: entry WC, superficie, experiencia registrada y forma ante bandas comparables de rivales. Una WC por sí sola no suma puntos. Se conserva el candidato por ranking cuando falta contexto, y no se confunde ausencia de datos con condición amateur. La cobertura ITF no es completa; la paginación validada solo certifica el feed consultado.

Los límites, restricciones de planes y comprobaciones públicas están en [PROVEEDORES.md](PROVEEDORES.md).

## Validación

Ejecutar `python -m unittest discover -v` (94 pruebas offline). Las pruebas no requieren claves ni envían Telegram. Cubren la alerta Brynäs/MODO con las señales de la captura previa (sin usar el resultado final), presupuestos por suscripción, ranking desconocido, alias, datos antiguos/ajenos/futuros, caché de ranking, salud, rotación de la cola, fuentes públicas, el motor separado de cricket y claridad/entrega íntegra de mensajes.

Se verificó además el parser con el PDF oficial del 12/10/2026: 1.545 entradas, puesto máximo 1.504 y alias McNally resuelto. Esto valida el formato actual, no la estabilidad futura ni la precisión predictiva. No se probaron llamadas con las claves privadas; el despliegue anterior se verificó mediante su endpoint de salud.

El endpoint de salud informa `starting`, `ok` o `degraded`, el último barrido, análisis y presupuestos. Devuelve HTTP 503 si el barrido deja de avanzar después de la gracia de arranque. Los reinicios reales del proveedor pueden diferir del calendario UTC de los contadores internos.

## Ampliación de fuentes públicas

Se añaden FIVB/VIS y CEV para vóley femenino, y ESPN para softball, lacrosse y hockey sobre césped femeninos. Son diez deportes habilitados con cobertura desigual. Los nuevos deportes tienen bloqueados los respaldos que consumen cuota de las APIs existentes; sus alertas se identifican como evaluación experimental.

`BBS_API_KEY` es opcional: prepara una fuente adicional de WNBA mediante el plan Free de Big Balls Sports Data. Sin key no hace llamadas y no figura como fuente activa. El acceso autenticado aún debe comprobarse. FIBA GDAP no se anuncia como fuente activa ni gratuita: su registro requiere aprobación/acuerdo. Ver restricciones, fechas, consumo y enlaces primarios en [PROVEEDORES.md](PROVEEDORES.md).

SportScore está activo sin key como respaldo parcial de fútbol femenino. `SPORTSCORE_ACTIVO=0` lo desactiva. Las alertas basadas en sus datos incluyen atribución visible; cobertura e historial incompletos no se convierten en señales de debilidad. BBS empieza con 250/día y reconoce 500 solo mediante la cabecera diaria del proveedor.

World Rugby está activo sin key para femenino XV (`WORLD_RUGBY_ACTIVO=0` lo desactiva); no mezcla seven. SportScore usa 24 h móviles y caché ampliada: `SPORTSCORE_LIMIT_24H` predetermina 9.800, máximo 10.000. `/health` muestra la ventana y HTTP del último barrido. OpenLigaDB admite camelCase actual y valida liga/temporada/género. Las ligas nuevas del catálogo que están vacías o incompletas no se activan automáticamente.

SportAPI.ai: guardar la key Free como `SPORTAPI_API_KEY` en Environment de Render y aplicar el deploy. Sin esa variable la fuente está desactivada. Cupo 2.000/día UTC, saldo real en `/health`, cachés y solo las competiciones femeninas positivas del catálogo. No pegar credenciales en archivos del repositorio. Ver comprobaciones y límites en PROVEEDORES.md.

SportScore ya consulta fútbol, básquet femenino 5x5 y calendario de tenis individual real. Su límite 9.800/24 h móviles se comparte entre esos deportes. Mantiene WTA oficial para ranking/WC/perfiles, rechaza SRL/simulaciones, dobles y cruces con identidad/horario contradictorios. Cricket continúa pendiente de motor específico.

## Observabilidad y evaluación prospectiva

La revisión `radar-evaluation-v2` añade cobertura, diario inmutable, seguimiento de resultados, evaluador offline y planificación con comparación en sombra. Estado operativo, mapa de fuentes, límites y clave opcional `TENNIS_API_RAPIDAPI_KEY`: [OPERACION_EVALUACION.md](OPERACION_EVALUACION.md).

## Contexto de tenis y vóley

Perfiles/historial Tennis API, tablas FIVB verificadas y contexto oficial LVF/LNV: [PACK_CONTEXTO_TENIS_VOLEY.md](PACK_CONTEXTO_TENIS_VOLEY.md). Revisión `tennis-volley-context-v1`, sin cambiar umbrales.
