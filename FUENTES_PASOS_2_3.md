# Fuentes internacionales: investigación y pack de integración

21/10/2026. Continúa la auditoría `AUDITORIA_FUENTES_2026-10-21.md`. Esta fase mantiene los deportes y umbrales deportivos existentes. Motores nuevos y recomendaciones siguen siendo pasos posteriores.

## Investigación del paso 2

Se separan API con cuota recurrente, fuentes oficiales públicas, créditos de prueba y wrappers que repiten una fuente existente. Disponibilidad HTTP no implica permiso de uso ilimitado ni cobertura femenina completa. Ningún MCP amplía por sí mismo la cuota del proveedor subyacente.

| Candidato / deporte | Resultado comprobado | Decisión |
|---|---|---|
| TAURON Liga Kobiet, vóley Polonia | Sitio femenino oficial devuelve tabla y calendario de edición 2026/2027. El parser valida 12 equipos y 18 terminados, reconciliando W/L y diferencia de sets. No había próximos partidos a menos de 24h en esa muestra. | Integrado sin key; no se promete una alerta por integrar la fuente |
| CEV, vóley europeo | El JS público publica `/api/competitions/{id}/detail` y `/api/matches/{id}/standing`. Pruebas HTTP 200: 90 matches y cinco grupos para la edición femenina 1948/1481. | Se incorpora tabla por grupo con reconciliación de resultados de la misma edición. Los próximos encuentros eran eliminatorios; correctamente quedan sin tabla de grupo |
| VBL/SAMS, vóley Alemania | Documentación de interfaz XML para calendario, tablas y resultados. Requiere solicitar API key por correo a `vbl-support@volleyball-bundesliga.de`; la documentación localizada no garantiza aprobación para este bot ni una cuota vigente. | Pendiente de respuesta/autorización y clave. No se envió correo ni se implementó acceso no verificado |
| SportSRC multideporte | V1 se anuncia pública, pero consulta real de categorías devolvió 403. V2 anuncia 1.000/día con key; el calendario completo y la profundidad tienen restricciones y la documentación presenta diferencias entre endpoints/tier. | No integrada sin prueba autenticada de cobertura femenina y alcance gratuito real |
| SportDB.dev, fútbol/básquet/tenis/hockey | Publica REST + MCP y 1.000 consultas iniciales; no se verificó renovación gratuita recurrente. Prueba directa desde este entorno: 403. | Pendiente; no se presenta como equivalente gratuito operativo de SportScore |
| GoSportsAPI, multideporte incluido vóley/handball | Página oficial de precios conserva placeholders `[X,XXX]`, `[TBD]` y cuotas sin completar. | No integrar basándose en marketing no verificable |
| Live Volleyball API | Pricing oficial confirma 100 créditos iniciales, después paquetes de pago. | No usar como respaldo gratuito permanente |
| CricketData, críquet | Pricing oficial: Lifetime Free 100 hits/día, datos con demora y registro sin tarjeta. Falta prueba autenticada por competición femenina. | Candidato para cuando se disponga de key; no se pide registrarse para completar el pack actual |
| Cricsheet, críquet | Descargas estructuradas de ligas y selecciones femeninas. | Ya integrado; no se cuenta como proveedor nuevo por descubrir otro wrapper |
| WTA / Tennis API, tenis | Ruta WTA pública y complemento Tennis API ya existen; otra envoltura MCP no aporta independencia. | Mantener y aprovechar conectores actuales; acceso ITF más profundo necesita pruebas específicas |
| FIBA GDAP, básquet internacional | Registro requiere revisión y acuerdo. | No prometer key gratuita inmediata ni activar endpoints no autorizados |
| SportsDataverse/wehoop, básquet femenino | Herramientas y archivos para WNBA/NCAA; parte de los datos procede de ESPN. | Candidato histórico; independencia se evalúa por procedencia, no por nombre del paquete. NCAA sigue como complemento |
| Sportmonks, fútbol | Free anuncia Danish Superliga y Scottish Premiership; cobertura comercial femenina no equivale a inclusión en ese free. | No sustituye el hueco femenino mundial con la gratuidad verificada |
| SportsDataIO | Prueba usa datos alterados/scrambled; Discovery Lab gratuito se centra en temporadas anteriores. | No usar prueba como señal factual actual |
| PandaScore, esports | Free de calendario/contexto 1.000/h; pricing limita planes estadísticos a usos no relacionados con apuestas. | Requiere aclarar uso y cobertura de competiciones antes de integrar; no modifica el alcance femenino del radar |
| World Aquatics, waterpolo/natación | Descarga real HTTP 200 de ranking femenino waterpolo en PDF; sitio ofrece resultados y rankings por prueba. | Datos candidatos; un ranking no acredita un calendario completo ni un motor nuevo |
| World Netball, netball | Página de rankings responde 200. | Candidato de contexto, sin API/cuota automatizada verificadas |
| ITTF/WTT, BWF, FIP, IHF, IIHF, IFF, World Curling | Localizadas fuentes oficiales de resultados/rankings femeninos. FIP respondió 403 en prueba directa. | Mapa de expansión, no conectores activados sin pruebas de identidad, fechas y contrato |
| World Athletics, UCI, FIS, ISU, IJF, UWW, World Taekwondo, FIE, LPGA, WWS, AAP | Rankings/resultados localizados en sus sitios oficiales para las ramas femeninas. | Requieren adaptadores y, para varios deportes, motores distintos; se conservan como candidatos del mapa amplio |

