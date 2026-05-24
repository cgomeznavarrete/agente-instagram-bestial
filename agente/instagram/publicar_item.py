"""
Publicación directa de un item de la biblioteca en Instagram.
Usado por main.py (CLI) y por bot.py (Telegram).

Política de música:
  - Posts de imagen → se publican como imagen estática. El usuario agrega música
    manualmente desde la app de Instagram. El bot envía una recomendación de track.
  - Stories de imagen → se convierten a MP4 con música antes de publicar.
  - Reels → música embebida en el MP4 generado.
  - Carruseles → no se publican via API; el usuario los sube manualmente con música.
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


def _normalizar_video_reel(url_video: str) -> str:
    """
    Descarga el video, lo re-encoda con FFmpeg a las specs exactas de Instagram
    (H.264 high, yuv420p, 30fps, AAC 44.1kHz, +faststart) y lo sube a Cloudinary.
    Retorna la nueva URL o la original si algo falla.

    Instagram procesa en ~2-3min videos ya en formato correcto.
    Sin normalizar puede tardar 15-20min por transcodificación interna.
    """
    import tempfile
    import subprocess
    import urllib.request as _urlreq

    try:
        # Descargar video original a temp
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f_in:
            ruta_in = f_in.name
        _urlreq.urlretrieve(url_video, ruta_in)

        ruta_out = ruta_in.replace(".mp4", "_ig.mp4")

        cmd = [
            "ffmpeg", "-y", "-i", ruta_in,
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.0",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-b:v", "3500k",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
            "-movflags", "+faststart",
            ruta_out,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=180)
        if result.returncode != 0:
            logger.warning("FFmpeg normalización falló — usando video original. stderr: %s",
                           result.stderr.decode(errors="replace")[-400:])
            return url_video

        nueva_url = cloudinary.uploader.upload(
            ruta_out,
            folder="salsas_bestial",
            resource_type="video",
        )["secure_url"]

        Path(ruta_in).unlink(missing_ok=True)
        Path(ruta_out).unlink(missing_ok=True)

        logger.info("Video normalizado para Instagram: %s", nueva_url)
        return nueva_url

    except Exception as e:
        logger.warning("No se pudo normalizar video — usando original: %s", e)
        return url_video


def _publicar_video_como_reel(url_video: str, caption: str) -> str | None:
    """
    Crea container de Reel → polling FINISHED → media_publish.
    Retorna media_id o None.
    """
    # Normalizar a specs exactas de Instagram antes de enviar
    logger.info("Normalizando video para Instagram...")
    url_video = _normalizar_video_reel(url_video)

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
    # status_code polling no funciona con nuestro token (Authorization Error 100/33).
    # Usamos retry en media_publish: si 9007 (not ready) esperar y reintentar.
    time.sleep(20)  # pausa inicial para que Instagram empiece a procesar
    for intento in range(30):  # máx 30 × 15s = 450s adicionales (~7.5min)
        r2 = req.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
            data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
            timeout=60,
        )
        if r2.status_code == 200:
            return r2.json().get("id")
        err = r2.json().get("error", {})
        if err.get("code") == 9007:
            logger.info("Reel aún no listo (9007) — reintento %d/30 en 15s...", intento + 1)
            time.sleep(15)
            continue
        logger.error("Error media_publish reel (%d): %s", r2.status_code, r2.text)
        return None
    logger.error("Timeout esperando reel listo tras ~470s — abortando")
    return None


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
        urls_guardadas = [u.strip() for u in (cloudinary_url or "").split(",") if u.strip().startswith("http")]
        rutas_slides = [Path(r) for r in (getattr(item, "archivos_carrusel", None) or [])]

        # Construir lista de URLs para cada slide — priorizar Cloudinary (ya subidas)
        # Si hay URLs guardadas, usarlas directamente sin necesitar archivos locales.
        if urls_guardadas:
            slide_urls = urls_guardadas
            logger.info("Carrusel: usando %d URLs de Cloudinary", len(slide_urls))
        else:
            slide_urls = []
            for slide_ruta in rutas_slides:
                if slide_ruta.exists():
                    try:
                        url_s = cloudinary.uploader.upload(
                            str(slide_ruta), folder="salsas_bestial"
                        )["secure_url"]
                        slide_urls.append(url_s)
                        logger.info("Carrusel: slide subido a Cloudinary: %s", url_s[:60])
                    except Exception as _e_slide:
                        logger.error("Error subiendo slide %s: %s", slide_ruta.name, _e_slide)
                else:
                    logger.warning("Slide no encontrado: %s", slide_ruta)

        if not slide_urls:
            logger.error("Carrusel sin slides — ni URLs guardadas ni archivos locales")
            return None

        creation_ids = []
        for i, url_slide in enumerate(slide_urls):
            r_c = req.post(
                f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
                data={"image_url": url_slide, "is_carousel_item": "true", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=60,
            )
            if r_c.status_code == 200:
                creation_ids.append(r_c.json()["id"])
                logger.info("Carrusel: slide %d/%d → creation_id=%s", i + 1, len(slide_urls), r_c.json()["id"])
            else:
                logger.error("Error slide %d carrusel: %s", i, r_c.text)
        if not creation_ids:
            logger.error("No se pudieron crear containers para los slides del carrusel")
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

        # Normalizar a specs exactas de Instagram antes de enviar
        # Reduce procesamiento de ~20min a ~2-3min
        logger.info("Normalizando video para Instagram...")
        url_video = _normalizar_video_reel(url_video)

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
        # status_code polling no funciona con nuestro token (Authorization Error 100/33).
        # Retry en media_publish: si 9007 esperar y reintentar.
        time.sleep(20)
        for intento in range(30):  # máx 30 × 15s = 450s adicionales
            r2 = req.post(
                f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
                data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=60,
            )
            if r2.status_code == 200:
                return r2.json().get("id")
            err = r2.json().get("error", {})
            if err.get("code") == 9007:
                logger.info("Reel aún no listo (9007) — reintento %d/30 en 15s...", intento + 1)
                time.sleep(15)
                continue
            logger.error("Error media_publish reel (%d): %s", r2.status_code, r2.text)
            return None
        logger.error("Timeout esperando reel listo tras ~470s — abortando")
        return None

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
            "media_type": "STORIES" if tipo_pub == "story" else "REELS",
            "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
        }
        if tipo_pub == "reel" or tipo_pub == "post":
            media_data["share_to_feed"] = "true"
        if item.caption:
            media_data["caption"] = item.caption
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

        if tipo_pub == "post":
            # Post de imagen → publicar como imagen estática.
            # La música la agrega el usuario manualmente desde la app.
            # El bot envía la recomendación de track en Telegram (ver bot.py).
            pass

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

    es_story  = media_data.get("media_type") == "STORIES"
    es_video  = "video_url" in media_data

    if es_story:
        # Stories NO soportan polling de status_code (devuelve Authorization Error 100/33).
        # Se intenta media_publish con retry: si devuelve 9007 (not ready), esperar y reintentar.
        pausa_inicial = 10 if es_video else 3
        logger.info("Story — pausa inicial %ds...", pausa_inicial)
        time.sleep(pausa_inicial)
        for intento in range(18):  # máx 18 reintentos × 10s = 180s adicionales
            r2 = req.post(
                f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
                data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=60,
            )
            if r2.status_code == 200:
                return r2.json().get("id")
            err = r2.json().get("error", {})
            if err.get("code") == 9007:
                logger.info("Story aún no lista (9007) — reintento %d/18 en 10s...", intento + 1)
                time.sleep(10)
                continue
            logger.error("Error media_publish story (%d): %s", r2.status_code, r2.text)
            return None
        logger.error("Timeout esperando story lista tras 180s — abortando")
        return None
    else:
        # Posts: polling hasta FINISHED (imagen: 2s×15, video: 10s×24)
        max_intentos = 24 if es_video else 15
        sleep_seg    = 10 if es_video else 2
        logger.info("Esperando procesamiento en Instagram (%s)...", "video" if es_video else "imagen")
        procesado = False
        for _ in range(max_intentos):
            time.sleep(sleep_seg)
            st_resp = req.get(
                f"https://graph.facebook.com/v21.0/{creation_id}",
                params={"fields": "status_code,status", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=30,
            ).json()
            st = st_resp.get("status_code", "")
            if not st:
                logger.warning("status_code vacío — respuesta: %s", st_resp)
            else:
                logger.info("status_code: %s", st)
            if "error" in st_resp:
                logger.error("Error API al consultar container: %s", st_resp["error"])
                return None
            if st == "FINISHED":
                procesado = True
                break
            if st == "ERROR":
                logger.error("Error procesando media: %s", st_resp)
                return None
        if not procesado:
            logger.error("Timeout esperando FINISHED (%ds) — abortando", max_intentos * sleep_seg)
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
