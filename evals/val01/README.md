<!-- EMOPARSE:VAL01-EVALS-README START -->
# VAL-01 · Smoke multigénero con modelos reales

VAL-01 verifica integración técnica sobre tres géneros: posts, artículo
periodístico y discurso presidencial. El cierre del lote 1 utilizó el
`config.yaml` vigente, versions v19/v54/v27/v41 y `gemma4-31b` para la stage
`emotions`.

El smoke controla finalización de stages, routing, contexto, JSON/schema,
persistencia, normalización y exportación. No funciona como golden set ni exige
una única lectura semántica correcta.

Resultados resumidos:

- posts: 5 frases, 8 emociones, 0 errores de detección/caracterización;
- artículo: 4 frases, 5 emociones, 0 errores;
- discurso: 7 frases, 7 emociones, 0 errores;
- brechas de normalización registradas: `cansancio` y `resentimiento`.

Los resultados locales, DB y logs permanecen bajo `.build/val01/` y no forman
parte del repositorio.

Antes de v1.0.0 debe ejecutarse la validación ampliada sobre la base piloto
local `bluesky_milei.jsonl` de 500 posts, con el routing de producción y una
revisión semántica muestral.
<!-- EMOPARSE:VAL01-EVALS-README END -->
