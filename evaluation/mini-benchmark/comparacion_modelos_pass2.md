# Comparación de modelos — EmoParse `emotions_pass2`

**Tarea:** detección de emociones (segundo pase) sobre el discurso de Milei en CPAC 2024 (161 frases).
**Gold:** silver gold anotado de forma independiente (≈97 frases con emoción / 64 NINGUNA). Está en evaluation/gold/gold.csv.
**Backend:** llama.cpp (GGUF Q4_K_M), salida JSON restringida por GBNF, GPU 24 GB, sin APIs pagas.
**Base común a todos los runs:** fix estructural de pass2 (el contexto previo son *features* —texto de frases anteriores + resumen—, no el roster de emociones detectadas —que generaba el bug de pass2—) + bounds de gramática (`maxItems`, `maxLength`, `ws`, `minItems`).

---

## Métricas

| Métrica | Qué mide | Objetivo |
|---|---|---|
| **Detección** (P/R/F1) | ¿Hay emoción en la frase? (presencia) | alto |
| **Tipo** (rec/prec) | ¿Qué emoción? (sobre frases donde ambos detectan, con equivalencias) | alto |
| **Experienciador** | ¿Quién siente? (sobre los tipos acertados) | alto |
| **Arrastre** | % de emociones justificadas por "contexto previo" (bug de pass2: tendía a detectar emociones que correspondían a frases previas) | bajo (~pass1 ≈ 25%) |

Se reportan dos vistas: **exacta** (match por lema, incluye emociones clasificadas como "low-conf") y la **justa** (usa equivalencias semánticas del archivo evaluation/gold/equivalencias.json + el parámetro `--exclude-low-conf`). La tabla principal usa la vista justa, que es la comparable contra el baseline histórico.

---

## Tabla principal — equivalencias + exclude-low-conf

| Modelo | Prec. | Recall | F1 | FP / FN | Tipo (rec/prec) | Exp. | Arrastre | Notas operativas |
|---|---|---|---|---|---|---|---|---|
| **gemma4-31b** | **0.93** | 0.98 | **0.95** | **5 / 1** | **0.76 / 0.70** | 0.41 | 1% | build nuevo + FA; VRAM justa (18.3 GB) |
| **qwen3.6-35b-a3b** | **0.93** | 0.78 | 0.85 | **4** / 14 | 0.70 / 0.57 | **0.70** | 2% | build nuevo; MoE |
| qwen3-14b | 0.74 | 0.95 | 0.83 | 21 / 3 | 0.69 / 0.54 | 0.57 | 19% | rápido; baseline |
| Mistral-24b | 0.79 | 0.86 | 0.82 | 15 / 9 | 0.62 / 0.46 | 0.62 | 1% | no-thinking; balanceado |
| qwen3.5-35b-a3b | 0.65 | 1.00 | 0.79 | 35 / 0 | 0.68 / 0.53 | 0.64 | 4% | build nuevo; sobre-detecta |
| qwen3.6-27b | 0.73 | 0.88 | 0.79 | 21 / 8 | 0.59 / 0.49 | 0.56 | 2% | build nuevo; sin perfil propio |
| Gemma3-27b | 0.68 | 1.00 | 0.81 | 30 / 0 | 0.57 / 0.45 | 0.43 | 1% | lento (2×); sobre-detecta |
| qwen3-32b | 0.57 | 1.00 | 0.72 | 49 / 0 | 0.51 / 0.43 | 0.41 | 11% | razonador; requiere `/no_think` + `minItems` |

> **Negrita** = mejor (o empatado en el mejor) de la columna.

### Vista exacta (match por lema, incluye low-conf) — referencia

| Modelo | Prec. | Recall | F1 | Tipo (rec/prec) | Exp. |
|---|---|---|---|---|---|
| gemma4-31b | 0.95 | 0.84 | 0.89 | 0.39 / 0.47 | 0.36 |
| qwen3.6-35b-a3b | 0.94 | 0.61 | 0.74 | 0.37 / 0.38 | 0.69 |
| qwen3-14b | 0.82 | 0.84 | 0.83 | 0.27 / 0.28 | 0.53 |
| qwen3.5-35b-a3b | 0.75 | 0.95 | 0.84 | 0.29 / 0.26 | 0.60 |
| qwen3.6-27b | 0.81 | 0.81 | 0.81 | 0.29 / 0.34 | 0.52 |

(La vista exacta castiga sinónimos válidos; sirve solo como piso. Las conclusiones se sacan de la vista justa.)

---

## Perfiles por modelo

- **gemma4-31b — el mejor en detección y tipado.** Rompe el trade precisión↔recall: alta precisión (0.93, solo 5 FP) *y* alto recall (0.98, 1 FN). Mejor tipado del set (0.76/0.70). Sus 5 FP son lecturas borderline dispersas en frases expositivas ambiguas; su único FN es "Muchas gracias" (formulaico). **Talón: experienciador 0.41** (rasgo de la familia Gemma — Gemma3 = 0.43).

- **qwen3.6-35b-a3b — el mejor en detección del experienciador.** Mejor atribución de quién siente (0.70) + precisión máxima (0.93, 4 FP) + buen tipado (0.70/0.57). **Sub-detecta** (recall 0.78, 14 FN): conservador, cuando dispara acierta, pero se pierde ~1 de cada 5 emociones.

