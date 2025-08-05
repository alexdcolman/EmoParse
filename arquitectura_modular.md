## 🧩 Arquitectura modular

El sistema opera como una cadena automatizada de módulos independientes pero integrados. Cada uno cumple funciones específicas que, en conjunto, permiten analizar discursos desde múltiples dimensiones: emocional, enunciativa, retórica y semiótica. Su modularidad facilita tanto la mejora progresiva como la adaptación a distintos tipos de textos.

---

### 1. Recolección de discursos (`webscraping.py`)

- Busca discursos en sitios web definidos (e.g., archivos oficiales, medios).
- Descarga textos completos y genera una base estructurada.
- Guarda metadatos clave: autor, fecha, lugar, medio de publicación, etc.

---

### 2. Preprocesamiento lingüístico (`preprocesamiento.py`)

- Segmenta discursos en frases y unidades lingüísticas.
- Limpia texto (corrige símbolos, errores comunes).
- Realiza análisis gramatical (lemas, POS, dependencias).
- Extrae entidades nombradas (personas, instituciones, lugares).
- Detecta sujetos implícitos y actores no nombrados.
- Identifica nominalizaciones y estructuras relevantes.

---

### 3. Resumen contextual inteligente (`resumen.py`)

- Resume cada discurso a nivel global y, si es necesario, por secciones.
- Utiliza LLMs para sintetizar contenido relevante.
- Proporciona contexto semántico que facilita la detección posterior de actores y emociones.
- Es clave para que LLMs operen con coherencia en frases que omiten explícitamente a los actores.

---

### 4. Identificación de actores discursivos (`identificacion_actores.py`)

Este módulo combina reglas discursivas y modelos LLM para detectar actores enunciativos y representados.

- Identifica:
  - Enunciador (quien habla)
  - Enunciatario (destinatario del discurso)
  - Actores representados en el discurso
- Clasifica tipos de discurso (político, periodístico, científico, etc.) y aplica reglas específicas como la triple destinación simultánea (Verón).
- Reconoce actores:
  - **Explícitos:** personas, grupos, instituciones nombradas.
  - **Implícitos o inferidos:** actores sugeridos pero no nombrados.
- Reasigna sujetos implícitos y clasifica actores según su rol discursivo.

---

### 5. Detección de emociones (`emociones.py`)

Por cada frase, el sistema identifica:

- **Dichas:** emociones expresadas directamente ("Estoy feliz").
- **Mostradas:** emociones inferidas por gestos o acciones ("Se puso roja").
- **Sostenidas:** emociones generadas por el relato ("Fue al hospital a ver nacer a su hijo").
- **Inducidas:** emociones que se buscan generar en el destinatario mediante recursos retóricos.

Además, asigna cada emoción a un actor específico: enunciador, enunciatario u otros actores representados.

---

### 6. Caracterización emocional

A cada emoción detectada se le asignan propiedades:

- **Foria:** tonalidad
  - *Eufórica* (positiva)
  - *Disfórica* (negativa)
  - *Ambifórica* (mixta)
  - *Afórica* (neutral)
- **Dominancia:** base afectiva
  - *Corpórea* (visceral, física)
  - *Cognitiva* (valorativa, racional)
- **Intensidad:** escala entre -1 y 1
- **Fuente emocional:** persona, hecho o situación que origina la emoción

---

### 7. Verificación y control de coherencia (`postprocesamiento.py`)

- Compara emociones clasificadas con un diccionario emocional propio.
- Detecta contradicciones semánticas o errores de asignación.
- Genera alertas cuando una emoción no concuerda con sus atributos (e.g., emoción positiva marcada como disfórica).

---

### 8. Historial de decisiones

- Registra el camino analítico seguido por cada módulo.
- Guarda trazabilidad sobre cómo se clasificó cada frase y emoción.
- Facilita auditorías, depuración y revisión manual de casos límite.

---

### 9. Exportación y análisis

- Genera una base final donde cada línea representa:
  - Una frase
  - Una emoción
  - El actor involucrado
  - Los atributos emocionales correspondientes
- La base está lista para análisis cuantitativo, visualización o estudios comparativos.

---

### 10. Visualización temporal del discurso

- Construye curvas emocionales a lo largo del discurso (frase a frase).
- Permite observar:
  - Evolución emocional del enunciador.
  - Emociones inducidas en el enunciatario.
  - Dinámica afectiva de actores representados.
- Se pueden comparar curvas para analizar tensiones, paralelismos o contrastes.

---

### 🎯 Resultado final

Una herramienta integral para el análisis automatizado de emociones discursivas que articula:

- Lenguaje, estilo y contenido emocional.
- Relaciones enunciativas y afectivas entre actores.
- Efectos emocionales buscados o generados en el destinatario.
- Visualizaciones dinámicas del "clima emocional" de un discurso.
