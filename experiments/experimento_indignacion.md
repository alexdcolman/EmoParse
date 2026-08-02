# Experimento: la indignación en EmoParse

**Pregunta**: la sobrerrepresentación de emociones disfóricas —y de la
indignación en particular— ¿es un sesgo de los modelos de lenguaje, o una
propiedad de los regímenes de producción y reconocimiento del sentido
contemporáneos que el sistema está registrando bien?

**Antecedente**: en el corpus de artículos de investigación en historia reciente
de la tesis doctoral, la indignación fue la emoción más frecuente — anotada por
un humano, sin modelos de lenguaje de por medio.

**Por qué vale plantearlo como experimento**: las dos explicaciones piden
correcciones opuestas. Si es artefacto, hay que subir el umbral de detección. Si
es fenómeno, subirlo destruye un hallazgo. Y los cuatro contrastes que las
separan usan instrumentos que EmoParse ya tiene.

---

## Cuatro contrastes

| # | Contraste | Instrumento | Qué indicaría artefacto | Qué indicaría fenómeno |
|---|---|---|---|---|
| 1 | **Sobre-detección estructural** | `eval --control` sobre `control_neutro.csv` | El modelo detecta indignación en texto administrativo sin carga afectiva | Tasa cercana a cero |
| 2 | **Acuerdo con lectura humana** | `eval --golden` (2.1) | El anotador lee mucha menos indignación que el modelo sobre los mismos textos | Frecuencias comparables |
| 3 | **Convergencia entre modelos** | `agreement.py` tratando cada run como anotador (2.3) | Un modelo la sobrerrepresenta y otros no: sesgo de esa familia | Modelos de arquitecturas y datos distintos coinciden en la tasa |
| 4 | **Variación entre géneros** | `eval --golden --por-genero` con los géneros de 6.1 | — | La indignación domina en géneros muy distintos (tuit político, alocución, artículo de investigación): apunta a un régimen de sentido, no a una particularidad genérica |

El contraste 2 es el decisivo: es el único que compara al sistema con una lectura
que no pasó por un modelo. El 3 es el más barato una vez que existan dos runs
comparables.

**Combinación diagnóstica**: control alto + desacuerdo con el humano = artefacto
puro, corregir umbral. Control bajo + acuerdo con el humano + convergencia entre
modelos = hay fenómeno, y la corrección de prompt debe apuntar sólo a la
sobre-detección residual sin tocar la tasa de fondo.

---

## Precisión conceptual necesaria antes de medir

La indignación no es sólo una emoción disfórica más: es **una emoción con
componente normativo**. Se siente ante algo juzgado como violación de una norma,
lo que la vuelve estructuralmente distinta de la tristeza o el miedo. Eso importa
para el experimento por dos razones:

- En el diseño de EmoParse, ese componente debería aparecer en el **verificador
  normativo** del análisis actancial, no sólo en el tipo de emoción. Si la
  indignación detectada rara vez trae verificador normativo, es señal de que el
  modelo está usando la etiqueta como categoría de disforia genérica — un sesgo
  de etiqueta, no una emoción bien identificada.
- Varias entradas de la ontología v3 son vecinas suyas por el mismo eje
  (desaprobación, hartazgo, desprecio, odio). Si el sistema colapsa la vecindad
  en la etiqueta más frecuente, el problema es de granularidad ontológica y no de
  detección.

**Medición asociada, barata**: proporción de indignaciones detectadas que traen
verificador normativo identificado (requiere `actants`), y distribución de la
vecindad disfórica-normativa en el mismo corpus.

---

## Procedimiento mínimo

1. Correr los cuatro contrastes sobre el corpus disponible y registrar las tasas
   en una tabla.
2. Medir la proporción de indignaciones con verificador normativo.
3. Sólo entonces decidir las palancas de prompt (ítem 5.1 de `PENDIENTES.md`),
   con la tasa de fondo del contraste 2 como piso: la corrección debe bajar
   falsos positivos sin bajar la detección hasta debajo de la lectura humana.
4. Registrar el resultado en este archivo, aunque sea negativo.

**Aclaración de alcance**: nada de esto prueba la hipótesis histórica sobre los
regímenes de sentido. Prueba, como mucho, que la frecuencia observada no se
explica por el instrumento — que es la condición previa para poder sostener la
hipótesis con datos.
