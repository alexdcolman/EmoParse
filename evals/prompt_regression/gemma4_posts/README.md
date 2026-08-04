# Regresión de prompts con gemma4-31b

Esta prueba se ejecuta después de cerrar los cinco posts de VAL-01. Usa una sola configuración, `gemma4-31b`, con `context_length=4096` y `max_tokens=2048`.

Corpus:

1. `data/ejemplos/tuits_ejemplo.jsonl`: 23 posts heterogéneos para estabilidad semántica y costo sostenido.
2. `long_thread.jsonl`: 12 posts encadenados y relativamente largos para estresar el contexto conversacional por llamada.

La prueba no presupone una cantidad exacta de emociones. Registra errores, bases, logs, exports y un informe automático. Después hay que revisar `emociones.csv` para falsos positivos, omisiones, experienciadores y marcas.

Comando:

    bash scripts/run_gemma4_posts_regression.sh

Resultados:

    .build/prompt_regression/gemma4/
    ~/Downloads/EmoParse_Gemma4_prompt_regression_*.zip

Es una corrida costosa. No ejecutarla dentro de VAL-01 hasta aprobar los cinco posts con el modelo de validación.

El catálogo de normalización no participa en ninguna llamada al modelo; la prueba mide templates, modos de existencia, configuraciones, heurísticas y contexto.