El pack no instala servidores MCP adicionales ni incorpora un LLM permanente. Continúa como programa Python autónomo.

## Cambios implementados en paso 3

### Nueva fuente polaca

`fuente_tauron.py`, activada por defecto y desactivable con `TAURON_ACTIVO=0`:

- Dos páginas del dominio femenino actual, sin clave. Caché persistente comprimida de seis horas y presupuesto interno separado de 24 solicitudes/día, reserva 2 y ritmo del cliente público de 6/min. Refrescos sanos de dos páginas cada seis horas suponen unas ocho solicitudes base/día; reinicios, errores y reintentos siempre quedan limitados por el presupuesto persistente.
- Se exige título femenino y temporada vigente; se ignoran filas ocultas de jornadas históricas. Los totales de partidos y sets deben coincidir con todos los resultados publicados de la edición.
- Historial para análisis limitado a 90 días; tabla se reconcilia con toda la temporada publicada. Hora local `Europe/Warsaw` convertida a UTC; horas ambiguas/no existentes en DST se rechazan.
- Datos presentes para individuales de equipos senior de liga regular; no se mezclan copas, juveniles ni divisiones inferiores. Sin parciales por set en el contrato utilizado, no se inventan.
- Identidad exacta o aliases explícitos del catálogo nacional. Alias usados sólo después de validar ambos equipos y competición. La deduplicación conserva también claves anteriores de alertas para el nombre original.
- Calendario, tabla, historial, resultados posteriores, presupuesto y capacidad integrados en las rutas existentes. El mapa pasa de ocho a nueve fuentes habilitadas para vóley; no son nueve respaldos para cada liga.

### Aprovechamiento de contexto ya existente

- LVF/LNV/TAURON con identidad resuelta permiten evaluar sin pasar por la bolsa compartida de búsquedas comerciales por nombre.
- Se consultan primero los historiales oficiales nacionales verificables. Se conservan fuentes alternativas por ID ya conocido; con contexto resuelto no se dispara una búsqueda comercial adicional por nombre sólo para rellenar cuatro muestras.
- FIVB puede aprovechar un contexto nacional compatible si falta historial propio. Los partidos internacionales CEV no se mezclan con ligas nacionales: siguen exigiendo contexto compatible.
- LVF/LNV recuperan detalles nuevos para equipos efectivamente solicitados por análisis. Reutilizan los detalles cacheados y mantienen un máximo de cuatro detalles nuevos por fuente/ciclo y sus presupuestos diarios originales.
- El H2H se recupera desde ambos historiales; se deduplica la orientación invertida del mismo resultado y se verifica que participen ambos equipos.
- Tablas CEV se consultan por edición/grupo, con máximo de dos consultas nuevas de edición por ciclo y dentro del presupuesto público ya existente de CEV (30/día, reserva 2). No crea otra bolsa ni aumenta el límite. Eliminatorias sin grupo, tablas inconsistentes, temporadas/participantes diferentes y filas malformadas se rechazan.

