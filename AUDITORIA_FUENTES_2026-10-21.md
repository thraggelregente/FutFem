# Auditoría de cobertura y aprovechamiento de fuentes

Fecha: 21/10/2026. Paso 1 de la hoja de ruta. No modifica código ejecutable, configuración, cuotas ni servicios externos.

## Evidencia y alcance

- Código local y `origin/main`: `570926de6a4d5f5e760263354d369fde39ad2a2a`, coincidente con el despliegue observado. Se hizo fetch de main antes de auditar.
- Lectura HTTP 200 del `/health` de Northflank, revisión `tennis-volley-context-v1-budget-fix`.
- Snapshot del último barrido terminado: **21/10/2026 04:37:13 UTC / 01:37:13 Argentina**, barrido 4 desde el inicio de esa instancia. Estado `ok`, persistencia principal declarada Upstash Redis, 100 análisis y 363 eventos únicos normalizados.
- Es una fotografía de un barrido, no un informe de todo el día ni una reconstrucción de todas las alertas anteriores. Una fuente con cero eventos puede estar fuera de temporada, sin próximos partidos, restringida, en caché o sin cobertura. No se calcula porcentaje del deporte mundial cubierto.
- Las rutas integradas y sus límites se verificaron en el código. Los inputs completos de cada evaluación no están publicados por `/health`; por ello no se atribuye a datos insuficientes cada descarte `sin señales`.
- No se usaron claves del usuario ni se consultaron endpoints comerciales deportivos para esta auditoría. La consulta pública de salud no dispara un barrido ni envía Telegram.

## Resultado principal: vóley

| Estado al cerrar el barrido | Encuentros |
|---|---:|
| Detectados como eventos únicos por el agregador | 35 |
| Pendientes por bolsa de búsquedas de identidad (`identity_lookup_budget`) | 14 |
| Pendientes por tope global de análisis (`analysis_queue`) | 14 |
| Pendientes por enfriamiento (`cooldown`) | 2 |
| Evaluados y descartados `sin señales` | 5 |
| Alertas nuevas en este barrido | 0 |

Sólo **5/35 = 14,3 %** de los eventos de vóley encontrados se evaluaron en ese ciclo. Los otros 30 no fueron rechazados por una comparación deportiva: quedaron pendientes. Esto no significa que nunca se hayan evaluado ni que no vayan a rotar en ciclos posteriores.

Los cinco evaluados corresponden a cuatro eventos de Serie A1 italiana y uno de NPVA Division #1 2026/27. Las razones agregadas no permiten saber si cada evaluación carecía de datos o simplemente no mostraba superioridad suficiente.

El código usa un máximo general de 100 análisis por ciclo y una bolsa compartida de 15 búsquedas por nombre por defecto y en el manifiesto. El snapshot alcanzó los 100 análisis. Esa bolsa limita tareas/eventos, no equivale a 15 solicitudes HTTP. La rotación por último intento está activa; el reparto por coste/urgencia/exploración se calcula en sombra y no distribuye efectivamente un presupuesto de análisis por deporte.

## Matriz general de rutas integradas

Los números cuentan fuentes habilitadas por el mapa runtime, incluidas las que sólo aportan contexto; no son cantidad de respaldos por partido. No se suman las filas para contar proveedores distintos. El libro propio de resultados es una derivación de las fuentes, no otro proveedor independiente.

