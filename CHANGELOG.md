# Changelog

## 2.3 — comparación de runs y reportes persistidos

- `run_metrics` conserva el alias efectivo por stage y permite advertir runs mixtos.
- `emoparse eval` puede persistir reportes golden y de control en `eval_reports`.
- El dashboard incorpora **Comparar modelos** con metadata, resultados por género, acuerdo,
  coincidencias referenciales y violaciones de contrato.
- La validación real con modelos queda pendiente hasta completar el golden v2.

## Contexto satélite para la anotación del golden v2

- `7.1A` adquiere padres, antecedentes, raíz, citas y reposts referidos por el corpus de Bluesky,
  sin incorporar respuestas posteriores ni mezclar el corpus origen con el satélite.
- Se congelan posts normalizados, vínculos tipados, una instantánea por unidad y un manifiesto con
  hashes; el proceso no ejecuta stages ni modifica la base de origen.
- El servicio local admite contexto estructurado antes de comenzar la campaña, conserva el hash de
  la instantánea y respalda su SQLite antes de adjuntarla.

## Cobertura del golden v2 por género

- `FIX-GOLDEN-03`: la cobertura mínima se ajusta a 200 posts, 80 párrafos periodísticos y 200
  frases presidenciales.
- La preparación solicita hasta 30 artículos y 24 discursos; el protocolo manual usa 80 unidades
  para artículos.

## Corrección de estructura y cobertura del corpus periodístico

- `FIX-GOLDEN-02`: Página/12 prioriza el cuerpo ANS/HTML con límites de párrafo sobre el `articleBody` aplanado de JSON-LD.
- Se agrega una reparación transaccional del corpus periodístico ad hoc, sin LLM y con respaldo previo.

## Corrección de adquisición para el golden v2

- Página/12 sobreadquiere candidatos para completar 24 artículos válidos cuando algunas URLs
  conservan metadata pero ya no exponen el cuerpo de la nota.
- La reanudación conserva los artículos existentes, deduplica y corta exactamente en el objetivo.

## Organización de referencias y lineamientos de escritura

- Se incorpora un índice documental que identifica la fuente de verdad de cada tema y la función de
  las duplicaciones públicas e internas.
- La antigua referencia monolítica `emoparse_docs.md` queda como redireccionador; sus detalles únicos
  se distribuyen en referencias de pipeline, ejecución LLM, persistencia y gobernanza de prompts.
- `docs/arquitectura.md` documenta backends, batches y cache, y se agrega una guía pública de solución
  de problemas.
- La página de artículos periodísticos se reescribe con los lineamientos visuales y retóricos del
  proyecto.

## Documentación pública y género periodístico

- El sitio incorpora una página propia para artículos periodísticos y presenta de forma consistente
  los tres géneros incluidos.
- Se agrega un tutorial completo de artículos, una referencia técnica pública de arquitectura y una
  navegación actualizada en todas las páginas.
- Se corrigen los comandos de adquisición de discursos y se documentan la metadata editorial, la
  segmentación por párrafos y su presentación y exportación genéricas.
- El SVG del recorrido general incluye artículos; las capturas reales pendientes quedan especificadas
  para la revisión previa a la próxima publicación minor.

## 2.1 — preparación del golden set v2 multigénero

- `emoparse eval --make-sample` incorpora género, metadata de anotación, fuente y modo de
  existencia, y permite exigir diversidad mínima y un máximo de unidades por texto.
- `--freeze-sample` valida y congela planillas completas como JSONL; `--make-retest` prepara una
  segunda pasada ciega de 30 unidades.
- `--agreement` compara anotadores o pasadas sobre presencia, tipo, experienciador, fuente, modo y
  foria.
- `--golden --por-genero` acepta un `--db` por género y produce resultados agregados y separados.
- El manual y `evals/golden/v2/README.md` fijan el protocolo de anotación de autor.
- `emoparse run --prepare-only` crea bases con ingesta y segmentación, sin stages ni modelos.
- `scripts/prepare_golden_v2_corpora.sh` adquiere tres corpus locales nuevos y prepara una SQLite
  independiente por género; `validate_golden_v2_corpora.py` verifica cobertura y ausencia de salidas
  analíticas.

<!-- EMOPARSE:VAL01-LOTE1-CHANGELOG START -->
## VAL-01 · Cierre técnico del lote 1

- `emotions` y `emotions_pass2` mantienen vocabulario abierto; la
  canonicalización ocurre ex post en `normalize_emotions`.
- `emociones.json` conserva exclusivamente los modos de existencia usados por
  detección, mientras `catalogo_normalizacion_emociones.json` queda reservado
  para normalización y no entra en prompts.
- `restricciones_caracterizacion_emociones.json` concentra las restricciones
  de caracterización utilizadas por V11.
- `modo_semiotizacion` y `modo_identificacion` siguen siendo variables
  analíticas: se derivan determinísticamente desde `tipo_configuracion` y se
  conservan en las exportaciones.
- El smoke multigénero con versions v19/v54/v27/v41 completó posts, artículo
  periodístico y discurso presidencial sin errores de `emotions` ni
  `characterizer`; el routing vigente usa `gemma4-31b` para `emotions`.
- Este resultado valida la integración técnica, no la exactitud semántica del
  modelo. La prueba de `bluesky_milei.jsonl` con 500 posts queda como gate
  obligatorio previo a v1.0.0.
<!-- EMOPARSE:VAL01-LOTE1-CHANGELOG END -->

## FIX-VAL01-10 — separación estricta entre detección y normalización