- **Mistral-24b — el mejor balance.** Buen experienciador (0.62), buena precisión (0.79), recall medio (0.86), tipado flojo (0.62/0.46). No-thinking → cero problemas con GBNF. La opción "un solo modelo que hace todo decentemente".

- **qwen3-14b — el baseline sólido y rápido.** 14 B, el más rápido. Recall alto (0.95), buen tipado (0.69/0.54), experienciador medio (0.57). Arrastre 19% (el más alto, pero dentro de lo aceptable). Buen default de bajo costo.

- **qwen3.5-35b-a3b — experienciador bueno (0.64) + buen tipado, pero sobre-detecta** (precisión 0.65, 35 FP dispersos: indignación/satisfacción/preocupación). Atrapa todo (recall 1.0) a costa de muchos falsos positivos.

- **qwen3.6-27b — dominado.** Es un qwen3-14b un poco peor en casi todo (recall 0.88, tipado 0.59/0.49), y más grande. No aporta perfil propio.

- **Gemma3-27b — sobre-detector dominado.** Recall 1.0 pero precisión 0.68 (30 FP), tipado y experienciador flojos (0.57/0.45, 0.43), y 2× más lento. Lo supera gemma4 en todo.

- **qwen3-32b — el peor para esta tarea.** Razonador: bajo GBNF tendía a devolver `[]` (resuelto con `/no_think` + `minItems`), pero termina sobre-detectando todo (precisión 0.57, 49 FP, experienciador 0.41). Requirió la mayor cantidad de hacks y es lento.

---

## Hallazgos transversales

1. **Eje precisión↔recall.** Casi todos los modelos se ordenan en un único eje: los conservadores (Mistral, qwen3.6-35b-a3b) tienen alta precisión / bajo recall; los agresivos (Gemma3, qwen3.5, qwen3-32b) tienen recall 1.0 / baja precisión.

2. **gemma4-31b es la excepción:** logra precisión *y* recall altos a la vez. Es genuinamente mejor, no solo otro punto del eje.

3. **Detección/tipo y experienciador los ganan modelos distintos.**
   - *¿Hay emoción? ¿De qué tipo?* → **gemma4-31b**, sin discusión.
   - *¿Quién la siente?* → **qwen3.6-35b-a3b (0.70)**, luego qwen3.5 (0.64) y Mistral (0.62). gemma4 es justo el peor ahí (0.41).
   - Ningún modelo gana los dos ejes.

4. **Modelos de razonamiento vs GBNF.** Los razonadores (por ejemplo, qwen3-32b) encajan mal con la salida estructurada estricta: tienden a no terminar o a devolver `[]`. Mitigable con `/no_think` + bounds de gramática, pero estructuralmente desfavorable. Los no-thinking (Mistral, Gemma) se comportan mejor.

5. **El arrastre dejó de ser problema** en todos los modelos nuevos (1-4%), gracias al fix estructural de pass2. Solo qwen3-14b (19%) y qwen3-32b (11%) quedan más altos, aún así muy por debajo del 91% original.

---

## Recomendaciones

| Prioridad | Modelo | Por qué |
|---|---|---|
| **Detección + tipo** (cobertura y etiqueta correcta) | **gemma4-31b** | Imbatible en P/R/F1 y tipo. Arreglar experienciador aparte. |
| **Experienciador + precisión** (quién siente, pocos FP) | **qwen3.6-35b-a3b** | Mejor exp (0.70) y precisión (0.93); aceptar menor recall. |
| **Un solo modelo balanceado** | **Mistral-24b** | Decente en todo, no sobre-detecta, no-thinking. |
| **Bajo costo / rápido** | **qwen3-14b** | 14 B, rápido, recall y tipado sólidos. |
| Descartados | qwen3-32b, qwen3.6-27b, Gemma3-27b, qwen3.5-35b-a3b* | Dominados o sobre-detectores. (*qwen3.5 solo si el experienciador es primordial y se toleran muchos FP.) |

**Idea de especialización (implicaría modificar la arquitectura del pipeline, o especializar las dos pasadas de detección emocional):** usar **gemma4-31b** para detección + tipo, y reforzar el **experienciador** aparte (prompt/few-shot dedicado, o apoyándose en la etapa actancial downstream, o un segundo modelo). Eso combinaría lo mejor de los dos ejes.

---

## Caveats metodológicos

- **Un solo discurso** (161 frases) y **silver gold**: las cifras son orientativas, no estadística poblacional.
- **Submuestras chicas** en Tipo (40-80 ítems) y Experienciador (40-60): diferencias de ±0.05 son ruido. Lo robusto son las brechas grandes (gemma4 en detección/tipo; qwen3.6-35b-a3b en experienciador; los sobre-detectores en precisión).
- **Un run por modelo.** Los modelos nuevos corren sobre un build de `llama-cpp-python` actualizado (≥0.3.x); revisar reproducibilidad/determinismo (el manejo del `seed` cambió entre versiones).
- **Costo operativo:** gemma4/qwen3.5/qwen3.6 requieren `llama-cpp-python` actualizado + `flash_attn: true` (iSWA de Gemma) + VRAM ajustada en 24 GB. qwen3-14b/Mistral/Gemma3 corren en el build original.