| Deporte | Fuentes habilitadas | Calendario integrado | Historial y comparación aprovechables | Tabla/ranking conectado al motor | Hueco o limitación principal |
|---|---:|---|---|---|---|
| Fútbol | 8 | ESPN, Highlightly, OddsPapi, OpenLigaDB, SportAPI, SportScore, The Odds API, TheSportsDB | ESPN, Highlightly, OpenLigaDB, SportAPI, SportScore; TheSportsDB auxiliar; libro con resultados recogidos de proveedores | ESPN, OpenLigaDB y Highlightly, sujetos a validaciones | Muchas fuentes de calendario no equivalen a profundidad mundial; tablas SportAPI/SportScore no conectadas como vigentes sin temporada verificable |
| Básquet | 8 | ESPN, Highlightly, OddsPapi, SportScore, BBS y BALLDONTLIE WNBA, The Odds API | ESPN, Highlightly, SportScore, BBS/BALLDONTLIE WNBA; TheSportsDB y libro como respaldo | ESPN y Highlightly | BBS/BALLDONTLIE no respaldan ligas internacionales fuera de WNBA |
| Tenis | 5 | WTA, ESPN, SportScore, Tennis API, OddsPapi | Perfiles/historial WTA y complemento Tennis API; el motor de tenis no usa la ruta general de H2H por equipos | WTA oficial y ranking auxiliar verificado Tennis API; ESPN de alcance limitado | Ranking/WC faltante en 88 de 171 eventos; listado incluye observaciones de dobles/SRL que no deben contarse como cobertura válida de individuales reales |
| Hockey sobre hielo | 6 | ESPN NCAA, Highlightly, PWHL, OddsPapi, The Odds API | ESPN, Highlightly, PWHL, TheSportsDB y libro | ESPN y Highlightly | PWHL y NCAA no acreditan ligas femeninas europeas; contexto internacional depende de otras rutas |
| Handball | 4 | Highlightly, OddsPapi, The Odds API | Highlightly, TheSportsDB auxiliar, libro; profundidad OddsPapi condicionada a configuración | Highlightly | Sin segundo conector oficial especializado integrado |
| Vóley | 8 | Highlightly, FIVB, CEV, OddsPapi, The Odds API | Highlightly; FIVB/CEV aislados; LVF Italia y LNV Francia como contexto; TheSportsDB auxiliar y libro en ruta general | Highlightly, FIVB por grupo validado, LVF Serie A1, LNV D1F | Colas, profundidad desigual, aislación de contexto y ausencia de bajas confirmadas |
| Rugby | 4 | World Rugby XV, OddsPapi, The Odds API | World Rugby XV aislado; TheSportsDB/libro para otras rutas cuando estén disponibles | Sin tabla especializada conectada para World Rugby | No hay respaldo equivalente para todos los clubes; XV no significa seven ni rugby league |
| Sóftbol | 1 | ESPN NCAA | Historial ESPN de liga/temporada | ESPN cuando la tabla resulte válida | Dependencia de una única fuente y ámbito NCAA; experimental |
| Lacrosse | 1 | ESPN NCAA femenino | Historial ESPN de liga/temporada | ESPN cuando la tabla resulte válida | Dependencia de una única fuente y ámbito NCAA; experimental |
| Hockey sobre césped | 1 | ESPN NCAA femenino | Historial ESPN de liga/temporada | ESPN cuando la tabla resulte válida | Dependencia de una única fuente y ámbito NCAA; experimental |
| Críquet | 2 | SportScore | Cricsheet, con filtros propios de formato/temporada | Contexto y evaluación específica; sin tabla general conectada | Calendario depende de una fuente; archivo publicado no garantiza actualidad inmediata ni temporada de clubes |

OddsPapi tiene funciones de historial/H2H por participante, pero `ODDSPAPI_PROFUNDIDAD` es 0 por defecto y en el manifiesto. No debe describirse como respaldo completo de H2H sin verificar su activación efectiva. El recolector diario de terminados alimenta el libro, con otra ruta y alcance. The Odds API se usa para calendario y resultados posteriores, no como proveedor directo de tablas/H2H del análisis.

## Calendario observado en el snapshot

| Deporte | Eventos únicos | Fuentes que aportaron calendario |
|---|---:|---|
| Fútbol | 99 | Highlightly, OddsPapi, SportAPI, SportScore |
| Básquet | 54 | ESPN, Highlightly, OddsPapi, SportScore, The Odds API |
| Tenis | 171 | ESPN, OddsPapi, SportScore, Tennis API, WTA |
| Hockey sobre hielo | 2 | Highlightly, OddsPapi |
| Handball | 2 | Highlightly, OddsPapi |
| Vóley | 35 | CEV, FIVB, Highlightly, OddsPapi |
| Rugby | 0 | Ninguna observación normalizada en este ciclo |
| Sóftbol | 0 | Ninguna observación normalizada en este ciclo |
| Lacrosse | 0 | Ninguna observación normalizada en este ciclo |
| Hockey sobre césped | 0 | Ninguna observación normalizada en este ciclo |
| Críquet | 0 | Ninguna observación normalizada en este ciclo |

## Vóley: proveedor por proveedor

