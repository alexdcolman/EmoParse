# Changelog

Los cambios públicos relevantes de EmoParse se registran en este archivo. El mantenimiento formal
del changelog comenzó durante la migración de v0.6.5 a v0.7.0; no se reconstruye de manera
retroactiva el detalle completo de versiones anteriores.

El formato sigue los principios de Keep a Changelog y el proyecto usa versionado semántico.

## [Sin publicar] — v0.7.0

### Agregado

- `CHANGELOG.md` como registro público acumulativo.
- Guía interna de prueba piloto hacia v1.0.0.
- Estrategia documental y de pruebas para futuras versiones.
- Pruebas de regresión para transacciones SQLite, carga opcional del scraper y aliases de
  compatibilidad.
- Fuente `pagina12` para construir localmente corpus de artículos recientes desde el sitemap del
  medio, conservando metadata editorial.
- Género built-in `articulo_periodistico`, con chunking por párrafo, roles enunciativos propios y
  tipos periodísticos cerrados.
- Declaración y validación Pydantic de metadata de input específica por género.
- Bloques declarativos de contexto de género, con campos etiquetados y presupuesto aproximado por stage.
- Composición genérica de metadata de género en `summarizer`, `metadata`, `enunciation` y `emotions`.
- Interfaz común `ContextBlockProvider` para contexto dinámico de hilo, tecnolingüísticos, media,
  reframing y emociones materializadas, con alcance y presupuesto declarados.
- Guía pública de puntos de extensión para géneros y metadata propia.
- Snapshot de presentación del género persistido con cada run, independiente de la disponibilidad
  posterior del plugin.
- Presentación genérica de metadata de input en las tabs Revisión y Tabla.
- `metadata_genero.csv` en formato largo, con presencia explícita por campo para medir cobertura.
- Suite estable separada en contratos permanentes, pruebas de andamio e integraciones LLM opt-in.
- `FakeBackend`, fábricas derivadas de schemas y fixtures aisladas para pruebas sin GPU ni red.
- Contratos automatizados para CLI, DAG, gramática estructurada, persistencia, exportaciones y
  documentación generada.
- Integración continua con Ruff, mypy, contratos en Python 3.11/3.12, documentación generada y
  construcción del wheel.
- Línea de base progresiva de lint y tipado: Ruff bloquea errores de sintaxis, imports y reglas
  seguras; mypy estricto cubre una frontera explícita de archivos ya limpios y se ampliará por módulos.
- `.git-blame-ignore-revs` para excluir del análisis de autoría el formateo mecánico inicial.
- Selectores dinámicos sobre payloads de stages anteriores mediante notación punto en el mismo YAML
  de `--select`.
- Persistencia del alcance por stage y categoría `fuera de alcance` en el estado del CLI y del
  dashboard.
- Traducción SQL compartida de filtros JSON entre selectores de corrida y políticas de reintento.
- Arnés reproducible `scripts/val01_smoke.py` para preparar y verificar el smoke test multigénero con un único modelo local.

### Corregido

- La detección de emociones queda cerrada al vocabulario efectivo de la ontología del género: aliases se canonizan antes de persistir y las etiquetas ajenas se descartan con advertencia.
- El prompt emocional distingue emoción negada o ausente, predicado emocional y objeto léxico; evita interpretar `carezco de esperanza` como esperanza y `colmar la paciencia` como paciencia.
- La autoatribución ya no puede asignarse a un experienciador distinto del emisor por la presencia de una matriz en primera persona como `creo que` o `siento que`.
- En respuestas de redes, la cuenta destinataria directa se obtiene de la relación del hilo y no se describe falsamente como una mención textual.
- `audiencia_ambiente` se documenta como audiencia pública secundaria compatible con una respuesta directa.
- Los roles de destinatario del discurso periodístico se unifican entre el género
  `articulo_periodistico`, el tipo `periodistico_informativo` de `tuit` y
  `knowledge/tipos_discurso.json`: `lector_ciudadano`, `instancia_blanco` y
  `fuente_referente`.
- La destinación del discurso político usa como fuente primaria las definiciones de
  `knowledge/tipos_discurso.json`: los vocativos y la presencia física describen el auditorio, no
  prueban por sí solos posiciones pro, para o contradestinatarias.
- Los géneros orales pueden declarar `auditorio_oral`; cuando hay marcas situacionales y el modelo
  omite el público presente, se materializa un auditorio mínimo determinista.
- Las justificaciones del caracterizador rechazan deliberación interna, relecturas y referencias al
  prompt; solo admiten la decisión final y su evidencia textual.