- elimina el catálogo canónico de todos los prompts, agentes de detección y juez;
- `emotions` y `emotions_pass2` vuelven a vocabulario abierto y `normalize_emotions` canonicaliza ex post; la evaluación consume `tipo_emocion_canonico` ya persistido;
- renombra y divide el antiguo recurso: `catalogo_normalizacion_emociones.json` queda exclusivo de `normalize_emotions`, mientras V11 usa `restricciones_caracterizacion_emociones.json`;
- fija en `.dev/referencia/GOBERNANZA_DE_PROMPTS.md` la prohibición absoluta y la diferencia con `emociones.json`, que contiene los modos de existencia;
- añade contratos para impedir regresiones y reduce nuevamente la huella de prompt de Gemma 4.



## FIX-VAL01-09 — depuración de prompts y control de sobreadaptación

- Retira reglas de casos particulares de los templates de `emotions`,
  `emotions_pass2` y `characterizer`; los templates conservan solo el
  contrato estable de entrada/salida.
- Reordena las reglas interpretativas entre heurísticas genéricas y
  heurísticas del género tuit, sin duplicarlas en el prompt renderizado.
- El postprocesado de emociones deja de completar detecciones omitidas por
  el modelo: normaliza únicamente emociones ya producidas y descarta
  atribuciones al enunciador sustentadas solo en matrices epistémicas.
- Añade contratos con contraejemplos, presupuesto de prompt, medición
  reproducible y una regresión preparada para `gemma4-31b`.
- Documenta la gobernanza de prompts en `.dev/referencia/GOBERNANZA_DE_PROMPTS.md`.
- Versiones: `knowledge=v18`, `prompt=v53`, `ontology=v26`, `schema=v41`.

Los cambios públicos relevantes de EmoParse se registran en este archivo. El mantenimiento formal
del changelog comenzó durante la migración de v0.6.5 a v0.7.0; no se reconstruye de manera
retroactiva el detalle completo de versiones anteriores.

El formato sigue los principios de Keep a Changelog y el proyecto usa versionado semántico.

## FIX-VAL01-08 — evidencia independiente y atribución explícita en posts

- Una forma optativa como `Ojalá` sostiene una sola esperanza del enunciador salvo que exista una
  segunda marca emocional literal e independiente en la misma unidad.
- La fuente o el objeto evaluado ya no basta para agregar ira, esperanza u otra emoción del autor
  cuando la marca del experienciador es `no identificado`.
- Las construcciones explícitas `actor + se hartó` se normalizan como verbos psicológicos y el
  caracterizador las reconoce como heteroatribución, no como comportamiento ni como referente
  recuperado solo del contexto.
- Se agregan regresiones con la salida real de `val01_posts_fix07`, incluida la esperanza duplicada
  y la ira espuria del último post.

## FIX-VAL01-07 — consistencia de marcas, experienciadores y atribución en posts

- Las marcas de experienciador y fuente deben pertenecer literalmente al post actual; el contexto
  del hilo puede resolver referentes, pero ya no suministra marcas ausentes.
- Se eliminan lecturas espurias de tristeza, interés, sorpresa e ira en los casos observados de
  VAL-01, y se completan de forma determinista la desconfianza condicional, el hartazgo explícito y
  la esperanza introducida por `Espero` u `Ojalá`.
- `Espero + proposición` conserva una sola esperanza realizada del autor y `Siento que +
  proposición` deja de ocultar predicaciones emocionales independientes de la misma unidad.
- El caracterizador distingue emoción lexicalizada, inferencia cognitiva y referente recuperado
  solo desde el contexto para fijar autoatribución, heteroatribución o ausencia de atribución.
- La derivación de menciones deduplica marcas sin distinguir mayúsculas y prioriza la inferencia que
  coincide con el referente literalmente nombrado.
- Se agregan contratos para los cinco posts y para la consistencia de menciones de experienciador.

## FIX-VAL01-06 — validación del caracterizador y semántica emocional de posts

- El validador de justificaciones distingue la deliberación interna del modelo de las citas
  textuales del corpus, por lo que admite evidencia como `lo voy a creer` sin habilitar fórmulas
  como `voy a poner` o `voy a elegir`.
- La detección emocional diferencia gratitud expresada de esperanza mencionada en mensajes,
  `siento que + proposición` de un sentimiento y `Ojalá` de una inferencia espuria de ansiedad.
- Los experienciadores genéricos del yo en posts se resuelven al handle concreto del enunciador.
- `estar + cansado` como realización de hartazgo se conserva como estado adjetival explícito.
- Se agregan contratos de regresión para los cinco casos pendientes de VAL-01.

## FIX-VAL01-05 — separación de ontología emocional y modos de existencia

- El runner usa `catalogo_normalizacion_emociones.json` como vocabulario léxico cerrado y
  `emociones.json` únicamente como catálogo de modos de existencia.
- La ontología efectiva se valida antes de llamar al modelo: un lookup vacío
  ahora falla cerrado con un error explícito.
- Los prompts de emociones reciben por separado nombres/aliases y modos.
- `normalize_emotions` y `judge` reutilizan la misma ontología configurada.
- Se agregan contratos del cableado real del runner para evitar regresiones.

## [v0.7.0] — 2026-08-05

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

### 4.1A-CTX-01 · Contexto intradocumental de anotación

- Se incorporaron instantáneas reproducibles de metadata y unidades vecinas para artículos y
  discursos del golden v2.
- El servicio de anotación distingue contexto conversacional externo y contexto contenido en el
  mismo documento, sin usar resultados de modelos para orientar al anotador.
