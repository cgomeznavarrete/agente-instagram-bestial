"""
Publicación directa de un item de la biblioteca en Instagram.
Usado por main.py (CLI) y por bot.py (Telegram).
"""
import logging
import time
from pathlib import Path

import requests as req
import cloudinary
import cloudinary.uploader

from config import settings
from agente.gestores.biblioteca import marcar_publicado

logger = logging.getLogger(__name__)


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

    media_id = None

    # ── CARRUSEL ──────────────────────────────────────────────────────────────
    if item.es_carrusel:
        urls_guardadas = [u for u in (cloudinary_url or "").split(",") if u.startswith("http")]
        rutas_slides = [Path(r) for r in getattr(item, "archivos_carrusel", [])]
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
        if cloudinary_url:
            url_video = cloudinary_url
        elif ruta and ruta.exists():
            url_video = cloudinary.uploader.upload(str(ruta), folder="salsas_bestial", resource_type="video")["secure_url"]
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
        for _ in range(18):
            time.sleep(10)
            st = req.get(
                f"https://graph.facebook.com/v21.0/{creation_id}",
                params={"fields": "status_code", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=30,
            ).json().get("status_code", "")
            if st == "FINISHED":
                break
            if st == "ERROR":
                logger.error("Error procesando reel en Instagram")
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
    es_video = any(item.nombre_archivo.lower().endswith(e) for e in (".mp4", ".mov", ".avi", ".m4v"))

    if es_video:
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
        # Story imagen → convertir a video con música si hay archivo local
        if tipo_pub == "story" and ruta and ruta.exists():
            try:
                from agente.generadores.video_automatico import imagen_a_video_story
                import random
                _MOOD_POR_PILAR = {
                    "humor_picante": "humor", "retos_y_pruebas_de_picante": "energetico",
                    "promociones_y_lanzamientos": "upbeat_latino", "como_comprar": "upbeat_latino",
                    "recetas_y_maridajes": "chill_food", "behind_the_scenes": "chill_food",
                    "lifestyle_y_comunidad": "chill_food", "educacion_sobre_salsas": "chill_food",
                    "testimonios_y_ugc": "chill_food", "beneficios_del_producto": "upbeat_latino",
                }
                pilar_item = getattr(item, "pilar", "") or ""
                mood = _MOOD_POR_PILAR.get(pilar_item) or random.choice(["chill_food", "upbeat_latino"])
                ruta_video = imagen_a_video_story(ruta, mood_musica=mood, duracion=15)
                if ruta_video and ruta_video.exists():
                    url_video = cloudinary.uploader.upload(str(ruta_video), folder="salsas_bestial", resource_type="video")["secure_url"]
                    media_data = {"video_url": url_video, "media_type": "STORIES", "access_token": settings.INSTAGRAM_ACCESS_TOKEN}
                else:
                    raise RuntimeError("Video no generado")
            except Exception as e:
                logger.warning("No se pudo convertir imagen a video: %s — publicando imagen estática", e)
                url_img = cloudinary_url or cloudinary.uploader.upload(str(ruta), folder="salsas_bestial")["secure_url"]
                media_data = {"image_url": url_img, "media_type": "STORIES", "access_token": settings.INSTAGRAM_ACCESS_TOKEN}
        else:
            if cloudinary_url:
                url_img = cloudinary_url
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
                break
            if st == "ERROR":
                logger.error("Error procesando video: %s", st_resp)
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