- La stage `semas` registra también los referentes procesados con resultado vacío, evitando que el
  estado los muestre como pendientes y que una reanudación vuelva a procesarlos.
- VAL-01 asigna el alias elegido a todas las stages LLM declaradas en el config; la primera
  corrida del artículo reveló que `semas` seguía usando `gemma4-31b`.
- En artículos periodísticos, la autoría declarada fija de forma determinista a la persona o firma
  emisora; el nombre del medio deja de sustituirla cuando `autoria` está presente.
- Los campos categoriales de la estructura enunciativa (`actor`, `nombre`, `clase`) rechazan
  etiquetas metalingüísticas como `enunciador` o `enunciatario`; las justificaciones conservan esa
  terminología analítica cuando corresponde.
- El adapter de Página/12 reconoce explícitamente el marcado actual
  `.p12Author .author-name .name`, incluida la ruta `/autores/`.
- Los reexports públicos `get_emociones` y `get_emociones_enriched` de la capa del dashboard se declaran explícitamente para que Ruff no los elimine como imports sin uso.
- La configuración inicial de lint ya no trata sugerencias de simplificación como errores de CI.
- El gate inicial de mypy usa Python 3.12 y una frontera explícita de archivos ya limpios; la deuda
  detectada en schemas, validators y backends queda registrada para adopción gradual.
- La importación general del CLI ya no requiere `beautifulsoup4` ni `lxml` hasta que se utiliza el
  scraper de Casa Rosada.
- Los errores de apertura o commit de una transacción SQLite ya no pueden quedar ocultos por un
  error secundario de rollback; los cursores transaccionales se cierran explícitamente.
- `modalidad` vuelve a ser opt-in en el pipeline default, en acuerdo con su contrato documentado y
  con el carácter opcional del extra `nlp`.
- Las tablas de la referencia HTML del CLI aprovechan el margen derecho disponible y mantienen
  legibles las columnas de opción, valor y default.
- El adapter de Página/12 ya no termina silenciosamente con cero resultados cuando el sitemap no
  expone URLs de artículos: utiliza como respaldo los feeds RSS oficiales y admite las URLs
  históricas basadas en identificador numérico.
- El cuerpo de las notas de Página/12 se recupera desde `Fusion.globalContent` cuando Arc XP no lo
  renderiza como párrafos en el HTML inicial.

### Cambiado

- Reorganización de la documentación interna de continuidad bajo `.dev/`.
- Separación entre pendientes activos, implementaciones realizadas y documentación histórica.
- Adaptación de las instrucciones de desarrollo de `.assistant/` a EmoParse.
- `emoparse.core.backend.grammar` delega en la implementación canónica de
  `emoparse.core.grammar`.
- Los módulos históricos de `emoparse.scraping` delegan en `emoparse.acquisition` y conservan sus
  imports compatibles.
- El system prompt base de `metadata` es neutral respecto del campo discursivo y utiliza el
  vocabulario cerrado declarado por el género cuando corresponde.
- `tuit` compone `metadata` y `enunciation` sobre los templates base; las reglas específicas se
  aportan mediante heurísticas y propiedades declarativas del género, sin duplicar el system
  prompt completo.
- Los valores estructurados de metadata de input se serializan como JSON válido en
  `discursos.csv` y en las descargas de la tab Tabla.
- La reanudación de un run sincroniza únicamente la sección reservada `_emoparse` de su config y
  conserva el config original del usuario.
- Los filtros del input se resuelven durante la ingesta; los filtros de payload empiezan a regir
  únicamente después de que su stage productora queda completa y afectan a las stages posteriores.

### Documentación

- Sitio HTML sincronizado con v0.6.5: pipeline completo, etapas digitales, backends, selección
  parcial y fuentes de adquisición vigentes.
- Ayuda de `run --stages` derivada del DAG canónico y referencia de comandos actualizada.
- Nuevo diagrama de dependencias para las veinte stages actuales.
- Incorporación de la actualización de tutoriales como requisito de cada versión minor o major.
- Auditorías técnica, de estilo y documental de la línea de base v0.6.5.
- Clasificación de la suite histórica para recuperación selectiva, sin usar contratos retirados como
  compuerta de aceptación.
- Validación local del corpus piloto: 24 artículos de Página/12 extraídos e ingeridos sin fallos.
- Registro explícito de la auditoría futura de campos editoriales por sitio, incluida la cobertura
  nula de `volanta` en la muestra piloto, antes de generalizar el scraper periodístico.

## [v0.6.5] — línea de base

v0.6.5 es la primera versión tomada como línea de base por este changelog. Los cambios anteriores
se consultan en el historial de Git y la documentación histórica del proyecto.
