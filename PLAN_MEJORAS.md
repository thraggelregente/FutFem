# Investigación y especificación de las cinco mejoras

Fecha: 14/10/2026. Estado histórico: **propuesta original previa a implementación**. La implementación autorizada posterior y sus límites actuales están en [OPERACION_EVALUACION.md](OPERACION_EVALUACION.md). Esta revisión sólo despliega mejoras de presentación/entrega de mensajes. No activa auditoría, recopilación posterior de resultados, calibración, reparto nuevo de cuota ni recomendaciones de apuestas.

## Hallazgos del proyecto actual

- `main.py` registra contadores por fuente/deporte del último barrido y claves de alertas entregadas. No persiste la decisión completa ni los motivos de todos los descartes. `alertas` cuenta alertas generadas, incluso si Telegram falla; no equivale a entregas.
- `libro_resultados.py` conserva filas de ocho campos: timestamp, deporte, firmas/nombres de equipos y puntos. No conserva fuente, competición, temporada, formato, precisión ni estado de finalización. No sirve como registro universal de resultados para evaluar alertas, y una pareja/día puede representar más de un partido. Conservar sus usos actuales mientras se crea el esquema nuevo, sin migrar los resultados antiguos como si tuvieran metadatos verificados.
- En la comprobación pública de producción, el servicio estaba `ok`, con 219 eventos únicos, 36 evaluaciones en el último barrido y 747 resultados en el libro. **219 menos 36 no significa 183 partidos sin datos**: hay ya enviados, enfriados, cola y otros filtros. Tampoco son 747 alertas evaluables.
- Highlightly básquet/handball/vóley estaba en 95/100 (cinco reservadas); SportScore tenía 8.602 solicitudes disponibles según el contador móvil local y SportAPI 1.960 según el contador diario local. Son snapshots, no saldos permanentes. Algunos valores son límites operativos nuestros, no cuotas anunciadas por proveedores.
- WTA devuelve historial con precisión de semana de torneo; no acredita días exactos de descanso/viaje. Su parser actual reduce el marcador a juegos agregados y descarta retiros/walkovers. Para evaluar sets/partidos exactos hay que conservar también el marcador original y el estado.
- `_upstash()` actualmente interpreta un HTTP exitoso como éxito aunque el JSON pueda contener `error`. El fallback a archivo no prueba persistencia durable en Render Free. Estos puntos deben resolverse antes de considerar íntegro un diario de evaluación; **no se modificaron en esta entrega**.
- Las fuentes coincidentes no necesariamente son independientes. No se deducirá el origen de un feed a partir de logos o nombres de dominio de imágenes.

## 1. Cobertura real por competición

Objetivo: distinguir falta de calendario, falta de datos, retraso de cola, límite de cuota, errores e identidad ambigua.

Desarrollo propuesto: `cobertura_radar.py`, hooks en `_recolectar_eventos()`, filtros y `_procesar_evento()`. Resumen público acotado en `/health`, agregados diarios/semanales en Redis y un comando de consulta del bot, sin envío automático de reportes hasta definirlo.

Grano: competición/temporada/categoría/modalidad + deporte + origen. Cuando falte un identificador verificable, marcar `unknown`, no inventar temporada ni fusionar ligas por parecido. Historial separado para clubes y selecciones; formatos T20/ODI, rugby XV y categorías juveniles distintos.

Contadores propuestos:

| Campo | Significado |
|---|---|
| Observaciones | Filas observadas por fuente, antes de deduplicar |
| Eventos únicos | Partidos normalizados y deduplicados dentro del alcance consultado |
| Evaluables / parciales | Datos suficientes o faltantes, por familia de señal |
| Candidatos / alertas generadas / entregadas | Estados separados; entregas completas por destino |
| Pendientes | Cola, falta de horario, índices aún cargando o reintentos |
| Descartes | Razón exacta: género, categoría, identidad, fecha, datos, contradicción, umbral |
| Truncamiento | Página al límite, paginación incompleta o filtro ignorado |
| Coste | Requests reales, créditos, cache hits, pausas y saldo observado con fecha |

Una ausencia se reporta como «sin eventos en las fuentes consultadas», no «esa liga no tiene partidos». La cobertura porcentual sólo se calcula si existe un calendario de referencia contrastado, con un denominador explícito. Rendimiento marginal de una fuente: eventos exclusivos **evaluables**, datos faltantes completados y correcciones verificadas, no sólo volumen de respuestas 200.

