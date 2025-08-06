# modules/exportador.py

import pandas as pd
import json
from pathlib import Path

def exportar_csv(df, ruta_salida):
    Path(ruta_salida).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta_salida, index=False, encoding="utf-8-sig")

def exportar_json(data, ruta_salida):
    Path(ruta_salida).parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def exportar_txt(texto, ruta_salida):
    Path(ruta_salida).parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write(texto)


def guardar_cache_emociones(diccionario_emociones, ruta_cache="cache/emociones_cache.json"):
    exportar_json(diccionario_emociones, ruta_cache)