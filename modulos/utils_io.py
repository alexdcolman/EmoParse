# utils_io.py

import os
import time

def guardar_csv(df, path_salida, verbose=True):
    if not path_salida:
        raise ValueError("Debe especificarse `path_salida`.")
    os.makedirs(os.path.dirname(path_salida), exist_ok=True)
    df.to_csv(path_salida, index=False, encoding="utf-8-sig")
    if verbose:
        print(f"✅ Archivo guardado: {path_salida}")

def mostrar_tiempo_procesamiento(start_time, mensaje="Tiempo total de procesamiento"):
    tiempo_total = time.time() - start_time
    print(f"⏱ {mensaje}: {tiempo_total:.2f} s")