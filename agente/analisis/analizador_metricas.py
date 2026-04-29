"""
Analiza métricas de Instagram con Claude y genera recomendaciones estratégicas.
El reporte se exporta a Obsidian y queda en material_agente/reportes/.
"""

import logging
from datetime import datetime
from pathlib import Path

from config import settings
from agente.claude.cliente_claude import ClienteClaude
from agente.claude import prompt_builder as pb
from agente.memoria import gestor_memoria as memoria
from agente.obsidian.exportador import exportar_reporte_metricas

logger = logging.getLogger(__name__)


class AnalizadorMetricas:

    def __init__(self):
        self._claude = ClienteClaude()

    def generar_reporte(self) -> str:
        """
        Genera un reporte estratégico semanal con Claude.
        Retorna el texto del reporte en Markdown.
        """
        metricas = memoria.cargar_metricas()
        semana = datetime.now().strftime("%Y-W%W")

        if not metricas or not metricas.semanas:
            logger.warning("No hay métricas para analizar")
            return "# Sin métricas disponibles\n\nEjecuta primero `analizar_metricas` para descargar los datos."

        semanas_recientes = metricas.semanas[-4:]
        historial = memoria.cargar_historial()

        prompt = pb.prompt_analisis_metricas(
            metricas={"semana_actual": semana, "semanas": semanas_recientes},
            historial=[p.model_dump() for p in historial.publicaciones[-20:]],
        )
        contexto_marca = pb.construir_contexto_marca()

        reporte = self._claude.generar_con_cache(
            contexto_cache=contexto_marca,
            prompt_usuario=prompt,
            temperatura=settings.TEMPERATURAS_CLAUDE.get("analisis", 0.3),
            max_tokens=2000,
        )

        self._guardar_reporte(reporte, semana)
        exportar_reporte_metricas(reporte, semana)

        return reporte

    def _guardar_reporte(self, reporte: str, semana: str):
        ruta = settings.MATERIAL_AGENTE_DIR / "reportes" / f"reporte_{semana}.md"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(reporte, encoding="utf-8")
        logger.info("Reporte guardado: %s", ruta.name)
