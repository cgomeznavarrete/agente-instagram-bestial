"""
Genera y gestiona el banco de ideas de contenido usando Claude.
"""

import uuid
import logging
from datetime import date

from config import settings
from agente.claude.cliente_claude import ClienteClaude
from agente.claude.prompt_builder import construir_contexto_marca
from agente.memoria import gestor_memoria as memoria
from agente.memoria.modelos import Idea

logger = logging.getLogger(__name__)

PROMPT_IDEAS = """
Genera 10 ideas frescas de contenido para Instagram de Salsas Bestial.

CONTEXTO: El banco de ideas debe tener variedad de pilares, tipos y enfoques.
Prioriza ideas que sean virales, auténticas y fáciles de producir con fotos del producto.

Devuelve ÚNICAMENTE este JSON:
{
  "ideas": [
    {
      "tipo_sugerido": "post|reel|story|carrusel",
      "pilar": "nombre_del_pilar",
      "concepto": "descripción clara y específica de la idea",
      "prioridad": "alta|media|baja",
      "notas": "por qué esta idea tiene potencial viral o comercial"
    }
  ]
}
"""


class GeneradorIdeas:

    def __init__(self):
        self._claude = ClienteClaude()

    def generar_banco(self, cantidad: int = 10) -> list[Idea]:
        """Genera nuevas ideas y las agrega al banco existente."""
        ideas_existentes = memoria.obtener_ideas_disponibles()
        conceptos_existentes = {i.concepto[:50] for i in ideas_existentes}

        contexto = construir_contexto_marca()
        prompt = PROMPT_IDEAS
        if conceptos_existentes:
            lista = "\n".join(f"- {c}" for c in list(conceptos_existentes)[:10])
            prompt += f"\n\nIDEAS YA EXISTENTES (no repetir):\n{lista}"

        try:
            datos = self._claude.generar_json(
                prompt_sistema=contexto,
                prompt_usuario=prompt,
                temperatura=settings.TEMPERATURAS_CLAUDE["ideas_contenido"],
            )
        except Exception as e:
            logger.error("Error generando ideas: %s", e)
            return []

        nuevas = []
        for item in datos.get("ideas", []):
            idea = Idea(
                id=f"idea-{uuid.uuid4().hex[:8]}",
                fecha_generacion=date.today(),
                origen="claude",
                tipo_sugerido=item.get("tipo_sugerido", "post"),
                pilar=item.get("pilar", "lifestyle_y_comunidad").lower().replace(" ", "_"),
                concepto=item.get("concepto", ""),
                notas=item.get("notas"),
                prioridad=item.get("prioridad", "media"),
            )
            nuevas.append(idea)

        if nuevas:
            memoria.agregar_ideas(nuevas)
            logger.info("Banco de ideas: %d nuevas ideas agregadas", len(nuevas))

        return nuevas
