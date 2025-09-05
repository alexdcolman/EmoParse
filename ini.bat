@echo off
echo Iniciando entorno para Primer MVP1...

:: 2. Activar entorno Conda
call conda activate ag_env2

:: 3. Verificar si pip está instalado
pip --version >nul 2>&1
if errorlevel 1 (
    echo Instalando pip...
    conda install -y pip
) else (
    echo pip ya está instalado.
)

:: 4. Instalar PyTorch con CUDA (cu118) desde el índice oficial de PyTorch
echo Instalando PyTorch con soporte CUDA 11.8...
pip install torch==2.1.0+cu118 torchvision==0.16.0+cu118 torchaudio==2.1.0+cu118 -f https://download.pytorch.org/whl/torch_stable.html

:: 5. Instalar dependencias del proyecto
echo Instalando dependencias desde requirements.txt...
pip install -r requirements.txt
pip install stanza

:: 6. Verificar y descargar recursos de NLTK
for %%R in (punkt averaged_perceptron_tagger stopwords wordnet omw-1.4) do (
    python -c "import nltk; nltk.data.find('tokenizers/%%R')" 2>NUL || (
        echo Descargando recurso NLTK: %%R
        python -m nltk.downloader %%R
    )
)

:: 7. Verificar y descargar modelos de spaCy
for %%M in (es_core_news_sm es_core_news_md) do (
    python -m spacy validate | find "%%M" >nul
    if errorlevel 1 (
        echo Descargando modelo spaCy: %%M
        python -m spacy download %%M
    ) else (
        echo Modelo %%M ya está instalado.
    )
)

:: 8. Verificar y descargar modelo de Stanza (es)
python -c "import stanza; stanza.Pipeline('es')" 2>NUL || (
    echo Descargando modelo de Stanza: es
    python -m stanza.download es
)

:: 9. Lanzar Jupyter Lab
echo Iniciando Jupyter Lab...
jupyter lab
