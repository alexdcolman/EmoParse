# webscraping.py

# XPaths específicos del sitio Casa Rosada
xpaths_casarosada = {
    "link_items": '/html/body/div[1]/div[2]/div/div[1]/div/main/div/section/div/div/div[2]/div[{i}]/div/a',
    "boton_siguiente": '/html/body/div[1]/div[2]/div/div[1]/div/main/div/section/div/div/div[3]/ul/li[13]/a',
    "titulo": '/html/body/div[1]/div[2]/div/div/div[1]/div/div/div/div/div/h2/strong',
    "fecha": '/html/body/div[1]/div[2]/div/div/div[1]/div/div/div/div/div/div[1]/time',
    "contenido": '/html/body/div[1]/div[2]/div/div/div[1]/div/article/div/div[2]/p'
}

import pandas as pd
import time
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException
from modulos.driver_utils import iniciar_driver
from modulos.scraping_utils import extraer_elementos, extraer_discurso
from modulos.utils_io import guardar_csv, mostrar_tiempo_procesamiento

def scrap_discursos(base_url, xpaths, espera, paginas, articulos_maximos,
                    headless=True, verbose=True, output_path=None, mostrar_tiempo=True):
    start_time = time.time()

    driver = iniciar_driver(headless)
    driver.get(base_url)
    time.sleep(espera)

    links = []

    for pagina in range(paginas):
        if verbose:
            print(f"🌐 Página {pagina + 1}")

        nuevos = extraer_elementos(driver, xpath_template=xpaths["link_items"], 
                                   atributo="href", existentes=links, max_items=50)
        links.extend(nuevos)
        if verbose:
            print(f"➕ {len(nuevos)} nuevos links")

        if len(links) >= articulos_maximos:
            break

        try:
            boton_siguiente = driver.find_element(By.XPATH, xpaths["boton_siguiente"])
            driver.execute_script("arguments[0].scrollIntoView(true);", boton_siguiente)
            time.sleep(1)
            boton_siguiente.click()
            if verbose:
                print("➡️ Clic en 'Siguiente'")
            time.sleep(espera)
        except (NoSuchElementException, ElementClickInterceptedException):
            if verbose:
                print("⚠️ No se pudo avanzar a la siguiente página.")
            break

    links = links[:articulos_maximos]
    if verbose:
        print(f"\n🔗 Total de links únicos obtenidos: {len(links)}")

    titulos, fechas, textos = [], [], []
    for i, link in enumerate(links):
        if verbose:
            print(f"\n📄 ({i+1}/{len(links)}) Procesando: {link}")
        t, f, tx = extraer_discurso(driver, link, xpaths, espera, verbose)
        titulos.append(t)
        fechas.append(f)
        textos.append("\n\n".join(tx))

    df = pd.DataFrame({
        'url': links,
        'titulo': titulos,
        'fecha': fechas,
        'contenido': textos
    })

    df["codigo"] = [f"DISCURSO_{i:03d}" for i in range(1, len(df) + 1)]

    df["INDEX"] = df.index.astype(int)

    if output_path:
        guardar_csv(df, output_path, verbose)

    driver.quit()

    if mostrar_tiempo:
        mostrar_tiempo_procesamiento(start_time)

    return df