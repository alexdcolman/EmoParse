"""Prompts del sistema con split system/user.

Los templates viven en templates/*.jinja2 y se renderizan con Jinja2.
Cada módulo <agente>.py mantiene la firma pública: render_system(...) y render_user(...).

SummarizerAgent: SYSTEMs estáticos expuestos como constantes; USERs via Jinja2.
"""