Criterios de aceptación: mismo partido en tres feeds = tres observaciones y un evento; 200 vacío y 429 se distinguen; la suma de razones no duplica descartes; un partido puede pasar de parcial a evaluable; completar una alerta en un destino no implica entrega completa en todos.

## 2. Diario previo al partido

Objetivo: poder explicar y reproducir una decisión con la información que efectivamente teníamos antes del inicio.

Desarrollo propuesto: `auditoria_decisiones.py`, almacenamiento separado de `RegistroVistos`, callbacks en agregación, filtro, evaluación y entrega. Modificación controlada de la capa Upstash para reconocer errores JSON, idempotencia y estado de persistencia. No modificar los umbrales en esta fase.

Contrato previsto `DecisionSnapshotV1`:

```json
{
  "schema_version": 1,
  "event_key": "identidad verificable del encuentro",
  "revision_motor": "commit o versión de reglas",
  "observed_at_utc": "instante de captura",
  "kickoff_utc": "inicio conocido en ese instante",
  "kickoff_precision": "exact|estimated|date|tournament_week|unknown",
  "sport": "Tennis",
  "competition_id": "id o unknown",
  "season": "edición verificada o unknown",
  "category": "senior_women",
  "format": "individuales; formato conocido o unknown",
  "participants": [],
  "provider_observations": [],
  "history_snapshot_refs": [],
  "signals": [],
  "score": null,
  "favoured_participant_id": null,
  "decision": "candidate|alert|discard|pending|unevaluable",
  "reason_codes": [],
  "data_quality": {},
  "persistence": "durable|volatile|failed"
}
```

Cada observación identifica proveedor, familia de endpoint, ID original, fecha de descarga, vigencia conocida y metadatos de caché. IDs de fixtures, archivos y servicios en vivo no son intercambiables. Cada señal guarda sus partidos de apoyo y valores: forma, H2H y Elo pueden compartir esos mismos resultados. Datos ausentes = `null`/razón explícita, nunca cero.

Snapshots inmutables: guardar primera evaluación y cambios materiales de datos/decisión, evitando reescribir un registro cada 15 minutos. Capturar también descartes antes del motor, errores y pendientes; priorizar candidatos/alertas si el límite de almacenamiento obliga a muestrear descartes. Cualquier muestreo guarda su regla y probabilidad de inclusión para no analizar una selección sesgada como si fuera todo el universo.

No mezclar hechos posteriores con información previa. Un histórico descargado hoy puede servir para contexto de una alerta futura; no demuestra que estuviera disponible antes de una alerta pasada. Fijar snapshot de historial/rankings y no recalcular un pronóstico anterior con el estado actual de Redis. Una corrección posterior genera versión nueva, no reemplaza la decisión original.

Persistencia: claves con namespace/version propios, TTL real, índice por fecha, paquetes de evidencia comprimidos y deduplicados. No guardar tokens, cabeceras de autorización, cuotas ni IDs privados de chat en los datos deportivos. Inspeccionar errores individuales en respuestas de pipeline/transacción; una transacción Redis no garantiza rollback de todos los errores de ejecución. Fallo del diario no debe detener las alertas, pero debe dejar visible que la muestra está incompleta.

Capacidad propuesta para ajustar con el panel real: límite conjunto inicial de 100 MB y 10.000 snapshots compactos, TTL inicial 90 días; evidencia compartida dentro del mismo límite. Contar bytes reales y comandos, no sólo objetos. Cota de trabajo adicional 90.000 comandos/mes, sujeta al consumo existente y al plan confirmado; no es autorización para superar Free. Reducir muestreo/retención si no hay margen.

Upstash publica Free con 250 MB, 500K comandos/mes y 10 GB de transferencia/mes; el panel de la cuenta es la referencia definitiva. Una petición HTTP con pipeline puede contener varios comandos: ahorrar round-trips no convierte todo el lote en una única unidad de consumo. Evitar reescribir un JSON histórico gigante en cada ciclo.

Criterios de aceptación: captura antes del kickoff, snapshot original inalterado después de corregir el resultado, datos incompletos visibles, reintentos idempotentes, errores JSON con HTTP 200 rechazados y presupuesto de almacenamiento respetado.