| Fuente | Calendario | Historial / H2H | Tabla | Alcance y estado observado |
|---|---|---|---|---|
| Highlightly | Sí; 14 filas normalizadas | Últimos partidos y H2H específico; búsqueda exacta de identidad | Sí, liga/temporada resueltas | 59/100 solicitudes diarias usadas; saldo proveedor observado 41, margen operativo 36 después de reserva |
| FIVB VIS | Sí; 1 evento | Hasta 10 resultados por equipo, últimos 90 días, misma competición; H2H derivado del historial | Grupo oficial reconciliado con resultados | 3/30 usadas del tope interno; 1 tabla verificada, 0 rechazadas en el ciclo |
| CEV | Sí; 2 eventos | Hasta 10 resultados por equipo, últimos 90 días, misma competición/edición | No existe conector de tabla CEV | 2/30 usadas del tope interno; los 2 eventos CEV estaban en enfriamiento |
| LVF | No | Contexto de Serie A1 italiana; detalles y parciales validados | Sí, edición actual | Tabla de 14 equipos, 16 resultados verificados, edición 2026/2027; 17/24 solicitudes internas usadas |
| LNV | No | Contexto D1F francesa; detalles y parciales validados | Sí, edición descubierta | Tabla de 13 equipos, 16 resultados verificados, edición 135; 20/24 solicitudes internas usadas |
| OddsPapi | Sí; 19 filas normalizadas | Funciones de profundidad opcionales; libro de resultados por recolector | No | Los 19 fueron exclusivos de esta fuente en este snapshot; no se puede afirmar que todos sean encuentros distintos de los de otros proveedores sin contrastar identidad/horario |
| The Odds API | Ruta habilitada; 0 eventos | Sin ruta directa de contexto H2H/tabla | No | Catálogo femenino activo condiciona lo que devuelve |
| TheSportsDB | En runtime sólo contexto para vóley | Búsqueda e historial auxiliar | No | Fuente pausada por el planificador; su 429 fue observado en los logs de arranque compartidos |

**No hay ocho respaldos completos para cada partido de vóley.** Tampoco hay fuente integrada de bajas/plantel de vóley: el lector de lesiones ESPN no dispone de slug de vóley y su mapa de deportes no incluye ese deporte. Hay umbral genérico de bajas para vóley, pero carece de alimentación efectiva por esa ruta.

## Hallazgos de aprovechamiento y límites

### 1. Cola de contexto y cola general: impacto confirmado en producción

14 eventos no accedieron a búsquedas y otros 14 quedaron fuera por el máximo general. Entre los primeros hay cinco observaciones OddsPapi de Serie A1 italiana. LVF dispone de contexto cargado, pero `_tiene_historial_propio` no evalúa si un evento puede resolverse con LVF/LNV: sólo reconoce determinadas fuentes de la observación o historial suficiente ya en el libro. Esto puede cargar a la bolsa de búsquedas tareas con respaldo oficial sin coste comercial. No se asegura que esos cinco eventos satisfagan los aliases/competición de LVF: requiere inputs por evento.

### 2. Aislamiento CEV/FIVB: protección con coste de profundidad

`main._historial_equipo` retorna inmediatamente el historial del proveedor principal si `historial_aislado=True`. No recorre `_observaciones` ni LVF/LNV como alternativas. `_tabla_evento` sí prueba LVF/LNV antes, pero estos rechazan copas/internacionales por diseño; FIVB sólo se consulta como tabla si FIVB es la fuente principal. La prioridad CEV (-4) precede a FIVB (-3) y Highlightly (0).

No es correcto arreglarlo mezclando indiscriminadamente ligas nacionales y copas: cualquier respaldo futuro necesita identidad, edición, modalidad y procedencia de evidencia verificadas.

### 3. H2H puede perder un cruce ya descargado

`utilidades.h2h_desde_fuentes` recibe ambos historiales, pero sólo inspecciona el local antes de consultar libro/proveedores. Si el enfrentamiento está exclusivamente en el historial visitante, se pierde cuando no existe respaldo; afecta especialmente rutas aisladas. Reproducción offline confirma este comportamiento. Corregir la unión validada/deduplicada no exige otra API.

### 4. Ocho fuentes no significan contraste simultáneo

La ruta general de historial conserva la muestra más larga y retorna cuando llega a cuatro resultados útiles; no une todos los historiales ni compara simultáneamente todos los proveedores. Eso ahorra requests, pero debe describirse como respaldo/fallback. Las tablas también se eligen por prioridad: no se vota entre proveedores.

### 5. Ventanas y mínimos pueden dejar contexto sin señales

Forma requiere al menos cuatro partidos válidos por lado, tres victorias del favorito y tres derrotas del rival, además de una brecha por deporte. Tabla requiere cinco partidos por equipo y diferencia suficiente de posición/efectividad. H2H exige dos triunfos recientes y proporción al menos 75 %. La tabla aporta dos puntos y se necesitan cuatro para alertar, con evidencia fuerte y sin contradicción suficiente. Una tabla descargada no garantiza emisión.

FIVB exige que la tabla se reconcilie exactamente con el historial del grupo y el inicio del torneo esté a no más de 90 días. CEV/FIVB no usan campañas anteriores para rellenar muestras. Los conectores oficiales conservan parciales donde están validados, pero el motor actual no tiene aún un evaluador específico completo que aproveche todos esos factores.

### 6. Límites de descubrimiento y cobertura observada

