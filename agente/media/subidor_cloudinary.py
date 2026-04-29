"""
Sube videos MP4 a Cloudinary y retorna una URL pública permanente.
Cloudinary es requerido porque Instagram Graph API necesita una URL HTTPS accesible.
Free tier: 25GB storage + 25GB bandwidth/mes.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def subir_video(ruta_video: Path, public_id: str | None = None) -> str | None:
    """
    Sube un MP4 a Cloudinary.

    public_id: nombre sin extensión para el video en Cloudinary.
               Si es None, Cloudinary genera uno automático.
    Retorna la URL HTTPS del video o None si falla.
    """
    try:
        import cloudinary
        import cloudinary.uploader
        from config import settings

        # cloudinary.config() lee automáticamente CLOUDINARY_URL del entorno
        # si no está configurado explícitamente
        if settings.CLOUDINARY_URL:
            cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL)
        else:
            logger.error("CLOUDINARY_URL no configurada en .env")
            return None

        opciones: dict = {
            "resource_type": "video",
            "folder": "salsas_bestial",
            "overwrite": True,
        }
        if public_id:
            opciones["public_id"] = public_id

        logger.info("Subiendo video a Cloudinary: %s (%.1f MB)", ruta_video.name, ruta_video.stat().st_size / 1_048_576)
        resultado = cloudinary.uploader.upload(str(ruta_video), **opciones)
        url = resultado.get("secure_url")
        logger.info("Video subido: %s", url)
        return url

    except ImportError:
        logger.error("cloudinary no instalado. Ejecuta: pip install cloudinary")
        return None
    except Exception as e:
        logger.error("Error subiendo video a Cloudinary: %s", e)
        return None


class SubidorCloudinary:
    """Wrapper de clase para subir imágenes y videos a Cloudinary."""

    def subir(self, ruta: Path, resource_type: str = "auto") -> str | None:
        """Sube imagen o video. resource_type='auto' detecta automáticamente."""
        try:
            import cloudinary
            import cloudinary.uploader
            from config import settings

            if settings.CLOUDINARY_URL:
                cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL)
            else:
                logger.error("CLOUDINARY_URL no configurada en .env")
                return None

            resultado = cloudinary.uploader.upload(
                str(ruta),
                folder="salsas_bestial",
                resource_type=resource_type,
                overwrite=True,
            )
            url = resultado.get("secure_url")
            logger.info("Subido a Cloudinary: %s", url)
            return url
        except Exception as e:
            logger.error("Error subiendo a Cloudinary: %s", e)
            return None


def eliminar_video(public_id: str) -> bool:
    """Elimina un video de Cloudinary. Usar 48h después de publicado."""
    try:
        import cloudinary.uploader
        resultado = cloudinary.uploader.destroy(public_id, resource_type="video")
        return resultado.get("result") == "ok"
    except Exception as e:
        logger.warning("No se pudo eliminar video %s de Cloudinary: %s", public_id, e)
        return False