### Reparto y diagnóstico

- Se intercalan deportes al recorrer la cola, manteniendo dentro de cada deporte la rotación por último intento y urgencia. No se aumentan los 100 análisis ni las 15 tareas de búsqueda por defecto; cada conector sigue imponiendo su cuota real.
- `/health.coverage.sports.<deporte>.context_evaluations` separa análisis con cuatro muestras por lado, con tabla, con H2H y procedencia efectiva del contexto de las fuentes que sólo aportaron calendario.
- Los recortes de páginas nuevos de Highlightly se agregan a `truncated_pages`; la caché de listados evita repetir peticiones. No se amplía paginación indiscriminadamente ni se inventan IDs de ligas para rellenar `HIGHLIGHTLY_WOMENS_LEAGUES`.
- El diario admite por defecto 30.000 objetos (configurable `AUDIT_MAX_RECORDS`, entre 10.000 y 50.000), sin borrar los anteriores ni aumentar los límites mensuales de comandos/transferencia ni los 100 MB comprimidos. Reserva el último 20 % para decisiones evaluadas/resultados. Las decisiones no evaluadas no duplican el evento completo como evidencia. El estado publica el límite. Es una ampliación acotada, no almacenamiento indefinido: si vuelve a agotarse se omiten nuevas escrituras, sin detener alertas.

## Validación

- Pruebas offline de temporadas, resultados, zona horaria, cuadros/grupos, aislamiento, H2H simétrico, rotación multideporte, identidad y claves antiguas, detalles a demanda, cuotas, capacidades del diario y diagnóstico.
- Suite completa: 155 pruebas aprobadas y compilación verificada antes de publicar. Las pruebas usan transporte simulado; no hacen llamadas comerciales ni envían Telegram.
- Prueba adicional con HTML real descargado: TAURON valida 12 equipos/18 resultados. Respuesta CEV real permite cargar cinco grupos; los dos próximos cruces verificados son eliminatorios y no reciben una tabla que no les corresponde.
- El bot puede seguir sin emitir una alerta de vóley si no se cumplen los criterios deportivos: el pack mejora acceso y procesamiento, no fuerza recomendaciones ni afloja umbrales.

## Fuentes primarias consultadas

- https://www.tauronligakobiet.pl/table/nocookies/1.html
- https://www.tauronligakobiet.pl/games/nocookies/1.html
- https://livescores.cev.eu/app.js
- https://livescores.cev.eu/api/competitions/1948/detail
- https://www.vbl-wiki.de/wiki/Ergebnisschnittstelle/VBL
- https://www.sportsrc.org/ y https://www.sportsrc.org/v2/
- https://sportdb.dev/
- https://gosportsapi.com/pricing
- https://live-volleyball-api.com/pricing
- https://cricketdata.org/pricing/
- https://gdap-portal.fiba.basketball/sign-up
- https://sportsdata.io/help/scrambled-data
- https://www.sportmonks.com/blogs/get-started-with-sportmonks-the-best-free-sports-api-for-developers/
- https://www.pandascore.co/pricing
- https://wehoop.sportsdataverse.org/
- https://www.worldaquatics.com/ y https://netball.sport/events-and-results/world-rankings-hub/current-world-rankings/

## Operación y rollback

Revisión de salud: `international-source-depth-v1`. Northflank debe construir el nuevo main automáticamente si CI/CD sigue habilitado. No necesita modificar secretos para este pack. No se reactivan servicios Render ni se reinician contadores de proveedores.

Desactivar sólo la nueva fuente: `TAURON_ACTIVO=0` y reiniciar una única instancia. Rollback completo al commit anterior al pack conserva datos y presupuestos existentes; no borrar Redis. La integración es compatible con registros antiguos sin el campo `evaluated`.
