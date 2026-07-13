# Golden set v1

Formato: JSONL, una unidad por línea:

    {"codigo": "<codigo>", "unit_idx": 0,
     "emociones": [{"experienciador": "...", "tipo_emocion": "...",
                    "foria": "disforico", "modo_existencia": "realizada"}]}

- `emociones: []` anota una unidad SIN emociones (imprescindible para medir
  falsos positivos: incluir unidades neutras a propósito).
- `foria` y `modo_existencia` son opcionales por emoción; si faltan, esa
  dimensión no se evalúa en ese caso.
- El golden de referencia sale de la **mediana de los anotadores** tras el
  protocolo de acuerdo (ver manual_anotacion.md), no de un solo juicio.

Uso:

    emoparse eval --db runs/<run>.sqlite --golden evals/golden/v1 \
        --out evals/reporte_v1.md

`golden_demo.jsonl` es una anotación DE DEMOSTRACIÓN sobre el fixture
`data/ejemplos/tuits_ejemplo.jsonl` (un solo juicio, del desarrollador):
sirve para probar el comando de punta a punta y como ejemplo del formato,
NO como referencia de validez.
