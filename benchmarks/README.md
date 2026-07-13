# Benchmarks de backend

Protocolo para medir el efecto de cada palanca de performance, una a la vez.

## Preparación

Corpus fijo (500–1000 posts), seed fija, cache deshabilitado o DB nueva por
variante (el harness usa DB nueva). Variantes típicas:

1. **Baseline in-process**: `backend: llama_cpp` (config actual).
2. **llama-server**: mismo modelo servido:
   `llama-server -m modelo.gguf -ngl 99 -c 16384 --parallel 4 --cont-batching --cache-reuse 256 --port 8080`
   y en el config: `backend: llama_server`, `base_url: http://127.0.0.1:8080`,
   `pipeline.parallel: 4`.
3. **Speculative decoding**: variante 2 + `--model-draft draft-chico.gguf`
   en el server. ATENCIÓN: con gramáticas GBNF la aceptación del draft puede
   caer y anular la ganancia; por eso se mide, no se asume. Comparar la
   columna tok/s de `emoparse metrics` (o del harness).
4. **KV cuantizado**: variante 2 + `--cache-type-k q8_0 --cache-type-v q8_0`.
   Verificar además calidad: correr `emoparse eval --golden ...` sobre el
   resultado (la cuantización del KV puede degradar salidas largas).

## Corrida

    python benchmarks/bench_pipeline.py \
        --input data/corpus_bench.jsonl --genre tuit \
        --stages technoparse,actors,emotions \
        --config-a config_inprocess.yaml --label-a baseline \
        --config-b config_server.yaml   --label-b server_p4 \
        --runs 3 --out benchmarks/resultado.md

## Lectura

- `prompt_tok` estable entre variantes (mismo corpus/prompts); si `total_s`
  baja con server, es cache de prefijo + batching (dominante en prefill).
- `tok/s` es la métrica de decode: es la que mueve el speculative decoding.
- Guardar cada `resultado.md` versionado junto al hash del config.
