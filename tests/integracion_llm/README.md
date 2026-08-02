# Integración con modelo real

Estas pruebas son opt-in. No forman parte de la corrida rápida y no deben ejecutarse en CI sin un
backend configurado explícitamente.

```bash
EMOPARSE_LLM_TEST_CONFIG=config.yaml \
EMOPARSE_LLM_TEST_MODEL=gemma4_31b \
python -m pytest tests/integracion_llm -m llm -q
```

La prueba multigénero con artículo, discurso y posts se incorpora como smoke test después de cerrar
la siguiente tanda de migraciones funcionales. No se fijan respuestas semánticas concretas del
modelo: solo validez estructural y terminación del flujo.
