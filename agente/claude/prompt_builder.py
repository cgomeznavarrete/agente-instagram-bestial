"""
Motor de construcción de prompts usando plantillas Jinja2.
Construye el bloque estático de brand context (para caching) y los prompts dinámicos.
"""

from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from config import settings
from config import brand_guidelines as brand


_env = Environment(
    loader=FileSystemLoader(str(settings.PROMPTS_DIR)),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def construir_contexto_marca() -> str:
    """
    Bloque estático de brand guidelines. Se usa como system prompt cacheado.
    Mismo texto para todas las llamadas de la semana → máximo ahorro de tokens.
    """
    return f"""Eres el agente de contenido de {brand.NOMBRE_MARCA}.

IDENTIDAD DE MARCA:
{brand.PERSONALIDAD}

TONO DE VOZ:
{brand.TONO_VOZ}

AUDIENCIA OBJETIVO:
{brand.AUDIENCIA_OBJETIVO}

PILARES DE CONTENIDO:
{chr(10).join(f'- {p.replace("_", " ").title()}' for p in brand.PILARES_CONTENIDO)}

PRODUCTOS DISPONIBLES:
{chr(10).join(f'- Salsa {s}' for s in brand.SABORES_DISPONIBLES)}

CANALES DE VENTA:
{chr(10).join(f'- {c}' for c in brand.CANALES_VENTA)}

PROHIBICIONES ABSOLUTAS (NUNCA violar):
{chr(10).join(f'- {p}' for p in brand.PROHIBICIONES_MARCA)}

{brand.REGLAS_COPY_HUMANO}

FORMATO DE RESPUESTA: Siempre responde con JSON válido según el esquema solicitado.
"""


def renderizar(plantilla: str, **kwargs) -> str:
    """Renderiza una plantilla Jinja2 con los datos proporcionados."""
    tmpl = _env.get_template(plantilla)
    return tmpl.render(**kwargs)


def prompt_calendario(
    semana: str,
    metricas_previas: dict,
    material_disponible: dict,
    campanas_activas: list,
    historial_resumido: list,
    posts_semana: int,
    reels_semana: int,
    stories_semana: int,
    carruseles_semana: int,
    reel_ganador_concepto: str = "",
) -> str:
    return renderizar(
        "calendario_semanal.j2",
        semana=semana,
        metricas_previas=metricas_previas,
        material_disponible=material_disponible,
        campanas_activas=campanas_activas,
        historial_resumido=historial_resumido,
        posts_semana=posts_semana,
        reels_semana=reels_semana,
        stories_semana=stories_semana,
        carruseles_semana=carruseles_semana,
        reel_ganador_concepto=reel_ganador_concepto,
    )


def prompt_copy(tipo: str, entrada: dict, historial_copies: list) -> str:
    plantilla_map = {
        "post": "copy_post.j2",
        "reel": "copy_reel.j2",
        "story": "copy_story.j2",
        "story_video": "copy_story.j2",
        "carrusel": "copy_carrusel.j2",
        "poster": "copy_post.j2",
    }
    plantilla = plantilla_map.get(tipo, "copy_post.j2")
    return renderizar(plantilla, entrada=entrada, historial_copies=historial_copies)


def prompt_brief_capcut(entrada: dict, material_disponible: list) -> str:
    return renderizar(
        "brief_capcut.j2",
        entrada=entrada,
        material_disponible=material_disponible,
    )


def prompt_analisis_metricas(metricas: dict, historial: list) -> str:
    return renderizar(
        "analisis_metricas.j2",
        metricas=metricas,
        historial=historial,
    )
