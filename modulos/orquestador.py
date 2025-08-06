# modules/orquestador.py

import logging
import pandas as pd
from modules import (
    preprocesamiento,
    deteccion_emociones,
    clasificacion_emocional,
    modo_existencia,
    foria_dominancia,
    intensidad,
    experienciador,
    fuente_emocional,
    exportador
)

# Configurar logging
logging.basicConfig(
    filename="logs/decisiones.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def ejecutar_pipeline(ruta_entrada="data/textos.csv"):
    logging.info("Inicio del pipeline emocional.")

    df = pd.read_csv(ruta_entrada, encoding="utf-8-sig")
    logging.info(f"Se cargaron {len(df)} textos.")

    try:
        df = preprocesamiento.procesar(df)
        logging.info("Preprocesamiento completado.")

        df = deteccion_emociones.detectar(df)
        logging.info("Detección de emociones completada.")

        df = clasificacion_emocional.clasificar(df)
        logging.info("Clasificación emocional completada.")

        df = modo_existencia.anotar(df)
        logging.info("Modo de existencia anotado.")

        df = foria_dominancia.analizar(df)
        logging.info("Foria y dominancia evaluadas.")

        df = intensidad.evaluar(df)
        logging.info("Intensidad emocional evaluada.")

        df = experienciador.extraer(df)
        logging.info("Experienciador extraído.")

        df = fuente_emocional.inferir(df)
        logging.info("Fuente emocional inferida.")

        exportador.exportar_csv(df, "data/resultado_emocional.csv")
        logging.info("Resultados exportados correctamente.")

    except Exception as e:
        logging.error(f"Error en el pipeline: {e}")
        raise

    logging.info("Pipeline emocional finalizado con éxito.")