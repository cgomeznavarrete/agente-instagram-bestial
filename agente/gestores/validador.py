"""
Valida formatos, dimensiones y restricciones de marca antes de publicar.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DIMENSIONES_MINIMAS = {
    "post": (1080, 1080),
    "carrusel": (1080, 1080),
    "story": (1080, 1920),
    "story_video": (1080, 1920),
    "reel": (1080, 1920),
}

FORMATOS_VALIDOS_IMAGEN = {".jpg", ".jpeg", ".png", ".webp"}
FORMATOS_VALIDOS_VIDEO = {".mp4", ".mov"}


def validar_imagen(ruta: Path, tipo_contenido: str = "post") -> tuple[bool, str]:
    """
    Valida que una imagen cumple los requisitos para Instagram.
    Retorna (es_valida, mensaje).
    """
    try:
        from PIL import Image
    except ImportError:
        return True, "Pillow no instalado — validación omitida"

    if not ruta.exists():
        return False, f"Archivo no encontrado: {ruta}"

    if ruta.suffix.lower() not in FORMATOS_VALIDOS_IMAGEN:
        return False, f"Formato no válido: {ruta.suffix}"

    try:
        with Image.open(ruta) as img:
            ancho, alto = img.size
            min_ancho, min_alto = DIMENSIONES_MINIMAS.get(tipo_contenido, (320, 320))
            if ancho < min_ancho or alto < min_alto:
                return False, (
                    f"Resolución insuficiente: {ancho}x{alto}px "
                    f"(mínimo {min_ancho}x{min_alto}px para {tipo_contenido})"
                )
            return True, f"OK — {ancho}x{alto}px"
    except Exception as e:
        return False, f"Error leyendo imagen: {e}"


def validar_video(ruta: Path) -> tuple[bool, str]:
    """Validación básica de archivo de video."""
    if not ruta.exists():
        return False, f"Archivo no encontrado: {ruta}"
    if ruta.suffix.lower() not in FORMATOS_VALIDOS_VIDEO:
        return False, f"Formato no válido: {ruta.suffix}"
    if ruta.stat().st_size < 1024:
        return False, "Archivo de video vacío o corrupto"
    return True, "OK"


def es_archivo_producto(ruta: Path) -> bool:
    """Detecta si un archivo proviene de referencia_producto/."""
    from config import settings
    try:
        ruta.relative_to(settings.REFERENCIA_PRODUCTO_DIR)
        return True
    except ValueError:
        return False


def validar_no_modificado(ruta_original: Path, ruta_procesada: Path) -> tuple[bool, str]:
    """
    Verifica que el archivo procesado no tiene dimensiones menores al original
    (señal de recorte no autorizado). Solo compara tamaño de archivo como heurística rápida.
    """
    if not ruta_original.exists() or not ruta_procesada.exists():
        return False, "Uno de los archivos no existe"
    tam_original = ruta_original.stat().st_size
    tam_procesado = ruta_procesada.stat().st_size
    if tam_procesado < tam_original * 0.1:
        return False, "El archivo procesado es sospechosamente pequeño vs el original"
    return True, "OK"