## 3. Resultados y evaluación deportiva

Objetivo: distinguir victoria, magnitud de superioridad, sorpresa y ausencia de resultado verificable. No medir rentabilidad de apuestas sin precio ni reglas del mercado.

Desarrollo propuesto: `resultados_evaluacion.py` y un índice de resultados versionado separado del libro actual. Reutilizar primero caches/feed agrupados existentes; consultas nuevas sólo para pendientes concretos y dentro de presupuesto. No una llamada por cada candidato si el feed del día resuelve varios.

Contrato `OutcomeV1`: ID compuesto, IDs de proveedor y origen, competición/temporada/formato/categoría, inicio real, orientación original, marcador original, resultado normalizado, estado final explícito, overtime/penalties/retirement/DLS si están disponibles, fecha de verificación, correcciones y conflictos. Vincular por identidad exacta; cuando falten IDs exigir pareja, competición, categoría, fecha/horario y ronda verificables. Emparejamientos ambiguos quedan pendientes. Dobles jornadas no se colapsan.

Primer reintento desde el siguiente barrido posterior a una hora esperada de finalización; luego backoff y consultas agrupadas. Usar 2 h/6 h/24 h/72 h como candidatos de programación, ajustados a formato/estado y duración observada, no como garantía de que el partido ya terminó. Si un proveedor sólo ofrece resultados de tres días, consultarlo antes de vencer esa ventana. Después, mantener `unresolved` o usar un archivo autorizado, no inventar derrota.

Etiquetas separadas:

| Deporte | Qué conservar / evaluar |
|---|---|
| Fútbol, handball, básquet y hockey | Ganadora y margen; tiempo reglamentario vs extra/penaltis si se conocen |
| Tenis | Sets, juegos por set, desempates y ganador; retiro/walkover separados. Un 2-0 no implica necesariamente dominio amplio |
| Vóley | Sets; puntos por set sólo cuando se dispone de ellos. Un 3-0 ajustado no se convierte en gran margen de puntos |
| Cricket | T20/ODI separados; ganador y margen oficial por runs o wickets, sin mezclar unidades; DLS/no-result/super-over aparte |
| Nuevos deportes experimentales | Sólo etiquetas compatibles con el formato conocido; sin trasladar reglas de otro deporte |

La definición de «dominio amplio» se versiona por deporte antes de medir, inicialmente exploratoria; no elegir el umbral después de conocer cada resultado. Métricas: proporción de alertas con resultado resuelto, victoria del lado señalado, distribución de márgenes, dominio según definición, sorpresas, cobertura perdida y motivos de descartes que terminaron siendo interesantes. Mostrar denominadores y límites de muestra. Comparar alertas con candidatos/descartes de calidad comparable, no sólo partidos ganados.

Fuentes de partida: WTA oficial para tenis disponible; SportScore fixtures/resultados y detalle exacto; feeds oficiales FIVB/CEV/PWHL/World Rugby/OpenLigaDB; ESPN por competición; SportAPI y BALLDONTLIE para su cobertura; Cricsheet para cricket. La demora de publicación y la cobertura incompleta de Cricsheet se mantienen visibles. The Odds API `/scores?daysFrom=...` cuesta dos créditos y tiene una ventana reciente; no se convierte en un recolector ilimitado. El feed OddsPapi observado sin marcadores no certifica resultados.

Criterios de aceptación: lado visitante ganador correctamente orientado, penalti/retirada separado de final normal, pareja repetida el mismo día distinguida, conflicto entre resultados no resuelto por mayoría ciega, dato tardío no altera el snapshot previo.

## 4. Ajuste del motor por deporte

Objetivo: comprobar qué reglas funcionan fuera de la muestra utilizada para ajustarlas. El puntaje actual es heurístico: no equivale a una probabilidad ni justifica una apuesta.

Desarrollo propuesto: evaluador offline `evaluacion_motor.py`, configuraciones versionadas por deporte y modo sombra para reglas candidatas. El análisis pesado se ejecuta bajo demanda fuera del loop de Render; primero registro/evaluación, luego cambios de producción revisables. No instalar librerías de aprendizaje automático en el bot por adelantado.

