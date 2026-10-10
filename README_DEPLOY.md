# Radar de asimetrías deportivas femeninas — despliegue

## Qué hace esta versión

- Analiza exclusivamente competiciones con evidencia positiva de ser femeninas: nombre femenino explícito o ID de competición agregado a una lista permitida.
- Combina Highlightly, API-Sports, OpenLigaDB, TheSportsDB V1, OddsPapi (solo fixtures) y ESPN. ESPN ya no gana por ser la primera fuente; se priorizan los proveedores con más contexto deportivo.
- Deduplica por nombres de equipos normalizados y día UTC, manteniendo las observaciones de todas las fuentes para buscar historial alternativo.
- No bloquea un partido porque un análisis haya quedado incompleto o todavía no tenga historial. Solo registra una clave al entregar la alerta a Telegram.
- No consulta, calcula, almacena ni muestra cuotas, mercados, bookmakers ni probabilidades implícitas. El módulo `tracker_cuotas_smart.py` queda como stub de compatibilidad sin llamadas de red, y `sugerir_mercado()` devuelve `None`.
- Evita el endpoint de ITF que había devuelto 403/404. No intenta eludir su WAF; el calendario WTA queda cubierto por el scoreboard de ESPN y su ranking si ESPN lo entrega.

## Archivos

Subí todos los archivos del ZIP al mismo directorio del repositorio. `render.yaml` define el comando de instalación, inicio y variables no secretas. Ejecutá localmente para validar:

```bash
python -m pip install -r requirements.txt
python -m py_compile *.py
python test_radar.py
```

Los tests son offline: no envían mensajes reales a Telegram ni consumen las cuotas de las API. Que los tests pasen no prueba que una clave o el plan del proveedor estén autorizados ni garantiza que un feed contenga partidos el día de la prueba.

## Variables obligatorias en Render

- `TELEGRAM_TOKEN`: token de BotFather.
- `CHAT_ID`: chat privado, grupo o canal donde el bot tenga permiso de publicar; también se puede usar `CHAT_ID_GRUPO` para un segundo destino.
- `UPSTASH_REDIS_REST_URL` y `UPSTASH_REDIS_REST_TOKEN`: recomendados para persistir alertas y presupuesto entre reinicios. El bot puede iniciar sin ellos, pero Render Free tiene filesystem efímero y no se deben considerar persistentes sus archivos locales.

## Variables opcionales de proveedores

- `HIGHLIGHTLY_API_KEY`: clave RapidAPI de Highlightly. Se empieza con una página por fecha y cuatro horas de caché. El límite local es 100 requests/día con reserva de 25 para análisis; ajustá `HIGHLIGHTLY_CACHE_MINUTES`, `HIGHLIGHTLY_RESERVA_ANALISIS` y `HIGHLIGHTLY_MAX_PAGINAS` solo tras observar el contador real del proveedor.
- `API_FOOTBALL_KEY`: clave API-Sports. Límite local conservador de 100/día compartido entre deportes y reserva de 12. `API_SPORTS_DEPORTES` limita las disciplinas consultadas. Usá `API_SPORTS_WOMENS_LEAGUES` para añadir IDs de ligas cuya denominación no deja claro que sean femeninas; sintaxis `Soccer:ID;Basketball:ID`.
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
