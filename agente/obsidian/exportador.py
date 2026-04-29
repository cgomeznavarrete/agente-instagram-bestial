"""
Exporta el contenido generado a la bóveda Obsidian-Instagram-Bestial.
Cada pieza del calendario se convierte en una nota Markdown con frontmatter.
El usuario aprueba cambiando status: generado → status: aprobado en Obsidian.
"""

import logging
from datetime import datetime
from pathlib import Path

from config import settings
from agente.memoria.modelos import CalendarioSemanal, EntradaCalendario, CopyContenido

logger = logging.getLogger(__name__)


def _asegurar_estructura_vault():
    """Crea las carpetas base de la bóveda si no existen."""
    carpetas = [
        settings.OBSIDIAN_VAULT_PATH / "Semanas",
        settings.OBSIDIAN_VAULT_PATH / "Metricas",
        settings.OBSIDIAN_VAULT_PATH / "Campanas",
    ]
    for c in carpetas:
        c.mkdir(parents=True, exist_ok=True)


def exportar_calendario(calendario: CalendarioSemanal) -> list[Path]:
    """
    Exporta todas las entradas del calendario como notas individuales en Obsidian.
    Retorna las rutas de los archivos creados.
    """
    _asegurar_estructura_vault()
    carpeta_semana = settings.OBSIDIAN_VAULT_PATH / "Semanas" / calendario.semana
    carpeta_semana.mkdir(parents=True, exist_ok=True)

    rutas = []

    # Nota índice de la semana
    ruta_indice = carpeta_semana / "📅 Calendario.md"
    ruta_indice.write_text(
        _construir_indice_semana(calendario),
        encoding="utf-8",
    )
    rutas.append(ruta_indice)

    # Una nota por entrada
    for entrada in calendario.entradas:
        ruta_nota = carpeta_semana / _nombre_nota(entrada)
        ruta_nota.write_text(
            _construir_nota_entrada(entrada),
            encoding="utf-8",
        )
        rutas.append(ruta_nota)

    logger.info(
        "Exportado a Obsidian: semana %s, %d notas en %s",
        calendario.semana, len(rutas), carpeta_semana,
    )
    return rutas


def _nombre_nota(entrada: EntradaCalendario) -> str:
    dia = entrada.dia.capitalize()
    tipo = entrada.tipo_contenido.upper()
    return f"{entrada.fecha} {dia} - {tipo} {entrada.id}.md"


def _construir_nota_entrada(entrada: EntradaCalendario) -> str:
    """Construye el Markdown de la nota de una pieza de contenido."""
    copy: CopyContenido | None = entrada.contenido_copy

    hashtags_str = ""
    if copy and copy.hashtags:
        hashtags_str = "  ".join(copy.hashtags)

    video_path = entrada.video_generado_path or ""
    imagen_path = entrada.imagen_compuesta_path or ""
    brief_path = entrada.brief_capcut_path or ""

    lineas = [
        "---",
        f"id: {entrada.id}",
        f"tipo: {entrada.tipo_contenido}",
        f"fecha: {entrada.fecha}",
        f"hora: {entrada.hora_publicacion}",
        f"dia: {entrada.dia}",
        f"pilar: {entrada.pilar}",
        f"objetivo: {entrada.objetivo}",
        f"status: generado",
        f"publicado: false",
        f"instagram_media_id: \"\"",
        "---",
        "",
        f"# {entrada.tipo_contenido.upper()} — {entrada.concepto[:60]}",
        "",
        f"> **Publicar:** {entrada.fecha} a las {entrada.hora_publicacion}",
        "",
        "---",
        "",
    ]

    if copy:
        lineas += [
            "## Hook",
            "",
            f"**{copy.hook}**",
            "",
            "## Copy completo",
            "",
            copy.cuerpo,
            "",
            "## CTA",
            "",
            f"_{copy.cta}_",
            "",
            "## Hashtags",
            "",
            hashtags_str,
            "",
            "---",
            "",
        ]
    else:
        lineas += [
            "## Copy",
            "",
            "> *Copy aún no generado. Ejecuta: `python main.py generar-copies`*",
            "",
            "---",
            "",
        ]

    lineas += ["## Material", ""]

    if video_path:
        lineas += [f"**Video generado:** `{video_path}`", ""]
    if imagen_path:
        lineas += [f"**Imagen compuesta:** `{imagen_path}`", ""]
    if brief_path:
        lineas += [f"**Brief CapCut:** [[{Path(brief_path).stem}]]", ""]
    if not video_path and not imagen_path:
        lineas += ["> *Material aún no generado.*", ""]

    if entrada.material_sugerido:
        lineas += ["**Material sugerido:**", ""]
        for m in entrada.material_sugerido[:5]:
            lineas.append(f"- `{m}`")
        lineas.append("")

    lineas += [
        "---",
        "",
        "## Aprobacion",
        "",
        "Cambia el campo `status` en las propiedades de esta nota:",
        "",
        "- `generado` → revisión pendiente",
        "- `aprobado` → listo para publicar automáticamente",
        "- `rechazado` → no publicar",
        "",
        f"*Generado el {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
    ]

    return "\n".join(lineas)


def _construir_indice_semana(calendario: CalendarioSemanal) -> str:
    """Construye la nota índice de la semana con tabla resumen."""
    lineas = [
        f"# Semana {calendario.semana}",
        "",
        f"**Del {calendario.fecha_inicio} al {calendario.fecha_fin}**",
        "",
    ]

    if calendario.notas_estrategia:
        lineas += [
            "## Estrategia de la semana",
            "",
            calendario.notas_estrategia,
            "",
        ]

    lineas += [
        "## Calendario",
        "",
        "| Día | Hora | Tipo | Pilar | Estado |",
        "|-----|------|------|-------|--------|",
    ]

    for e in calendario.entradas:
        tipo = e.tipo_contenido.upper()
        pilar = e.pilar.replace("_", " ").title()[:25]
        lineas.append(
            f"| {e.dia.capitalize()} | {e.hora_publicacion} | {tipo} | {pilar} | {e.estado} |"
        )

    lineas += [
        "",
        "---",
        "",
        "## Piezas",
        "",
    ]
    for e in calendario.entradas:
        lineas.append(f"- [[{_nombre_nota(e)[:-3]}]]")

    lineas += [
        "",
        f"*Calendario generado el {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
    ]

    return "\n".join(lineas)


def exportar_reporte_metricas(reporte: str, semana: str) -> Path:
    """Exporta un reporte de métricas como nota Obsidian."""
    _asegurar_estructura_vault()
    ruta = settings.OBSIDIAN_VAULT_PATH / "Metricas" / f"Reporte {semana}.md"
    ruta.write_text(reporte, encoding="utf-8")
    logger.info("Reporte de métricas exportado a Obsidian: %s", ruta.name)
    return ruta