Datos: entrenamiento en periodos anteriores, validación temporal separada y prueba final posterior sin reutilizarla para escoger umbrales. Nuestros eventos no están igualmente espaciados: usar bloques de calendario y agrupar torneos/semanas; no aplicar sin más un split por número de filas. Incluir gap cuando la ventana de features o los resultados pendientes atraviesen la frontera. Rankings, forma y ratings deben ser los conocidos en el instante de predicción; recalcular Elo cronológicamente por competición/categoría compatible.

No usar los 747 resultados compactos como si fueran 747 decisiones prepartido guardadas. Backtests reconstruidos con límites desconocidos de publicación se etiquetan exploratorios; la validación prospectiva nace del diario nuevo. Evaluar sensibilidad, estabilidad entre periodos, errores de identidad, intervalos de incertidumbre y cobertura además de la tasa de victorias. Comparar contra un baseline simple de ranking/Elo con el mismo universo de partidos.

Cambios específicos candidatos:

- **Tenis prioritario**: distinguir WC, entrada clasificatoria y regreso con ranking protegido; WC no suma debilidad por sí misma. Comparar experiencia registrada, nivel WTA/ITF, actividad reciente y rivales comparables; confirmar que el ranking de la rival corresponde al momento del partido. Superficie con fuente/edición verificadas, conservando indoor/outdoor cuando la fuente lo declara. Reducir apoyo duplicado de forma y superficie. Ausencia de registro nunca implica condición amateur. Evaluar si la selección inicial por ranking/WC está excluyendo asimetrías documentadas.
- **Equipos**: probar diferencia de forma y muestra por deporte, calidad de rivales comunes y estabilidad de Elo con muestras pequeñas. Separar competición/temporada/formato; las señales de descanso/congestión requieren calendario con cobertura suficiente, no inferir descanso desde un historial truncado.
- **Cricket**: probar por separado umbrales T20 y ODI, carreras/wickets, reciente actividad y H2H. Clubes siguen fuera de alertas hasta verificar temporada. No quitar esa barrera para aumentar el número de mensajes.
- **Fuentes**: registrar procedencia conocida/independencia desconocida. Dos feeds coincidentes no proporcionan automáticamente dos pruebas independientes.

Métricas iniciales son deportivas descriptivas, no probabilidades. Si más adelante se necesita un modelo probabilístico, será una tarea distinta: calibración en datos separados, curvas de fiabilidad, Brier/log-loss con denominadores y evaluación fuera de muestra. Un Brier menor por sí solo no demuestra mejor calibración.

Criterios de aceptación: evaluación reproduce exactamente una versión/snapshot, uso de datos futuros hace fallar una prueba, comparación con baseline y periodos posteriores, cambio de reglas sólo tras informe de impacto en cobertura y errores; rollback por configuración.

### Fuente opcional identificada para tenis: Tennis API – ATP WTA ITF

Documentación del proveedor anuncia FREE con 50 requests/día y 4/segundo; Free y Pro comparten payload factual salvo excepciones de productos predictivos premium. La página de cobertura anuncia hard limit en Free. **Sin suscripción autenticada, no se comprobó profundidad real, actualización, cobertura ITF completa ni campos de retiro/WC para casos concretos.** Registro web no prueba acceso gratuito de todos los datos anunciados: contrastar panel y headers de la cuenta.

Producto correcto: https://rapidapi.com/jjrm365-kIFr3Nx_odV/api/tennis-api-atp-wta-itf . Host `tennis-api-atp-wta-itf.p.rapidapi.com`. Variable futura propuesta `TENNIS_API_RAPIDAPI_KEY`, **sin conector ni cambios de entorno en esta entrega**. Suscribirse a FREE; confirmar 50/día y hard limit en el panel. Guardar clave en Render, no en chat ni repositorio. No reutilizar credenciales de otro proveedor sin comprobar producto/suscripción.

Rutas factuales previstas:

- `/tennis/v2/wta/fixtures/{date}`: `filter=PlayerGroup:singles`, incluir torneo/cancha/ronda y paginar según `hasNextPage` (máximo documentado 500 filas/página). `wta` incluye femenino de niveles inferiores donde se cubren; no existe `type=itf`. Validar edición, individuales, hora UTC y no iniciado. Nunca usar player1 como ganadora en fixtures.
- `/tennis/v2/wta/player/past-matches/{id}`: filtros de años/grupo individual, torneo/cancha/estadísticas cuando se disponga; player1 es la ganadora en resultados. No asumir que ID de archivo, fixture y live son el mismo.
- Resultados por fecha/torneo para evaluar decisiones pendientes; datos de superficie y seed WC/Q como observaciones de esa fuente. Una etiqueta WC informada por tercero no se presenta como confirmación del cuadro oficial sin corroboración.

