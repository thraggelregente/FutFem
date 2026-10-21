# Diario, cobertura y evaluación del radar

Implementado el 14/10/2026. Revisión de producción: `radar-evaluation-v2`.

## Qué está funcionando

1. Cobertura de los feeds normalizados por deporte, competición, edición conocida, categoría y modalidad. Se diferencian observaciones, eventos únicos, última razón de decisión, cola, enfriamiento y entrega completa por destino. `/health` publica `coverage` y `source_capabilities`. Una respuesta vacía no demuestra ausencia de partidos. `cobertura_diaria_v1.json` conserva 35 días: máximo de eventos por barrido, evaluaciones (pueden repetir un partido), solicitudes y entregas. No publica un porcentaje ficticio de cobertura mundial.
2. Diario prepartido inmutable, snapshots de entradas y salidas, evidencia compartida por hash, primera decisión y cambios materiales. Reconoce errores JSON de Redis y errores individuales de pipeline. TTL 90 días; hasta 10.000 objetos entre decisiones, resultados y evidencia, 100 MB comprimidos, 90.000 comandos adicionales/mes y aproximadamente 3 GB de transferencia/mes. Un fallo del diario no interrumpe las alertas; su estado `durable`, `volatile` o `failed` se publica. Un archivo local sólo es durable si el operador acredita almacenamiento persistente con `DATA_DIR_DURABLE=1`; Upstash es la opción existente en Render Free. No se borran ni migran los datos anteriores como si fueran pronósticos.
3. Seguimiento de hasta 1.000 encuentros evaluados, resultados con versiones y conflictos, reintentos espaciados, agrupación hasta ocho consultas lógicas por ciclo y retención de 90 días. Las consultas lógicas pueden tener varias peticiones/páginas; cada adaptador mantiene sus límites. Se reutilizan listados FIVB, CEV, PWHL, World Rugby y Big Balls. ESPN, SportScore, SportAPI, OpenLigaDB y BALLDONTLIE consultan fechas/ligas pertinentes con caché y presupuesto existentes. Cricsheet conserva su demora y precisión diaria. Tennis API es opcional. Emparejamientos sin identidad/contexto suficientes permanecen pendientes; se requiere coincidencia inequívoca, no simplemente nombres parecidos. Los estados especiales no se cuentan como derrota. Vóley diferencia sets de puntos. El alcance temporal del marcador puede ser desconocido: estas métricas no liquidan mercados de apuestas.
4. Evaluador offline reproducible: exporta snapshots, verifica datos conocidos antes del inicio, vuelve a ejecutar el motor con entradas congeladas, agrupa en bloques de calendario, aplica gap y muestra entrenamiento previo elegible según cuándo se confirmó cada resultado. Comparación descriptiva de reglas actuales/candidatas y baseline de ranking/Elo cuando existe. Intervalos Wilson con denominadores. **No hay entrenamiento automático ni precisión validada todavía**: el diario empieza ahora. Las reglas candidatas están en sombra; no se publican nuevos umbrales sin evidencia. Los denominadores de reglas y baseline pueden diferir y se muestran por separado.
5. Planificador integrado: rotación activa de eventos pendientes, límites compartidos por fuente, pausas ante 401/403/429, contadores HTTP y cache hits. Calcula en sombra asignaciones por urgencia, información faltante, coste y 20% de exploración. El coste declarado en esa simulación es una unidad de tarea de contexto, no una garantía de que un perfil cueste una sola petición. No ejecuta automáticamente esas nuevas asignaciones ni eleva cuotas: hacen falta datos de rendimiento para activar un reparto distinto. No usa una liga o slug inventado para rellenar un feed truncado; ese truncamiento queda visible.

Se evita emitir una alerta si el partido comenzó mientras se descargaban sus datos. Las recomendaciones de apuestas continúan pendientes: este cambio no incorpora precios, probabilidades calibradas ni mercados.

## Consulta y evaluación

`/health` ofrece los contadores de cobertura, auditoría, resultados y planificación. No se incorpora un receptor de comandos Telegram ni reportes automáticos adicionales.

En un entorno con acceso autorizado al Redis del bot:

```bash
python evaluacion_motor.py --export /tmp/radar-export.jsonl
python evaluacion_motor.py --input /tmp/radar-export.jsonl --block-days 28 --gap-days 7
```

La exportación consume lecturas de Redis y respeta el presupuesto adicional; no consulta proveedores deportivos. Guárdese como dato privado operativo, fuera de git. Un snapshot posterior al inicio o con historial futuro se rechaza. Una descarga actual no reconstruye lo que sabíamos ayer. El libro antiguo de resultados no se importa como decisiones.

## Tennis API opcional

Producto: https://rapidapi.com/jjrm365-kIFr3Nx_odV/api/tennis-api-atp-wta-itf

1. Entrar con la cuenta RapidAPI, pulsar **Subscribe to run**.
2. Elegir **BASIC $0.00** y comprobar 50 solicitudes diarias y el límite duro en el panel.
3. Abrir **Open playground**. Copiar el valor del encabezado **X-RapidAPI-Key** del ejemplo generado.
4. En Render → servicio → Environment, añadir `TENNIS_API_RAPIDAPI_KEY` con ese valor y guardar/redeploy. No pegarla en chat ni en git.

