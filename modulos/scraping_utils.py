# scraping_utils.py

import time
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, ElementClickInterceptedException

def get_text(driver, xpath, default="No encontrado"):
    """
    Intenta extraer el texto de un elemento usando su XPath.
    Devuelve 'default' si no se encuentra el elemento.
    """
    try:
        return driver.find_element(By.XPATH, xpath).text.strip()
    except NoSuchElementException:
        return default
    except Exception:
        return default

def extraer_elementos(driver, xpath_template, atributo=None, max_items=50, existentes=None):
    """
    Extrae valores de elementos visibles usando un XPath con índice {i}.
    - xpath_template: string con {i} donde se iterarán los elementos.
    - atributo: si None, devuelve el texto; si es un string, devuelve el atributo del elemento.
    - existentes: lista de valores ya extraídos para evitar duplicados.
    """
    if existentes is None:
        existentes = []

    resultados = []
    for i in range(1, max_items + 1):
        try:
            xpath = xpath_template.format(i=i)
            elemento = driver.find_element(By.XPATH, xpath)
            valor = elemento.get_attribute(atributo) if atributo else elemento.text.strip()
            if valor and valor not in existentes:
                resultados.append(valor)
        except NoSuchElementException:
            break
        except Exception:
            continue
    return resultados

def extraer_discurso(driver, link, xpaths, espera=2, verbose=True):
    """
    Extrae título, fecha y contenido de un discurso desde su link.
    """
    try:
        driver.get(link)
        time.sleep(espera)

        titulo = get_text(driver, xpaths["titulo"], "Título no encontrado")
        fecha = get_text(driver, xpaths["fecha"], "Fecha no encontrada")

        try:
            parrafos = driver.find_elements(By.XPATH, xpaths["contenido"])
            contenido = [p.text.strip() for p in parrafos if p.text.strip()]
            if not contenido:
                contenido = ["Contenido no encontrado"]
        except Exception:
            contenido = ["Contenido no encontrado"]

        if verbose:
            palabras = sum(len(p.split()) for p in contenido)
            print(f"📝 {titulo} ({fecha}) - {palabras} palabras")

        return titulo, fecha, contenido

    except Exception as e:
        if verbose:
            print(f"⚠️ Error procesando {link}: {e}")
        return "Título no encontrado", "Fecha no encontrada", ["Contenido no encontrado"]