"""
Publicación directa de un item de la biblioteca en Instagram.
Usado por main.py (CLI) y por bot.py (Telegram).

Política de música:
  - Posts de imagen y Carruseles → se convierten a Reel MP4 con música antes de publicar.
    La Instagram Graph API no permite agregar música a imágenes estáticas vía API.
  - Reels y Stories de video → música embebida en el MP4 generado.
"""
import logging
import time
from pathlib import Path

import requests as req
import cloudinary
import cloudinary.uploader

from config import settings
from config.imagen_params import MOOD_POR_PILAR
from agente.gestores.biblioteca import marcar_publicado

logger = logging.getLogger(__name__)


def _publicar_video_como_reel(url_video: str, caption: str) -> str | None:
    """
    Crea container de Reel → polling FINISHED → media_publish.
    Retorna media_id o None.
    """
    r1 = req.post(
        f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
        data={
            "video_url": url_video,
            "media_type": "REELS",
            "caption": caption,
            "share_to_feed": "true",
            "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
        },
        timeout=120,
    )
    if r1.status_code != 200:
        logger.error("Error creando container reel: %s", r1.text)
        return None

    creation_id = r1.json()["id"]
    procesado = False
    for _ in range(18):
        time.sleep(10)
        st = req.get(
            f"https://graph.facebook.com/v21.0/{creation_id}",
            params={"fields": "status_code", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
            timeout=30,
        ).json().get("status_code", "")
        if st == "FINISHED":
            procesado = True
            break
        if st == "ERROR":
            logger.error("Error procesando reel en Instagram")
            return None

    if not procesado:
        logger.error("Timeout esperando reel FINISHED — abortando")
        return None

    r2 = req.post(
        f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
        timeout=60,
    )
    if r2.status_code != 200:
        logger.error("Error media_publish reel: %s", r2.text)
        return None
    return r2.json().get("id")


def _imagen_a_reel_cloudinary(ruta_local: Path, pilar: str) -> str | None:
    """
    Convierte imagen a MP4 Reel con música y lo sube a Cloudinary.
    Retorna la URL pública del video, o None si falla.
    """
    try:
        from agente.generadores.video_automatico import imagen_a_reel
        import random
        mood = MOOD_POR_PILAR.get(pilar or "", None) or random.choice(["chill_food", "upbeat_latino"])
        ruta_video = imagen_a_reel(ruta_local, mood_musica=mood, duracion=20)
        if not ruta_video or not ruta_video.exists():
            return None
        return cloudinary.uploader.upload(
            str(ruta_video), folder="salsas_bestial", resource_type="video"
        )["secure_url"]
    except Exception as e:
        logger.warning("No se pudo convertir imagen a reel: %s", e)
        return None


def _carrusel_slides_a_reel_cloudinary(rutas_slides: list, pilar: str) -> str | None:
    """
    Convierte lista de slides de carrusel a MP4 Reel con música y lo sube a Cloudinary.
    Retorna la URL pública del video, o None si falla.
    """
    try:
        from agente.generadores.video_automatico import carrusel_a_reel
        import random
        mood = MOOD_POR_PILAR.get(pilar or "", None) or random.choice(["chill_food", "upbeat_latino"])
        ruta_video = carrusel_a_reel(rutas_slides, mood_musica=mood)
        if not ruta_video or not ruta_video.exists():
            return None
        return cloudinary.uploader.upload(
            str(ruta_video), folder="salsas_bestial", resource_type="video"
        )["secure_url"]
    except Exception as e:
        logger.warning("No se pudo convertir carrusel a reel: %s", e)
        return None


def publicar_item(item) -> str | None:
    """
    Publica un item de la biblioteca en Instagram.
    Retorna media_id si tuvo éxito, None si falló.
    item: objeto con atributos: tipo, nombre_archivo, ruta_local, cloudinary_url,
          caption, es_carrusel, archivos_carrusel, pilar
    """
    cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL)
    tipo_pub = item.tipo
    cloudinary_url = getattr(item, "cloudinary_url", "") or ""
    ruta = Path(item.ruta_local) if getattr(item, "ruta_local", None) else None
    if ruta and not ruta.exists():
        ruta = None

    # Detectar sin media antes de intentar nada
    if not cloudinary_url and not ruta and not getattr(item, "archivos_carrusel", None):
        logger.error(
            "Item %s (%s) no tiene archivo local ni cloudinary_url — marcando como sin_media",
            item.id, item.tipo,
        )
        return "SIN_MEDIA"

    media_id = None

    # ── CARRUSEL ──────────────────────────────────────────────────────────────
    # Los carruseles se publican como estáticos (sin música).
    # El usuario los publica manualmente desde la app de Instagram para agregarles música.
    # Si llega aquí desde publicar_pendientes es porque el usuario ya lo aprobó para publicar sin música.
    if item.es_carrusel:
        urls_guardadas = [u for u in (cloudinary_url or "").split(",") if u.startswith("http")]
        rutas_slides = [Path(r) for r in (getattr(item, "archivos_carrusel", None) or [])]
        creation_ids = []
        for i, slide_ruta in enumerate(rutas_slides):
            if i < len(urls_guardadas):
                url_slide = urls_guardadas[i]
            elif slide_ruta.exists():
                url_slide = cloudinary.uploader.upload(str(slide_ruta), folder="salsas_bestial")["secure_url"]
            else:
                logger.warning("Slide %d no encontrado", i)
                continue
            r_c = req.post(
                f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
                data={"image_url": url_slide, "is_carousel_item": "true", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=60,
            )
            if r_c.status_code == 200:
                creation_ids.append(r_c.json()["id"])
            else:
                logger.error("Error slide carrusel: %s", r_c.text)
        if not creation_ids:
            logger.error("No se pudieron subir slides al carrusel")
            return None
        r_car = req.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(creation_ids),
                "caption": item.caption,
                "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
            }, timeout=60,
        )
        if r_car.status_code != 200:
            logger.error("Error creando container carrusel: %s", r_car.text)
            return None
        r_pub = req.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
            data={"creation_id": r_car.json()["id"], "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
            timeout=60,
        )
        media_id = r_pub.json().get("id") if r_pub.status_code == 200 else None
        if not media_id:
            logger.error("Error publicando carrusel: %s", r_pub.text)
        return media_id

    # ── REEL ──────────────────────────────────────────────────────────────────
    if tipo_pub == "reel":
        pilar_item = getattr(item, "pilar", "") or ""
        # Detectar si el archivo es imagen (jpg/png) — si lo es, convertir a MP4 con música
        es_imagen_reel = any(
            item.nombre_archivo.lower().endswith(e)
            for e in (".jpg", ".jpeg", ".png", ".webp")
        )
        # Si es imagen y no hay archivo local → descargar de Cloudinary a temp
        if es_imagen_reel and (not ruta or not ruta.exists()) and cloudinary_url:
            try:
                import tempfile, urllib.request as _urlreq
                sufijo = Path(item.nombre_archivo).suffix or ".jpg"
                tmp = tempfile.NamedTemporaryFile(suffix=sufijo, delete=False)
                _urlreq.urlretrieve(cloudinary_url.split(",")[0].strip(), tmp.name)
                ruta = Path(tmp.name)
                logger.info("Imagen Reel descargada de Cloudinary a temp: %s", tmp.name)
            except Exception as e:
                logger.warning("No se pudo descargar imagen de Cloudinary para reel: %s", e)

        if es_imagen_reel and ruta and ruta.exists():
            logger.info("Reel de imagen — convirtiendo a MP4 con música (pilar=%s)", pilar_item)
            url_video = _imagen_a_reel_cloudinary(ruta, pilar_item)
            if not url_video:
                logger.error("No se pudo convertir imagen a Reel — abortando")
                return None
        elif cloudinary_url and ("/video/" in cloudinary_url or cloudinary_url.lower().endswith((".mp4", ".mov"))):
            url_video = cloudinary_url
        elif ruta and ruta.exists():
            # Archivo local de video
            url_video = cloudinary.uploader.upload(str(ruta), folder="salsas_bestial", resource_type="video")["secure_url"]
        elif cloudinary_url:
            # URL de Cloudinary que no parece video — intentar igual
            logger.warning("cloudinary_url no parece video pero se intentará como Reel: %s", cloudinary_url[:60])
            url_video = cloudinary_url
        else:
            logger.error("Sin video para reel")
            return None
        r1 = req.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
            data={
                "video_url": url_video, "media_type": "REELS",
                "caption": item.caption, "share_to_feed": "true",
                "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
            }, timeout=120,
        )
        if r1.status_code != 200:
            logger.error("Error creando container reel: %s", r1.text)
            return None
        creation_id = r1.json()["id"]
        procesado = False
        for _ in range(18):
            time.sleep(10)
            st = req.get(
                f"https://graph.facebook.com/v21.0/{creation_id}",
                params={"fields": "status_code", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=30,
            ).json().get("status_code", "")
            if st == "FINISHED":
                procesado = True
                break
            if st == "ERROR":
                logger.error("Error procesando reel en Instagram")
                return None
        if not procesado:
            logger.error("Timeout esperando reel FINISHED tras 180s — abortando")
            return None
        r2 = req.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
            data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
            timeout=60,
        )
        if r2.status_code != 200:
            logger.error("Error media_publish reel: %s", r2.text)
            return None
        return r2.json().get("id")

    # ── POST / STORY ──────────────────────────────────────────────────────────
    pilar_item = getattr(item, "pilar", "") or ""
    es_video = any(item.nombre_archivo.lower().endswith(e) for e in (".mp4", ".mov", ".avi", ".m4v"))

    if es_video:
        # Video enviado por el usuario — puede tener música propia → publicar tal cual.
        if cloudinary_url:
            url_video = cloudinary_url
        elif ruta and ruta.exists():
            url_video = cloudinary.uploader.upload(str(ruta), folder="salsas_bestial", resource_type="video")["secure_url"]
        else:
            logger.error("Sin video para story/post")
            return None
        media_data = {
            "video_url": url_video,
            "media_type": "STORIES" if tipo_pub == "story" else "VIDEO",
            "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
        }
    else:
        # Imagen estática → agregar música convirtiéndola a video.
        import random
        import tempfile
        import urllib.request
        mood = MOOD_POR_PILAR.get(pilar_item) or random.choice(["chill_food", "upbeat_latino"])

        # Si no hay archivo local pero sí cloudinary_url de imagen → descargar a temp
        if (not ruta or not ruta.exists()) and cloudinary_url:
            url_img_check = cloudinary_url.split(",")[0].strip()
            es_img_url = not ("/video/" in url_img_check or url_img_check.lower().endswith((".mp4", ".mov", ".m4v")))
            if es_img_url:
                try:
                    sufijo = Path(url_img_check.split("?")[0]).suffix or ".jpg"
                    tmp = tempfile.NamedTemporaryFile(suffix=sufijo, delete=False)
                    urllib.request.urlretrieve(url_img_check, tmp.name)
                    ruta = Path(tmp.name)
                    logger.info("Imagen descargada de Cloudinary a temp: %s", tmp.name)
                except Exception as e:
                    logger.warning("No se pudo descargar imagen de Cloudinary: %s", e)

        if tipo_pub == "post" and ruta and ruta.exists():
            # Post de imagen → Reel con música (más alcance + audio)
            logger.info("Post imagen → convirtiendo a Reel con música (%s)", mood)
            url_video_reel = _imagen_a_reel_cloudinary(ruta, pilar_item)
            if url_video_reel:
                return _publicar_video_como_reel(url_video_reel, item.caption)
            logger.warning("No se pudo convertir imagen a Reel — publicando como post estático")

        if tipo_pub == "story" and ruta and ruta.exists():
            # Story imagen → video con música
            try:
                from agente.generadores.video_automatico import imagen_a_video_story
                ruta_video = imagen_a_video_story(ruta, mood_musica=mood, duracion=15)
                if ruta_video and ruta_video.exists():
                    url_video = cloudinary.uploader.upload(str(ruta_video), folder="salsas_bestial", resource_type="video")["secure_url"]
                    media_data = {"video_url": url_video, "media_type": "STORIES", "access_token": settings.INSTAGRAM_ACCESS_TOKEN}
                else:
                    raise RuntimeError("Video no generado")
            except Exception as e:
                logger.warning("No se pudo convertir story imagen a video: %s — publicando imagen estática", e)
                url_img = cloudinary_url or cloudinary.uploader.upload(str(ruta), folder="salsas_bestial")["secure_url"]
                media_data = {"image_url": url_img, "media_type": "STORIES", "access_token": settings.INSTAGRAM_ACCESS_TOKEN}
        else:
            # Fallback: publicar imagen estática (sin música)
            if cloudinary_url:
                url_img = cloudinary_url.split(",")[0].strip()
            elif ruta and ruta.exists():
                url_img = cloudinary.uploader.upload(str(ruta), folder="salsas_bestial")["secure_url"]
            else:
                logger.error("Sin imagen para post/story")
                return None
            media_data = {"image_url": url_img, "access_token": settings.INSTAGRAM_ACCESS_TOKEN}
            if tipo_pub == "story":
                media_data["media_type"] = "STORIES"
            else:
                media_data["caption"] = item.caption

    r1 = req.post(
        f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
        data=media_data, timeout=120,
    )
    if r1.status_code != 200:
        logger.error("Error creando container post/story (%d): %s", r1.status_code, r1.text)
        return None

    creation_id = r1.json()["id"]

    # Polling para videos
    if "video_url" in media_data:
        logger.info("Esperando procesamiento de video en Instagram...")
        procesado = False
        for _ in range(24):
            time.sleep(10)
            st_resp = req.get(
                f"https://graph.facebook.com/v21.0/{creation_id}",
                params={"fields": "status_code,status", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=30,
            ).json()
            st = st_resp.get("status_code", "")
            logger.info("status_code: %s", st)
            if st == "FINISHED":
                procesado = True
                break
            if st == "ERROR":
                logger.error("Error procesando video: %s", st_resp)
                return None
        if not procesado:
            logger.error("Timeout esperando video FINISHED tras 240s — abortando")
            return None

    r2 = req.post(
        f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
        timeout=60,
    )
    if r2.status_code != 200:
        logger.error("Error media_publish (%d): %s", r2.status_code, r2.text)
        return None
    return r2.json().get("id")
