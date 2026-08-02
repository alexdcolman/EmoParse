# Suite de pruebas

La suite separa contratos permanentes de pruebas de andamio y de integraciones con modelos reales.
La corrida ordinaria no necesita red, GPU ni un backend LLM.

## Capas

- `contrato/`: fronteras públicas e invariantes que deben bloquear una entrega si fallan.
- `andamio/`: piezas internas todavía migrables. Se mantienen mientras ayudan a desarrollar y no
  deben fijar implementaciones accidentales.
- `integracion_llm/`: pruebas opt-in con un backend real. No se ejecutan como parte de la validación
  predeterminada.

No se congelan prompts completos ni respuestas concretas de un modelo. Las expectativas se derivan
preferentemente de schemas Pydantic, del DAG, de descriptores de género o del parser del CLI.

## Utilidades compartidas

`tests/factories.py` contiene `FakeBackend` y fábricas que construyen respuestas desde el schema
solicitado. `tests/conftest.py` ofrece bases SQLite temporales, contextos de run y aislamiento de
conexiones y logs.

Al cambiar un schema, se actualiza la fuente de verdad; no se replica su lista de campos dentro de
las fábricas. Un test de andamio que se rompe repetidamente por migraciones deliberadas debe
reformularse como propiedad estable o eliminarse.

## Comandos

```bash
# Calidad estática
ruff check src tests scripts
ruff format --check src tests scripts
mypy  # usa la frontera declarada en tool.mypy.files

# Contratos obligatorios
python -m pytest tests/contrato -q

# Andamio informativo
python -m pytest tests/andamio -q

# Toda la suite sin modelos reales
python -m pytest -m "not llm" -q

# Comprobar la colección completa
python -m pytest --collect-only -q
```

La integración estructurada con un modelo real se documenta en
`tests/integracion_llm/README.md`. Solo se ejecuta cuando se definen explícitamente la configuración
y el alias del modelo.

## Integración continua

GitHub Actions ejecuta los contratos en Python 3.11 y 3.12. El andamio corre con resultado
informativo y no bloquea. Las pruebas LLM, el scraping real y la GPU quedan fuera del workflow.
