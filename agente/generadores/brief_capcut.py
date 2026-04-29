"""
Genera briefs de producción detallados para CapCut.
Cada brief es un archivo Markdown listo para que el editor humano lo siga.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from config import settings
from agente.claude.cliente_claude import ClienteClaude
from agente.claude.prompt_builder import construir_contexto_marca, prompt_brief_capcut
from agente.memoria.modelos import EntradaCalendario
from agente.gestores import material as gestor_material

logger = logging.getLogger(__name__)

TIPOS_VIDEO = {"reel", "story_video"}


class GeneradorBriefCapCut:

    def __init__(self):
        self._claude = ClienteClaude()
        self._contexto = construir_contexto_marca()

    def generar_y_guardar(self, entrada: EntradaCalendario) -> Path:
        """Genera el brief JSON y lo exporta como Markdown. Retorna la ruta del .md."""
        catalogo = gestor_material.cargar_catalogo()
        material_disponible = [
            a["ruta"] for a in
            catalogo.get("material_usuario", []) +
            catalogo.get("referencia_producto", [])
        ]

        entrada_dict = {
            "tipo_contenido": entrada.tipo_contenido,
            "pilar": entrada.pilar,
            "objetivo": entrada.objetivo,
            "concepto": entrada.concepto,
            "fecha": str(entrada.fecha),
            "hora_publicacion": entrada.hora_publicacion,
        }

        datos = self._claude.generar_json(
            prompt_sistema=self._contexto,
            prompt_usuario=prompt_brief_capcut(entrada_dict, material_disponible[:15]),
            temperatura=settings.TEMPERATURAS_CLAUDE["brief_capcut"],
        )

        ruta_md = self._exportar_markdown(entrada, datos)
        logger.info("Brief CapCut generado: %s", ruta_md.name)
        return ruta_md

    def _exportar_markdown(self, entrada: EntradaCalendario, datos: dict) -> Path:
        """Convierte el JSON del brief en un Markdown estructurado y legible."""
        nombre = f"{entrada.fecha}_{entrada.tipo_contenido}_{entrada.id}.md"
        ruta = settings.MATERIAL_AGENTE_DIR / "briefs_capcut" / nombre

        escenas = datos.get("escenas", [])
        musica = datos.get("musica", {})

        lineas = [
            f"# Brief CapCut — {datos.get('nombre_pieza', entrada.concepto[:40])}",
            f"",
            f"**Fecha:** {entrada.fecha}  ",
            f"**Hora de publicación:** {entrada.hora_publicacion}  ",
            f"**Tipo:** {entrada.tipo_contenido.upper()}  ",
            f"**Duración total:** {datos.get('duracion_total_seg', 25)} segundos  ",
            f"**Formato:** 9:16 vertical (1080×1920px)  ",
            f"",
            f"---",
            f"",
            f"## Hook — primeros 3 segundos",
            f"",
            f"> {datos.get('hook_primeros_3_seg', '')}",
            f"",
            f"---",
            f"",
            f"## Escenas",
            f"",
        ]

        for i, escena in enumerate(escenas, 1):
            lineas += [
                f"### Escena {escena.get('numero', i)} — {escena.get('duracion_seg', 4)}s",
                f"",
                f"- **Visual:** {escena.get('descripcion_visual', '')}",
                f"- **Material:** `{escena.get('material_a_usar', '')}`",
                f"- **Texto en pantalla:** {escena.get('texto_en_pantalla', '')}",
                f"- **Posición texto:** {escena.get('posicion_texto', 'bottom')}",
                f"- **Fuente:** {escena.get('fuente', 'Impact')} — {escena.get('tamano_fuente', 'grande')}",
                f"- **Transición de salida:** {escena.get('tipo_transicion_salida', 'fade')}",
                f"",
            ]

        lineas += [
            f"---",
            f"",
            f"## Música",
            f"",
            f"- **Mood:** {musica.get('mood', '')}",
            f"- **Volumen:** {musica.get('volumen_pct', 25)}%",
            f"- **Fade in:** {musica.get('fade_in_seg', 1)}s | **Fade out:** {musica.get('fade_out_seg', 1.5)}s",
            f"",
            f"---",
            f"",
            f"## CTA Final",
            f"",
            f"**Texto:** {datos.get('texto_cta_final', '')}",
            f"",
            f"**Color texto:** {datos.get('color_texto_principal', '#FFFFFF')}",
            f"",
        ]

        efectos = datos.get("efectos_adicionales", [])
        if efectos:
            lineas += [
                f"## Efectos adicionales",
                f"",
            ] + [f"- {ef}" for ef in efectos] + [""]

        notas = datos.get("notas_editor", "")
        if notas:
            lineas += [
                f"## Notas para el editor",
                f"",
                f"{notas}",
                f"",
            ]

        lineas += [
            f"---",
            f"*Generado automáticamente el {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        ]

        ruta.parent.mkdir(exist_ok=True)
        ruta.write_text("\n".join(lineas), encoding="utf-8")
        return ruta
