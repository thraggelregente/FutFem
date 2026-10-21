# Pack de aprovechamiento de proveedores

Revisión de producción: `provider-utilization-v1`. Implementado el 21/10/2026.

## Cuotas y calendario

SportsAPI.app mantiene una sola bolsa de 100 solicitudes/día UTC para los siete deportes y el límite existente de 40 consultas de descubrimiento. No aumenta ninguna cuota. Ahora libera hasta 12 consultas al comenzar el día y el resto gradualmente: 57 a las 12:00 UTC y 100 desde las 23:00 UTC. El descubrimiento comienza con seis y libera las 40 con la misma pauta. El saldo no usado se puede recuperar más tarde; no se prometen 100 solicitudes si no hay demanda útil.

El control usa los contadores persistidos anteriores. Un reinicio o despliegue no vuelve a otorgar saldo. Si el despliegue encuentra 90 solicitudes ya gastadas, las siguientes esperan a que el calendario de liberación alcance ese consumo; las 40 consultas de descubrimiento previamente gastadas siguen gastadas hasta el día siguiente.

Se rota el deporte inicial cada 15 minutos. Para cada deporte/fecha se refresca primero la página inicial cuando lleva seis horas sin actualizarse, antes de continuar páginas profundas. La última página válida puede reutilizarse durante un máximo de 24 horas, siempre filtrando nuevamente horario, estado prepartido y participantes. Fallos de refresco conservan esa página dentro del límite y esperan una hora; una respuesta de autorización rechazada detiene el conector. Se conserva el límite de ritmo de diez solicitudes por minuto.

## Contexto y reevaluación

Un evento marcado con historial aislado puede utilizar otra observación verificada del mismo encuentro. Se exige deporte, participantes, categoría/modalidad, horario compatible y nombre normalizado de competición. Los IDs de temporada de proveedores distintos no se comparan como si fueran años; las etiquetas de temporada explícitas sí deben concordar. Si la equivalencia no se puede acreditar, no se utiliza ese respaldo. No se concatenan muestras de dos proveedores para aumentar artificialmente el historial: se selecciona el historial suficiente y se remapean ambos participantes.

El enfriamiento se abre una vez cuando cambian fuentes observadas, rankings/entradas o contexto oficial relevante. Cambiar el orden de las observaciones o un timestamp de descarga no constituye evidencia nueva. Las alertas ya entregadas mantienen su deduplicación.

LVF/LNV conservan el último contexto validado ante indisponibilidad, como máximo 48 horas desde la última validación, con persistencia para reinicios. Los parsers continúan rechazando documentos incompatibles, temporadas viejas, ediciones ambiguas o nuevas ediciones sin validar. Un fallo de detalle no borra parciales ya verificados; deben seguir coincidiendo con la matriz vigente. La caché normal de descarga sigue siendo de seis horas: el límite de respaldo no garantiza información en vivo. Un despliegue sin snapshot previo necesita una primera descarga válida.

## Seguimiento y evaluación

El seguimiento mantiene hasta 1.000 eventos activos, con 200 plazas reservadas para alertas. Los resueltos salen tras la ventana de correcciones de 72 horas y al menos seis horas desde su primera resolución. Los pendientes/conflictos sin resolución durante 30 días caducan. Se conservan recuentos agregados por deporte/día durante 90 días; el diario conserva sus resultados y evidencia con su retención existente. Esto no crea una base histórica permanente.

Al migrar un seguimiento lleno, una alerta nueva puede sustituir un pendiente no alertado; se publica un contador de esas sustituciones. Ningún evento alertado se expulsa para incorporar un descarte. Los intentos omitidos por capacidad también se contabilizan. No se reinicia el seguimiento previo.

La primera alerta registrada conserva su favorito y decisión aunque haya análisis posteriores. El evaluador offline aplica la misma selección. Los resultados por ID (SportsAPI.app y oficiales nacionales) se consultan por evento; las fuentes por jornada mantienen consultas agrupadas. SportsAPI.app tiene un máximo de ocho intentos por evento/ciclo dentro de su cuota compartida, priorizando alertas y rotando los menos comprobados.

Las discrepancias entre fuentes se conservan aunque una fuente no responda en el siguiente ciclo. Los conflictos sin resolver y los resultados especiales no se convierten en derrotas. El porcentaje de victorias queda nulo si no hay alertas normales resueltas con favorito; el intervalo Wilson offline usa sólo ese denominador. Ganar y demostrar dominio deportivo siguen siendo métricas distintas, con las definiciones existentes. No se cambian señales ni umbrales ni se proclama precisión validada.

## Métricas y optimización

`budgets.sportsapi_app` distingue intentos HTTP, respuestas desde caché, aplazamientos por ritmo, validaciones repetidas y eventos/resultados/tablas únicos observados en esta ejecución. Los conjuntos únicos tienen una cota de 5.000 elementos y no equivalen a cobertura mundial. `data_planner` separa contadores HTTP de cache hits del barrido. `outcome_evaluation.states` describe sólo seguimiento activo; `sports` incluye los recuentos agregados todavía retenidos.

Se centralizó el registro de conectores de historial; se evitan llamadas redundantes a la ruta genérica antes del conector específico. La comparación de resultados se indexa primero por deporte y participantes, manteniendo luego las verificaciones completas de identidad. El enfriamiento se persiste una vez por barrido y los snapshots oficiales sólo se escriben cuando cambia su contenido o al renovar su checkpoint horario.

Validación: 217 pruebas offline, compilación Python y revisión de espacios del diff. No requiere nuevas claves ni dependencias. Las pruebas no consultan proveedores ni envían Telegram.

Para revertir, desplegar el commit previo `a25137a7818df47bd98a4a479b6282994d7588b5`. No borrar claves de Redis ni reiniciar contadores de proveedores. Los campos nuevos del seguimiento son aditivos; los resúmenes agregados no reconstruyen eventos retirados en una versión anterior.