El conector detecta la variable automáticamente. Comparte 50 solicitudes en ventana móvil de 24 horas entre calendario y resultados; no presume una hora de reinicio que el proveedor no haya confirmado. Conserva espacio para resultados al limitar los barridos de calendario a dos fechas, cuatro páginas por fecha y caché de seis horas. Filtros de individuales, horas UTC, edición y participantes definidos. WC/Q/PR del proveedor son etiquetas de un tercero: no reemplazan la confirmación de cuadro oficial. `player1` en calendario no es la ganadora; en archivo de resultados sí. IDs de fixture y archivo se enlazan sólo después de contrastar participantes, edición y ronda. Se descartan campos de cuotas antes de persistir. Acceso y profundidad real ITF siguen sin comprobar hasta disponer de la suscripción.

Documentación: https://docs.tennis-api.com/getting-started ; https://docs.tennis-api.com/fixtures ; https://docs.tennis-api.com/results

## Mapa de fuentes por deporte

Configuración de referencia del anterior despliegue Render y adaptadores integrados; el manifiesto obsoleto fue retirado al migrar a Northflank. **Habilitada** significa que existe una ruta utilizable con la configuración y claves presentes; no garantiza que hoy exista una liga femenina en el catálogo ni acceso verificado de todos sus endpoints. El mapa runtime y las fuentes observadas de `/health` tienen prioridad si se cambia Environment.

| Deporte femenino | Proveedores habilitados, incluidos contextos | Calendario / contexto específico |
|---|---:|---|
| Fútbol | 8 | ESPN, Highlightly, SportScore, SportAPI.ai, OpenLigaDB, TheSportsDB, OddsPapi, The Odds API |
| Básquet | 8 | ESPN, Highlightly, SportScore, Big Balls, BALLDONTLIE, OddsPapi, The Odds API; TheSportsDB como historial auxiliar |
| Tenis | 4, más 1 opcional | WTA oficial, ESPN, SportScore, OddsPapi; Tennis API cuando haya suscripción/key |
| Hockey sobre hielo | 6 | PWHL, ESPN, Highlightly, OddsPapi, The Odds API; TheSportsDB como historial auxiliar |
| Handball | 4 | Highlightly, OddsPapi, The Odds API; TheSportsDB como historial auxiliar |
| Vóley | 6 | FIVB/VIS, CEV, Highlightly, OddsPapi, The Odds API; TheSportsDB como historial auxiliar |
| Rugby | 4 | World Rugby, OddsPapi, The Odds API; TheSportsDB como historial auxiliar |
| Cricket | 2 | SportScore calendario; Cricsheet resultados publicados |
| Softball | 1 | ESPN NCAA, experimental |
| Lacrosse | 1 | ESPN NCAA femenino, experimental |
| Hockey sobre césped | 1 | ESPN NCAA femenino, experimental |

**16 proveedores/fuentes distintos habilitados actualmente** en la comprobación previa de producción. No sumar las filas: se comparten proveedores. WTA ranking PDF y backend oficial cuentan como un proveedor, no como dos pruebas independientes. API-Sports suspendida queda fuera. Tennis API sólo se suma cuando esté configurada y su acceso se pueda comprobar.

Restricciones relevantes:

- Big Balls y BALLDONTLIE: WNBA; no aportan por sí mismos respaldo a cada liga femenina de básquet. ESPN también NCAA.
- TheSportsDB: sólo seis ligas de fútbol configuradas para calendario; el contexto por equipo es auxiliar y exige identidad/categoría verificadas. No se cuenta como proveedor de historial para tenis, donde el motor usa la ruta WTA.
- The Odds API/OddsPapi: las listas de deportes habilitadas no garantizan catálogo femenino activo; su aporte real por fecha se registra aparte. El motor de tenis no obtiene ranking de estos calendarios.
- WTA: cuadro/ranking/historial oficial; no equivale a todo el ITF. ESPN tiene un corte de ranking y funciona como respaldo. Tennis API todavía requiere comprobar profundidad y autorización.
- World Rugby: rama femenina XV; no se declara cobertura general de sevens ni league.
- FIVB/CEV: indoor, competición/edición verificadas; no beach/snow. Los listados pueden carecer de partidos y no certifican ausencia global.
- Cricket: temporada verificada requerida para alertar sobre clubes. El calendario puede ser válido y el evento permanecer sin evaluación.
- Las tres ramas NCAA experimentales necesitan una segunda fuente. Son la dependencia más clara; luego profundidad ITF, rugby y handball. Primero revisar **aporte exclusivo evaluable**, no sólo sumar APIs.

## Rollback

Volver a `775ea512c59058f00518168d7d675cf13577f953` conserva namespaces y cuotas existentes; no borrar claves de Redis. El diario nuevo usa su propio namespace y caduca. Si sólo falla la auditoría, el radar sigue enviando alertas y el estado de persistencia lo indica.
