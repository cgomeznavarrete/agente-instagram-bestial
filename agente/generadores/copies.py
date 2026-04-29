"""
Genera copies completos para cada entrada del calendario:
hook, cuerpo, CTA, hashtags y (para reels) guion de video.
"""

import json
import logging
from pathlib import Path

from config import settings
from agente.claude.cliente_claude import ClienteClaude
from agente.claude.prompt_builder import construir_contexto_marca, prompt_copy
from agente.memoria import gestor_memoria as memoria
from agente.memoria.modelos import EntradaCalendario, CopyContenido

logger = logging.getLogger(__name__)


def _historial_copies_recientes() -> list[dict]:
    """Retorna los hooks de los últimos copies para evitar repetición."""
    pubs = memoria.obtener_publicaciones_recientes(semanas=4)
    resultado = []
    for p in pubs:
        c = p.contenido_copy
        if c:
            resultado.append({"hook": c.hook, "tipo": p.tipo})
    return resultado[-10:]


def _guardar_copy_json(entrada: EntradaCalendario, datos: dict) -> Path:
    """Guarda el copy generado como JSON en material_agente/copies/."""
    semana = entrada.fecha.strftime("%Y-W%V")
    carpeta = settings.MATERIAL_AGENTE_DIR / "copies" / f"semana_{semana}"
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / f"{entrada.tipo_contenido}_{entrada.id}.json"
    with open(archivo, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    return archivo


class GeneradorCopies:

    def __init__(self):
        self._claude = ClienteClaude()
        self._contexto_marca = construir_contexto_marca()

    def generar(self, entrada: EntradaCalendario) -> CopyContenido:
        """Genera el copy para una entrada del calendario."""
        historial = _historial_copies_recientes()
        temperatura = settings.TEMPERATURAS_CLAUDE.get(
            f"copy_{entrada.tipo_contenido}",
            settings.TEMPERATURAS_CLAUDE["copy_post"],
        )

        entrada_dict = {
            "tipo_contenido": entrada.tipo_contenido,
            "pilar": entrada.pilar,
            "objetivo": entrada.objetivo,
            "concepto": entrada.concepto,
        }

        prompt_u = prompt_copy(
            tipo=entrada.tipo_contenido,
            entrada=entrada_dict,
            historial_copies=historial,
        )

        datos = self._claude.generar_json(
            prompt_sistema=self._contexto_marca,
            prompt_usuario=prompt_u,
            temperatura=temperatura,
        )

        _guardar_copy_json(entrada, datos)

        # Para reels, el copy puede tener estructura diferente (guion_video)
        # Normalizamos a CopyContenido extrayendo los campos estándar
        hook = datos.get("hook", "")
        cuerpo = datos.get("caption") or datos.get("cuerpo", "")
        cta = datos.get("cta", "")
        hashtags = datos.get("hashtags", [])

        # Guardar datos extras (guion, escenas, etc.) en notas si existen
        extras = {k: v for k, v in datos.items()
                  if k not in ("hook", "caption", "cuerpo", "cta", "hashtags")}
        if extras:
            logger.debug("Copy extras para %s: %s", entrada.id, list(extras.keys()))

        copy = CopyContenido(
            hook=hook,
            cuerpo=cuerpo,
            cta=cta,
            hashtags=hashtags,
        )

        logger.info("Copy generado: %s %s — hook: %.60s", entrada.tipo_contenido, entrada.id, hook)
        return copy
