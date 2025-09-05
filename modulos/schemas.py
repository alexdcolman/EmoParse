from pydantic import BaseModel, RootModel
from typing import List, Optional
from langchain.output_parsers import PydanticOutputParser

# --- Tipo de discurso ---
class TipoDiscursoSchema(BaseModel):
    tipo: str
    justificacion: str

    @classmethod
    def get_langchain_parser(cls):
        return PydanticOutputParser(pydantic_object=cls)

# --- Lugar ---
class LugarSchema(BaseModel):
    ciudad: str
    provincia: str
    pais: str
    justificacion: str

    @classmethod
    def get_langchain_parser(cls):
        return PydanticOutputParser(pydantic_object=cls)

# --- Enunciación ---
class EnunciadorSchema(BaseModel):
    actor: str
    justificacion: str

class EnunciatarioSchema(BaseModel):
    actor: str
    tipo: str
    justificacion: str

class EnunciacionSchema(BaseModel):
    enunciador: EnunciadorSchema
    enunciatarios: List[EnunciatarioSchema]

    @classmethod
    def get_langchain_parser(cls):
        return PydanticOutputParser(pydantic_object=cls)

# --- Actores ---
class ActorSchema(BaseModel):
    actor: str
    tipo: str
    modo: str
    justificacion: str

class ListaActoresSchema(RootModel[List[ActorSchema]]):
    @classmethod
    def get_langchain_parser(cls):
        return PydanticOutputParser(pydantic_object=cls)
