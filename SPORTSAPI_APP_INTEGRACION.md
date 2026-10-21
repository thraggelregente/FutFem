# SportsAPI.app y cuota mensual de SportAPI.ai — 21/10/2026

## Alcance

Dos proveedores diferentes: SportsAPI.app es multideporte; SportAPI.ai continúa sólo para fútbol. La integración nueva utiliza exclusivamente SPORTSAPI_APP_API_KEY, agregada en Northflank. Nunca se copia a GitHub, logs, evidencia ni mensajes.

La clave no está disponible en el entorno local de desarrollo. La documentación pública se verificó; la descarga directa del OpenAPI devolvió HTTP 403 desde este entorno. Las pruebas autenticadas reales y sus límites de acceso deben comprobarse en producción; una prueba offline o una clave cargada no acreditan cobertura femenina real.

## Deportes y capacidades

| Deporte | Calendario | Historial utilizable | Tabla |
|---|---|---|---|
| Fútbol | Femenino explícito | Misma liga/edición, 90 días, final normal | Temporada y participantes verificados |
| Básquet | Femenino explícito | Misma liga/edición, 90 días; se omiten prórrogas en esta primera versión | Temporada y participantes verificados |
| Tenis | Individual femenino real | Respaldo cuando falta historial reciente; sets completos, fechas exactas, ventana parcial de 90 días | No aplica; no inventa rankings desde semillas |
| Hockey hielo | Femenino explícito | Final en tiempo reglamentario; sin prórroga/penales | Temporada y participantes verificados |
| Handball | Femenino explícito | Misma liga/edición, final normal | Temporada y participantes verificados |
| Vóley | Femenino indoor | Marcadores terminados en sets al mejor de cinco | Temporada y participantes verificados |
| Rugby | Femenino explícito | Misma liga/edición, final normal | Temporada y participantes verificados |

No se anuncian 20 deportes integrados: softball, lacrosse y hockey césped no están en el catálogo anunciado; cricket requiere conversión explícita de formato/scorecards y no se mezcla con el motor de puntos. MMA, esports y otros necesitan validación femenina y motores específicos antes de alertar. El registro de competiciones explícito preserva las categorías y evita inferir género de un nombre de persona.

## Cuota compartida y uso

- 100 solicitudes/día UTC en total, no por deporte; 10/min. Sin reserva diaria inutilizable ni reinicio de cuota al desplegar.
- Un catálogo /v2/sports cacheado 24 h. Hasta 40 solicitudes nuevas/día de descubrimiento, incluidos catálogo y páginas. El resto queda disponible para historiales, tablas y verificación posterior de resultados. Las llamadas de contexto también comparten el mismo contador de 100.
- Todos los deportes compatibles participan. El orden rota cada seis horas para evitar prioridad fija de una disciplina.
- /v2/fixtures entrega diez ligas por página, no todos los partidos mundiales en una sola llamada. Se recorren páginas progresivamente y se conservan las ya observadas para hoy/mañana; hasNextPage o complete=false aparecen como truncamiento en cobertura. La cuota limita la profundidad posible: no se promete calendario universal.
- Caché persistente de doce horas para descubrimiento/contexto y una hora para verificación de resultados terminados. Hasta diez partidos recientes por equipo. Consultas por ID ya resuelto, sin búsquedas globales adicionales por nombre.
- RateLimit-Remaining informa el minuto: nunca se interpreta como saldo diario. Retry-After gobierna las pausas 429. 401/403 deshabilitan la fuente durante el proceso; no se reintenta agresivamente. Los errores de red también cuentan conservadoramente en el presupuesto local.
- El consumo local no conoce llamadas manuales o de otros programas con la misma cuenta. El proveedor aplica su cuota compartida y puede devolver 429 antes del contador local.

## Integridad y acompañamiento

La fuente complementa las rutas existentes de calendario, historial, tabla y resultados. Se conservan observaciones de fuentes coincidentes; sólo se remapean participantes con identidad verificada. No se unen ligas ni temporadas por parecido. En eventos aislados se conserva la regla de consultar el historial de su fuente/competición; no se transforma una copa internacional en una muestra doméstica.

H2H se obtiene de partidos individuales fechados del historial. /h2h devuelve un resumen agregado sin fechas: no se convierte en resultados ficticios ni se puntúa como evidencia reciente. Tablas exigen IDs de temporada y participantes, W+D+L=partidos, grupo no ambiguo; se rechazan eliminatorias y clasificaciones de otra edición. Los rankings, superficie y dobles faltas no se inventan cuando faltan campos.

En tenis se usa el nuevo historial como respaldo, no como sustituto de un perfil reciente WTA/Tennis API. Las muestras de 90 días se etiquetan como tales y no como consulta completa de dos años. No se modifican umbrales del detector ni se activan cuotas/mercados del proveedor.

## Control mensual de SportAPI.ai

La página oficial de precios anuncia 14.000/mes calendario UTC desde el 1 de noviembre de 2026, además de 2.000/día. DiarioMensual conserva el contador diario anterior y agrega uno mensual persistente; en octubre observa y prepara el estado, y desde noviembre aplica ambos topes. No agrega un supuesto límite semanal ni reparte rígidamente por día un cupo mensual libre.

El contador mensual inicial de octubre es parcial: no reconstruye pedidos anteriores a su instalación. Al rotar a noviembre empieza el mes desde cero con seguimiento completo del bot, siempre que el proceso nuevo ya esté instalado. Otros usos externos de la clave siguen siendo desconocidos. /health publica mes, consumo observado, límite, fecha de aplicación y completitud del contador local.

## Operación y pruebas

Sin claves locales: pruebas con transporte simulado, sin red ni Telegram. Suite completa, compilación y diff --check antes de publicar. Casos: siete deportes, género, simulados/dobles, horario, finalización, sets/puntos, identidad, temporadas/grupos, historial de tenis, integración en main, cuota compartida/cache, preservación de contadores y transición noviembre/diciembre.

Configuración: SPORTSAPI_APP_ACTIVO=0 desactiva la fuente; SPORTSAPI_APP_DEPORTES permite elegir disciplinas usando los nombres internos del bot. Por defecto incluye las siete compatibles. Revisión prevista /health: sportsapi-app-v1. En budgets.sportsapi_app, auth=verified sólo tras respuesta autenticada correcta; tables_verified/histories_verified y observaciones de cobertura informan aportes reales. configured_count no equivale a cobertura probada ni a independencia de los feeds de origen.

Fuentes primarias:
- https://sportsapi.app/docs
- https://sportsapi.app/
- https://sportapi.ai/pricing
