import ollama
from langchain_ollama import ChatOllama

def get_model(modelo="mistral"):
    
    def modelo_llm(prompt):
        response = ollama.chat(
            model=modelo,
            messages=[{"role": "user", "content": prompt}]
        )
        return response["message"]["content"]
        
    modelo_llm.invoke = modelo_llm
    
    return modelo_llm

# LLM envoltorio para usar con LangChain
llm = ChatOllama(model="mistral", temperature=0.3)