Highlightly consulta una página de 100 por fecha por defecto; mezcla géneros antes de filtrar. La variable de ligas femeninas estaba vacía en la captura de migración. Esto es un riesgo de cobertura, pero no hay en este snapshot una medición pública que pruebe truncamiento concreto de vóley: sólo consta truncamiento SportScore fútbol. La instrumentación de Highlightly informa recortes por log, no los agrega a `coverage.truncated_pages`.

Los nombres/aliases exactos y la deduplicación pueden dejar observaciones de un mismo partido separadas. Encontrar Serie A1 en dos proveedores no demuestra que sean los mismos encuentros: hay que contrastar pares y horarios. El contador de eventos únicos sólo representa las identidades reconocidas por el agregador.

### 7. Consumo anticipado de detalles oficiales

LVF/LNV cargan hasta cuatro detalles nuevos por barrido durante recolección, antes de saber qué eventos pasan a la cola efectiva. En cuatro ciclos ambas tenían 16 resultados verificados, pero LNV ya usó 20/24 de su presupuesto local. Es un límite interno, no una cuota publicada del proveedor; conviene orientar el gasto a equipos/eventos pendientes y conservar las validaciones, en vez de elevarlo a ciegas.

### 8. Diario de auditoría al límite

`audit.records_and_evidence=10000`, límite interno alcanzado; `omitted_capacity=1677`, omisiones por capacidad, no necesariamente 1677 partidos únicos. `errors=0`, `pending_writes=0`, `persistence=unknown` para el diario, aunque la persistencia principal sea Upstash. Esto no demuestra fallo de Redis ni bloqueo de alertas; sí limita la captura de evidencia nueva y la futura validación de motores. No se borró ningún registro.

## Comprobaciones reproducibles realizadas

Se ejecutaron cuatro comprobaciones de diagnóstico en memoria con las funciones extraídas por AST del código actual, sin importar main, sin iniciar el bot y sin enviar mensajes:

1. Un historial CEV vacío con aislamiento retorna sin consultar alternativas.
2. Un evento sólo OddsPapi no reconoce LVF como historial propio en el filtro de elegibilidad.
3. Un H2H exclusivamente en historial visitante no se devuelve sin alternativas.
4. El conteo de 35 eventos se reconcilia con 5 evaluados y 30 pendientes en el snapshot.

No se escribieron pruebas permanentes ni se ejecutó un barrido local completo: sería innecesario para una auditoría y podría confundir el estado operativo o gastar cuota. No se modificaron umbrales ni se implementaron los cambios propuestos.

## Prioridad que deja esta auditoría para el paso siguiente

1. Aprovechamiento: resolver identidad y fuentes oficiales ya disponibles antes de cargar la bolsa de búsquedas; evitar que el volumen total deje un deporte sin turno suficiente, sin sobrepasar cuotas.
2. Corregir recuperación simétrica del H2H ya descargado; registrar muestras, fuente real de cada input y razones de carencia por evento.
3. Revisar capacidad del diario antes de usarlo para calibrar nuevos motores, sin destruir el historial.
4. Búsqueda de fuentes internacionales orientada a huecos: tablas y resultados de CEV, ligas nacionales de vóley fuera de Italia/Francia, nombres/IDs verificables y planteles. Otro calendario sin historial no sustituye esos datos.
5. En el resto: profundizar ITF y ranking verificable; respaldo especializado para handball/rugby; extensión internacional de básquet/hockey fuera de WNBA/PWHL/NCAA; segunda fuente sólo donde aporte valor en ramas experimentales.

Para reconstruir la causa exacta de cada descarte se requieren los snapshots de inputs del diario o logs completos del barrido; el endpoint público permite el diagnóstico agregado, no la comparación completa de cada pareja. No hace falta entregar claves al chat para continuar.

## Referencias de implementación

- `main.py`: `_recolectar_eventos`, `_historial_equipo`, `_tabla_evento`, `_tiene_historial_propio`, `_procesar_evento`, `ejecutar_barrido_radar`.
- `mapa_fuentes.py`, `cobertura_radar.py`, `planificador_datos.py`, `auditoria_decisiones.py`.
- `utilidades.py`: `historial_desde_fuentes`, `h2h_desde_fuentes`, `tabla_desde_fuentes`.
- `fuente_fivb.py`, `fuente_cev.py`, `fuente_lvf.py`, `fuente_lnv.py`, `voley_oficial.py`, `fuente_highlightly.py`.
- `fuente_espn.py`, `fuente_oddspapi.py`, `fuente_theoddsapi.py`, `libro_resultados.py`, `motor_mismatches.py`.

Los nombres anteriores remiten al commit auditado, no a promesas generales de cobertura de los proveedores.
