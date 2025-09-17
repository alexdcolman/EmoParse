# paths.py

from pathlib import Path

# Base del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent

# Carpeta de datos
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Archivos CSV
discursos = DATA_DIR / "A1. discursos.csv"
discursos_filtrado = DATA_DIR / "A2. discursos_filtrado.csv"
discursos_preprocesado = DATA_DIR / "A3. discursos_preprocesado.csv"
discursos_resumen = DATA_DIR / "A4. discursos_resumenes.csv"
discursos_metadatos = DATA_DIR / "A5. discursos_metadatos.csv"
discursos_enunc = DATA_DIR / "A6. discursos_enunciacion.csv"

recortes = DATA_DIR / "B1. recortes.csv"
recortes_filtrado = DATA_DIR / "B2. recortes_filtrado.csv"
recortes_preprocesado = DATA_DIR / "B3. recortes_preprocesado.csv"
recortes_prueba = DATA_DIR / "B3b. recortes_preprocesado_10.csv"

actores_identificados = DATA_DIR / "C1. actores_identificados.csv"
actores_validos = DATA_DIR / "C2. actores_validos.csv"
actores_excluidos = DATA_DIR / "C3. actores_excluidos.csv"

emociones_identificadas = DATA_DIR / "D1. emociones_identificadas.csv"
emociones_enunciador = DATA_DIR / "D1. emociones_identificadas_enunciador.csv"
emociones_enunciatarios = DATA_DIR / "D1. emociones_identificadas_enunciatarios.csv"
emociones_actores = DATA_DIR / "D1. emociones_identificadas_actores.csv"
emociones_caracterizadas = DATA_DIR / "D2. emociones_caracterizadas.csv"
emociones_caracterizadas_enunciador = DATA_DIR / "D2. emociones_caracterizadas_enunciador.csv"
emociones_caracterizadas_enunciatarios = DATA_DIR / "D2. emociones_caracterizadas_enunciatarios.csv"
emociones_caracterizadas_actores = DATA_DIR / "D2. emociones_caracterizadas_actores.csv"
emociones_completo = DATA_DIR / "D3. emociones_completo.csv"

# Carpeta de logs
LOGS_DIR = BASE_DIR / "logs"

# Listas de códigos
codigos_eliminados = LOGS_DIR / "codigos_eliminados.txt"

# Carpeta de errores
ERRORS_DIR = BASE_DIR / "errors"
ERRORS_DIR.mkdir(parents=True, exist_ok=True)

# Listas de errores
errores_metadatos = ERRORS_DIR / "errores_metadatos.jsonl"
errores_enunciacion = ERRORS_DIR / "errores_enunciacion.jsonl"
errores_identificacion_actores = ERRORS_DIR / "errores_identificar_actores.jsonl"
errores_persistentes = ERRORS_DIR / "errores_persistentes.jsonl"
errores_identificacion_emociones = ERRORS_DIR / "errores_identificar_emociones.jsonl"
errores_identificacion_emociones_enunciador = ERRORS_DIR / "errores_identificar_emociones_enunciador.jsonl"
errores_identificacion_emociones_enunciatarios = ERRORS_DIR / "errores_identificar_emociones_enunciatarios.jsonl"
errores_identificacion_emociones_actores = ERRORS_DIR / "errores_identificar_emociones_actores.jsonl"
errores_caracterizacion_emociones_enunciador = ERRORS_DIR / "errores_caracterizar_emociones_enunciador.jsonl"
errores_caracterizacion_emociones_enunciatarios = ERRORS_DIR / "errores_caracterizar_emociones_enunciatarios.jsonl"
errores_caracterizacion_emociones_actores = ERRORS_DIR / "errores_caracterizar_emociones_actores.jsonl"