No usar feeds enriquecidos de predicciones ni rutas de odds. Algunos endpoints factuales pueden incluir campos de cuotas: lista permitida de campos, descartar esos campos antes de persistir. El H2H de carrera no se usa como H2H reciente sin fechas. Marcadores de retiros/incompletos y códigos deben comprobarse antes de puntuarlos.

Presupuesto piloto propuesto, dentro del hard limit: hasta 8 llamadas agrupadas de calendario/día, 8 de resultados, 26 de contexto seleccionado y 8 disponibles para paginación/validaciones. Son llamadas, no 26 perfiles completos. La asignación se puede redistribuir con demanda real, nunca superar 50. Hora de reinicio: confirmar con headers/panel, no inferir medianoche UTC. Identidades positivas cacheadas y negativos acotados; probar profundidad temporal con pocas jugadoras conocidas y casos ITF antes de ampliar.

Requisito del usuario: una suscripción Free para **validar esta fuente opcional**. No es un bloqueo para desarrollar cobertura, diario y evaluación con las fuentes existentes.

## 5. Reparto útil de requests gratuitos

Objetivo: aprovechar el cupo disponible obteniendo datos útiles, manteniendo límites reales y recuperación ante fallos.

Desarrollo propuesto: `planificador_datos.py`, instrumentación de caches/contadores y adaptadores que declaren capacidades por deporte/competición. Piloto en modo sombra; luego activar por fuente compatible. No cambia cuotas durante la fase de observación.

Cada tarea declara: recurso/endpoint, evento y competición, información faltante, coste en requests o créditos, caché vigente, plazo útil, estado de identidad y presupuesto compartido. Prioridad por cercanía del partido, información que puede resolver la evaluación, cobertura nueva verificable y coste. No sólo por puntaje alto: dejar parte del trabajo para casos desconocidos/ITF y evitar sesgo de selección. Reservar resultados pendientes y validar posibles nuevos partidos antes de repetir historiales cacheados.

Ventanas independientes: cuota diaria real por host, semana/mes cuando existan, móvil 24 h de SportScore, rate limit por minuto de BALLDONTLIE, y límites propios para endpoints públicos sin cuota contractual. WTA 100/día es una política operativa nuestra, no una garantía de un plan gratuito publicado. Las llamadas gratis en créditos siguen consumiendo ancho de banda y límites de tráfico. Headers, fecha de observación y reinicio conocido acompañan el saldo; no sumar presupuestos por deporte si el proveedor comparte host/IP.

Ejemplo de oportunidad comprobada: trasladar calendario/contexto compatible de Highlightly agotado hacia SportScore/SportAPI cuando identidad y competición estén verificadas. SportScore limita a 200 filas por consulta sin paginación documentada: usar filtro `competition` con slug verificado para ligas femeninas que queden fuera, en lugar de repetir el feed global truncado. No elegir slug por aproximación ni asumir equivalencia de toda la cobertura.

Cache adaptativa: refresh de calendario según plazo del encuentro; rankings según publicación verificada; historial final cuando haya un nuevo resultado; negatividad temporal según causa (identidad ambigua, 404, plan restringido). 401/403/429/suspensión detienen o pausan tareas; no evadir restricciones. Aprovechar saldo próximo a reinicio en trabajos con valor medible, no en duplicados.

Criterios de aceptación: dos deportes de SportScore comparten un presupuesto; scores de The Odds API descuentan créditos según respuesta; saldo real bajo prevalece sobre contador local; reintento concurrente no consume por duplicado; trabajo vencido se cancela; comparar requests por evento evaluable antes/después y cobertura de ligas pequeñas.

## Recomendaciones de apuestas: requisitos separados

La única implementación actual es el encabezado y estado «Pendientes de evaluación». Para generar recomendaciones hace falta:

