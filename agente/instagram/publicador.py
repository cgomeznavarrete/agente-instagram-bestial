"""
Publica Posts, Carruseles, Reels y Stories en Instagram via Graph API.
Todos los tipos de contenido son 100% automáticos — no requiere acción humana.
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import settings
from agente.memoria.modelos import EntradaCalendario
from agente.instagram import cliente_api
from agente.media import subidor_cloudinary, subidor_imgbb

logger = logging.getLogger(__name__)


@dataclass
class ResultadoPublicacion:
    exito: bool
    instagram_media_id: str = ""
    error: str = ""
    url_cloudinary: str = ""


class Publicador:
    """Orquesta el flujo completo de publicación para cada tipo de contenido."""

    def publicar(self, entrada: EntradaCalendario) -> ResultadoPublicacion:
        tipo = entrada.tipo_contenido.lower()

        if tipo == "post":
            return self._publicar_post(entrada)
        elif tipo == "carrusel":
            return self._publicar_carrusel(entrada)
        elif tipo == "reel":
            return self._publicar_reel(entrada)
        elif tipo in {"story", "story_video"}:
            return self._publicar_story(entrada)
        else:
            return ResultadoPublicacion(exito=False, error=f"Tipo desconocido: {tipo}")

    # ── Post (imagen única) ───────────────────────────────────────────────────

    def _publicar_post(self, entrada: EntradaCalendario) -> ResultadoPublicacion:
        imagen_path = self._resolver_imagen(entrada)
        if not imagen_path:
            return ResultadoPublicacion(exito=False, error="No se encontró imagen para el post")

        url = subidor_imgbb.subir_imagen(imagen_path)
        if not url:
            return ResultadoPublicacion(exito=False, error="Error subiendo imagen a imgbb")

        caption = self._construir_caption(entrada)

        try:
            creation_id = cliente_api.crear_contenedor_imagen(url, caption)
            media_id = cliente_api.publicar_contenedor(creation_id)
            logger.info("Post publicado: media_id=%s", media_id)
            return ResultadoPublicacion(exito=True, instagram_media_id=media_id)
        except cliente_api.ErrorInstagram as e:
            return ResultadoPublicacion(exito=False, error=str(e))

    # ── Carrusel ─────────────────────────────────────────────────────────────

    def _publicar_carrusel(self, entrada: EntradaCalendario) -> ResultadoPublicacion:
        imagenes = self._resolver_imagenes_carrusel(entrada)
        if not imagenes:
            return ResultadoPublicacion(exito=False, error="No se encontraron imágenes para el carrusel")
        if len(imagenes) < 2:
            return ResultadoPublicacion(exito=False, error="El carrusel necesita mínimo 2 imágenes")

        urls = subidor_imgbb.subir_imagenes(imagenes[:10])
        if len(urls) < 2:
            return ResultadoPublicacion(exito=False, error="No se pudieron subir suficientes imágenes")

        try:
            item_ids = [cliente_api.crear_contenedor_carrusel_item(url) for url in urls]
            caption = self._construir_caption(entrada)
            creation_id = cliente_api.crear_contenedor_carrusel(item_ids, caption)
            media_id = cliente_api.publicar_contenedor(creation_id)
            logger.info("Carrusel publicado: media_id=%s (%d imágenes)", media_id, len(item_ids))
            return ResultadoPublicacion(exito=True, instagram_media_id=media_id)
        except cliente_api.ErrorInstagram as e:
            return ResultadoPublicacion(exito=False, error=str(e))

    # ── Reel ─────────────────────────────────────────────────────────────────

    def _publicar_reel(self, entrada: EntradaCalendario) -> ResultadoPublicacion:
        video_path = self._resolver_video(entrada)
        if not video_path:
            return ResultadoPublicacion(exito=False, error="No se encontró video MP4 para el Reel")

        url_video = subidor_cloudinary.subir_video(
            video_path,
            public_id=f"reels/{entrada.id}",
        )
        if not url_video:
            return ResultadoPublicacion(exito=False, error="Error subiendo video a Cloudinary")

        caption = self._construir_caption(entrada)

        try:
            creation_id = cliente_api.crear_contenedor_video(url_video, caption, media_type="REELS")
            listo = cliente_api.esperar_video_listo(creation_id, max_intentos=30, intervalo=10)
            if not listo:
                return ResultadoPublicacion(exito=False, error="El video no terminó de procesarse en Meta")

            media_id = cliente_api.publicar_contenedor(creation_id)
            logger.info("Reel publicado: media_id=%s", media_id)
            return ResultadoPublicacion(exito=True, instagram_media_id=media_id, url_cloudinary=url_video)
        except cliente_api.ErrorInstagram as e:
            return ResultadoPublicacion(exito=False, error=str(e))

    # ── Story ─────────────────────────────────────────────────────────────────

    def _publicar_story(self, entrada: EntradaCalendario) -> ResultadoPublicacion:
        # Las Stories pueden ser video o imagen estática
        video_path = self._resolver_video(entrada)

        if video_path:
            url_video = subidor_cloudinary.subir_video(
                video_path,
                public_id=f"stories/{entrada.id}",
            )
            if not url_video:
                return ResultadoPublicacion(exito=False, error="Error subiendo story video a Cloudinary")

            caption = self._construir_caption(entrada)

            try:
                creation_id = cliente_api.crear_contenedor_video(url_video, caption, media_type="STORIES")
                listo = cliente_api.esperar_video_listo(creation_id, max_intentos=20, intervalo=10)
                if not listo:
                    return ResultadoPublicacion(exito=False, error="Story video no terminó de procesarse")

                media_id = cliente_api.publicar_contenedor(creation_id)
                logger.info("Story (video) publicada: media_id=%s", media_id)
                return ResultadoPublicacion(exito=True, instagram_media_id=media_id, url_cloudinary=url_video)
            except cliente_api.ErrorInstagram as e:
                return ResultadoPublicacion(exito=False, error=str(e))

        else:
            # Story de imagen estática
            imagen_path = self._resolver_imagen(entrada)
            if not imagen_path:
                return ResultadoPublicacion(exito=False, error="No se encontró imagen ni video para la Story")

            url = subidor_imgbb.subir_imagen(imagen_path)
            if not url:
                return ResultadoPublicacion(exito=False, error="Error subiendo imagen de story a imgbb")

            try:
                creation_id = cliente_api.crear_contenedor_imagen(url, "")
                media_id = cliente_api.publicar_contenedor(creation_id)
                logger.info("Story (imagen) publicada: media_id=%s", media_id)
                return ResultadoPublicacion(exito=True, instagram_media_id=media_id)
            except cliente_api.ErrorInstagram as e:
                return ResultadoPublicacion(exito=False, error=str(e))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _construir_caption(self, entrada: EntradaCalendario) -> str:
        copy = entrada.contenido_copy
        if not copy:
            return ""
        partes = []
        if copy.hook:
            partes.append(copy.hook)
        if copy.cuerpo:
            partes.append(copy.cuerpo)
        if copy.cta:
            partes.append(copy.cta)
        if copy.hashtags:
            partes.append("  ".join(copy.hashtags))
        return "\n\n".join(partes)

    def _resolver_imagen(self, entrada: EntradaCalendario) -> Optional[Path]:
        """Busca la imagen a usar: generada primero, luego material sugerido."""
        if entrada.imagen_compuesta_path:
            p = Path(entrada.imagen_compuesta_path)
            if p.exists():
                return p

        if entrada.material_sugerido:
            for ruta_rel in entrada.material_sugerido:
                p = settings.BASE_DIR / ruta_rel
                if p.exists() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                    return p

        return None

    def _resolver_video(self, entrada: EntradaCalendario) -> Optional[Path]:
        """Busca el video MP4 generado."""
        if entrada.video_generado_path:
            p = Path(entrada.video_generado_path)
            if p.exists() and p.suffix.lower() == ".mp4":
                return p
        return None

    def _resolver_imagenes_carrusel(self, entrada: EntradaCalendario) -> list[Path]:
        """Para carruseles, devuelve hasta 10 imágenes para publicar.
        Prioridad: imagenes_carrusel_paths (generadas por el agente) > material_sugerido.
        """
        imagenes = []
        extensiones = {".jpg", ".jpeg", ".png", ".webp"}

        # Primero: slides generados automáticamente (Camino B)
        for ruta_str in (entrada.imagenes_carrusel_paths or []):
            p = Path(ruta_str)
            if p.exists() and p.suffix.lower() in extensiones:
                imagenes.append(p)

        # Fallback: material_sugerido por el usuario
        if not imagenes:
            for ruta_rel in (entrada.material_sugerido or []):
                p = settings.BASE_DIR / ruta_rel
                if p.exists() and p.suffix.lower() in extensiones:
                    imagenes.append(p)

        return imagenes[:10]
