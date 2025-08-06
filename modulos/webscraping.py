from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import time

# XPaths específicos del sitio Casa Rosada
xpaths_casarosada = {
    "link_items": '/html/body/div[1]/div[2]/div/div[1]/div/main/div/section/div/div/div[2]/div[{i}]/div/a',
    "boton_siguiente": '/html/body/div[1]/div[2]/div/div[1]/div/main/div/section/div/div/div[3]/ul/li[13]/a',
    "titulo": '/html/body/div[1]/div[2]/div/div/div[1]/div/div/div/div/div/h2/strong',
    "fecha": '/html/body/div[1]/div[2]/div/div/div[1]/div/div/div/div/div/div[1]/time',
    "contenido": '/html/body/div[1]/div[2]/div/div/div[1]/div/article/div/div[2]/p'
}

# Funciones secundarias
def iniciar_driver(headless=True):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver


def extraer_links_visibles(driver, xpath_link_items, links, max_items_por_pagina=50):
    nuevos_links = []
    for i in range(1, max_items_por_pagina + 1):
        try:
            xpath = xpath_link_items.format(i=i)
            elemento = driver.find_element(By.XPATH, xpath)
            href = elemento.get_attribute('href')
            if href and href not in links:
                nuevos_links.append(href)
        except NoSuchElementException:
            break
    return nuevos_links


def extraer_discurso(driver, link, xpaths, espera, verbose):
    try:
        driver.get(link)
        time.sleep(espera)

        def get_text(xpath, default):
            try:
                return driver.find_element(By.XPATH, xpath).text.strip()
            except:
                return default

        titulo = get_text(xpaths["titulo"], "Título no encontrado")
        fecha = get_text(xpaths["fecha"], "Fecha no encontrada")

        try:
            parrafos = driver.find_elements(By.XPATH, xpaths["contenido"])
            contenido = [p.text.strip() for p in parrafos if p.text.strip()]
            if not contenido:
                contenido = ["Contenido no encontrado"]
        except:
            contenido = ["Contenido no encontrado"]

        if verbose:
            palabras = sum(len(p.split()) for p in contenido)
            print(f"📝 {titulo} ({fecha}) - {palabras} palabras")

        return titulo, fecha, contenido

    except Exception as e:
        if verbose:
            print(f"⚠️ Error procesando {link}: {e}")
        return "Título no encontrado", "Fecha no encontrada", ["Contenido no encontrada"]

# Función principal
def scrap_discursos(
    base_url,
    xpaths,
    espera,
    paginas,
    articulos_maximos,
    headless=True,
    verbose=True,
    output_path=None
):

    driver = iniciar_driver(headless)
    driver.get(base_url)
    time.sleep(espera)

    links = []

    for pagina in range(paginas):
        if verbose:
            print(f"🌐 Página {pagina + 1}")
        nuevos = extraer_links_visibles(driver, xpaths["link_items"], links)
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

    if output_path:
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        if verbose:
            print(f"\n✅ Archivo '{output_path}' guardado correctamente.")

    driver.quit()
    return df