1. Definir mercado y formato: ganador en tiempo reglamentario, ganador incluyendo extra, ganador del partido de tenis, hándicap de goles/juegos/sets o resultado exacto son objetivos diferentes.
2. Resultado compatible para medir ese mercado. No se puede evaluar un hándicap de juegos con sólo sets, ni reglamentario con un marcador que incluye extra sin desglose.
3. Reglas de liquidación de la plataforma: retiros, walkovers, aplazamientos, extra, anulaciones y push pueden variar. Eso requiere las reglas concretas del mercado elegido, no suposiciones universales.
4. Precio/línea/hora realmente disponibles al emitir la recomendación, si se pretende valorar conveniencia económica. Ganar con frecuencia no demuestra rentabilidad. Por ahora no se consulta ninguna API de cuotas; una futura entrada manual de esos datos sería una opción a definir.
5. Evaluación prospectiva y/o temporal adecuada para ese mercado, incertidumbre y opción «sin recomendación». El puntaje heurístico y el Elo actual no son una probabilidad calibrada.
6. Identificación de recomendaciones que dependen del mismo desenlace. Ganador y 2-0 de la misma tenista no son dos oportunidades independientes; no proponer combinadas automáticamente.

Sin precio se puede describir el mercado que merece evaluación deportiva; no se presenta como apuesta rentable. La implementación futura de mercados/probabilidades es un cambio de alcance aparte del radar factual y de estas cinco mejoras. No se definió tamaño de apuesta ni ejecución automática.

## Secuencia de implementación y necesidades del operador

1. Integridad de persistencia, identidad y observabilidad de coste; después cobertura y diario, inicialmente sin tocar puntuación.
2. Recolector de resultados y métricas descriptivas, con estados pendientes/conflictos.
3. Evaluación offline y reglas candidatas en sombra, comenzando por tenis/cricket.
4. Planificador en sombra; activar gradualmente con comparación antes/después.
5. Decidir mercados/recomendaciones tras resultados verificables, no como consecuencia automática del nuevo texto.

No se requiere otra base de datos ni una key nueva para empezar las cinco mejoras. Hace falta confirmar en el panel existente de Upstash: plan, comandos del mes, almacenamiento y transferencia. La clave Tennis API es opcional para probar profundidad ITF. Producción ya muestra BALLDONTLIE configurado y consumo, pero eso por sí solo no verifica toda su cobertura/autorización; no se solicita una segunda key innecesariamente.

Preservar el comportamiento actual con flags apagados por defecto; cambios de datos en namespaces nuevos y lecturas de compatibilidad, sin borrar Redis ni reiniciar cuotas. Documentar versión desplegada y rollback. Pruebas offline para cada criterio; pequeñas consultas reales agrupadas sólo tras habilitar la fase correspondiente. Esta propuesta no instala ni ejecuta ninguna de esas fases.

## Fuentes primarias revisadas

- Upstash planes: https://upstash.com/pricing/redis y https://upstash.com/docs/redis/overall/billing
- REST, errores, pipelines/transacciones: https://upstash.com/docs/redis/features/restapi
- Métricas de cuenta: https://upstash.com/docs/redis/howto/metrics-and-charts
- Validación temporal y requisito de muestras igualmente espaciadas: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
- Calibración y límites de Brier: https://scikit-learn.org/stable/modules/calibration.html
- SportScore: https://sportscore.com/developers/ y https://sportscore.com/developers/openapi.yaml (descarga directa YAML comprobada 200, filtros de competición/equipo y límite 200)
- Cricket, estados y unidades: https://cricsheet.org/format/json/
- The Odds API scores/créditos: https://the-odds-api.com/liveapi/guides/v4/
- BALLDONTLIE WNBA Free: https://wnba.balldontlie.io/
- Tennis API Free y autenticación: https://docs.tennis-api.com/getting-started ; https://tennis-api.com/api-coverage/
- Contratos factuales: https://docs.tennis-api.com/fixtures ; https://docs.tennis-api.com/players ; https://docs.tennis-api.com/results ; https://docs.tennis-api.com/tournaments
- Reglas deportivas de tenis: https://www.itftennis.com/en/about-us/governance/rules-and-regulations/ (no equivalen a reglas de liquidación de una apuesta)

Estas son especificaciones técnicas propias basadas en la revisión del código y documentación; las cifras de capacidad/asignación son propuestas iniciales, no límites nuevos implementados ni rendimiento validado.
