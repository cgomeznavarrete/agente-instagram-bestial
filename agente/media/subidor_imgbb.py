"""
Sube imágenes a imgbb.com y retorna una URL pública.
imgbb es gratuito (hasta 32MB por imagen) y no requiere tarjeta de crédito.
"""

import base64
import logging
from pathlib import Path

import requests

from config import settings

logger = logging.getLogger(__name__)

IMGBB_API_URL = "https://api.imgbb.com/1/upload"
# Las imágenes se eliminan automáticamente tras 48h (suficiente para publicar en IG)
EXPIRACION_SEGUNDOS = 172800  # 48 horas


def subir_imagen(ruta_imagen: Path) -> str | None:
    """
    Sube una imagen a imgbb.

    Retorna la URL directa de la imagen (display_url) o None si falla.
    La URL expira en 48h — solo se necesita durante la publicación en Instagram.
    """
    if not settings.IMGBB_API_KEY:
        logger.error("IMGBB_API_KEY no configurada en .env")
        return None

    if not ruta_imagen.exists():
        logger.error("Imagen no encontrada: %s", ruta_imagen)
        return None

    try:
        with open(ruta_imagen, "rb") as f:
            imagen_b64 = base64.b64encode(f.read()).decode("utf-8")

        logger.info("Subiendo imagen a imgbb: %s (%.1f KB)", ruta_imagen.name, ruta_imagen.stat().st_size / 1024)

        resp = requests.post(
            IMGBB_API_URL,
            params={"key": settings.IMGBB_API_KEY, "expiration": EXPIRACION_SEGUNDOS},
            data={"image": imagen_b64},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()

        if not body.get("success"):
            logger.error("imgbb rechazó la imagen: %s", body)
            return None

        url = body["data"]["display_url"]
        logger.info("Imagen subida: %s", url)
        return url

    except Exception as e:
        logger.error("Error subiendo imagen a imgbb: %s", e)
        return None


def subir_imagenes(rutas: list[Path]) -> list[str]:
    """Sube múltiples imágenes y retorna solo las URLs que tuvieron éxito."""
    urls = []
    for ruta in rutas:
        url = subir_imagen(ruta)
        if url:
            urls.append(url)
    return urls
