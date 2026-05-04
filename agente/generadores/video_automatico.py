"""
Genera videos MP4 9:16 automáticamente con MoviePy.
Flujo: imágenes → slideshow → texto en pantalla → música → exportar MP4 listo para Instagram.
"""

import logging
import random
from pathlib import Path
from datetime import datetime

from config import settings
from config import imagen_params as params

logger = logging.getLogger(__name__)

# Pillow 10+ eliminó Image.ANTIALIAS — MoviePy 1.x lo necesita internamente
try:
    import PIL.Image
    if not hasattr(PIL.Image, "ANTIALIAS"):
        PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
except Exception:
    pass


def _cargar_moviepy():
    """Importa MoviePy con mensaje de error útil si no está instalado."""
    try:
        # Pillow 10+ eliminó Image.ANTIALIAS — MoviePy 1.x lo usa internamente
        import PIL.Image
        if not hasattr(PIL.Image, "ANTIALIAS"):
            PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
        from moviepy.editor import (
            ImageClip, VideoFileClip, AudioFileClip,
            CompositeVideoClip, concatenate_videoclips, TextClip,
        )
        return True
    except ImportError:
        logger.error("MoviePy no instalado. Ejecuta: pip install moviepy")
        return False


def _seleccionar_musica(mood: str) -> Path | None:
    """Selecciona un track de música según el mood solicitado."""
    tracks = params.MUSICA_POR_MOOD.get(mood, [])
    if not tracks:
        todas = [t for lista in params.MUSICA_POR_MOOD.values() for t in lista]
        tracks = todas
    random.shuffle(tracks)
    for nombre in tracks:
        ruta = settings.MUSICA_DIR / nombre
        if ruta.exists():
            return ruta
    logger.warning("No se encontró música para mood '%s' en %s", mood, settings.MUSICA_DIR)
    return None


def _rutas_absolutas(rutas: list[str]) -> list[Path]:
    """Resuelve rutas (absolutas o relativas al proyecto) y filtra las que existen como imagen."""
    resultado = []
    extensiones = {".jpg", ".jpeg", ".png", ".webp"}
    for ruta in rutas:
        p = Path(ruta)
        if not p.is_absolute():
            p = settings.BASE_DIR / ruta
        if p.exists() and p.suffix.lower() in extensiones:
            resultado.append(p)
    return resultado


def generar_reel(
    imagenes: list[str],
    mood_musica: str = "upbeat_latino",
    textos: list[dict] | None = None,
    duracion_total: int | None = None,
    transicion: str = "fade",
    sufijo: str = "",
) -> Path | None:
    """
    Genera un Reel MP4 9:16.

    imagenes: lista de rutas relativas al proyecto
    textos: [{"texto": "...", "inicio": 0, "fin": 3, "posicion": "top|center|bottom"}]
    duracion_total: segundos totales (None = automático según imágenes)
    """
    if not _cargar_moviepy():
        return None

    from moviepy.editor import (
        ImageClip, AudioFileClip, CompositeVideoClip,
        concatenate_videoclips, TextClip,
    )

    rutas = _rutas_absolutas(imagenes)
    if not rutas:
        logger.error("No se encontraron imágenes válidas para el Reel")
        return None

    res = params.VIDEO_REELS["resolucion"]
    dur_imagen = params.DURACION_IMAGEN_REEL_SEG
    if duracion_total:
        dur_imagen = max(2.0, duracion_total / len(rutas))

    clips = []
    for ruta in rutas:
        try:
            clip = (
                ImageClip(str(ruta))
                .set_duration(dur_imagen)
                .resize(res)
            )
            if transicion == "fade":
                clip = clip.fadein(params.TRANSICIONES["fade"]["duracion_seg"])
                clip = clip.fadeout(params.TRANSICIONES["fade"]["duracion_seg"])
            clips.append(clip)
        except Exception as e:
            logger.warning("Error procesando imagen %s: %s", ruta.name, e)

    if not clips:
        logger.error("No se generaron clips de imagen")
        return None

    video = concatenate_videoclips(clips, method="compose")

    # Música
    pista = _seleccionar_musica(mood_musica)
    if pista:
        try:
            audio = (
                AudioFileClip(str(pista))
                .subclip(0, min(video.duration, params.VIDEO_REELS["duracion_max_seg"]))
                .audio_fadein(params.VOLUMEN_FADE_IN_SEG)
                .audio_fadeout(params.VOLUMEN_FADE_OUT_SEG)
                .volumex(params.VOLUMEN_MUSICA)
            )
            video = video.set_audio(audio)
        except Exception as e:
            logger.warning("No se pudo agregar música: %s", e)

    # Textos superpuestos
    capas = [video]
    for texto_cfg in (textos or []):
        try:
            txt_clip = (
                TextClip(
                    texto_cfg["texto"],
                    fontsize=params.TEXTO_VIDEO["tamano_hook_px"],
                    color=params.TEXTO_VIDEO["color_texto_principal"],
                    font=params.TEXTO_VIDEO["fuente_hook"],
                    stroke_color=params.TEXTO_VIDEO["color_sombra_texto"],
                    stroke_width=2,
                    method="caption",
                    size=(res[0] - params.TEXTO_VIDEO["margen_px"] * 2, None),
                    align="center",
                )
                .set_start(texto_cfg.get("inicio", 0))
                .set_end(texto_cfg.get("fin", 3))
                .set_position(_posicion_texto(texto_cfg.get("posicion", "bottom"), res))
                .fadein(0.3)
                .fadeout(0.3)
            )
            capas.append(txt_clip)
        except Exception as e:
            logger.warning("Error creando texto '%s': %s", texto_cfg.get("texto", ""), e)

    video_final = CompositeVideoClip(capas) if len(capas) > 1 else video

    return _exportar(video_final, "reel", sufijo)


def generar_story(
    imagen_fondo: str,
    texto_principal: str,
    texto_cta: str,
    mood_musica: str | None = None,
    duracion: int = 15,
    sufijo: str = "",
) -> Path | None:
    """
    Genera una Story MP4 de 15 segundos con imagen + texto animado + música.
    """
    if not _cargar_moviepy():
        return None

    from moviepy.editor import (
        ImageClip, AudioFileClip, CompositeVideoClip, TextClip,
    )

    res = params.VIDEO_STORIES["resolucion"]
    rutas = _rutas_absolutas([imagen_fondo])
    if not rutas:
        logger.error("Imagen de fondo no encontrada: %s", imagen_fondo)
        return None

    video = ImageClip(str(rutas[0])).set_duration(duracion).resize(res)

    capas = [video]

    # Texto principal (aparece al segundo 1)
    try:
        hook_clip = (
            TextClip(
                texto_principal,
                fontsize=params.TEXTO_VIDEO["tamano_hook_px"],
                color=params.TEXTO_VIDEO["color_texto_principal"],
                font=params.TEXTO_VIDEO["fuente_hook"],
                stroke_color=params.TEXTO_VIDEO["color_sombra_texto"],
                stroke_width=2,
                method="caption",
                size=(res[0] - params.TEXTO_VIDEO["margen_px"] * 2, None),
                align="center",
            )
            .set_start(1.0)
            .set_end(duracion - 2)
            .set_position(_posicion_texto("top", res))
            .fadein(0.5)
        )
        capas.append(hook_clip)
    except Exception as e:
        logger.warning("Error texto principal: %s", e)

    # CTA final (últimos 4 segundos)
    try:
        cta_clip = (
            TextClip(
                texto_cta,
                fontsize=params.TEXTO_VIDEO["tamano_cta_px"],
                color=params.TEXTO_VIDEO["color_texto_principal"],
                font=params.TEXTO_VIDEO["fuente_cta"],
                stroke_color=params.TEXTO_VIDEO["color_sombra_texto"],
                stroke_width=2,
                method="caption",
                size=(res[0] - params.TEXTO_VIDEO["margen_px"] * 2, None),
                align="center",
            )
            .set_start(duracion - 4)
            .set_end(duracion)
            .set_position(_posicion_texto("bottom", res))
            .fadein(0.4)
        )
        capas.append(cta_clip)
    except Exception as e:
        logger.warning("Error texto CTA: %s", e)

    video_final = CompositeVideoClip(capas)

    # Música opcional
    if mood_musica:
        pista = _seleccionar_musica(mood_musica)
        if pista:
            try:
                audio = (
                    AudioFileClip(str(pista))
                    .subclip(0, duracion)
                    .audio_fadein(params.VOLUMEN_FADE_IN_SEG)
                    .audio_fadeout(params.VOLUMEN_FADE_OUT_SEG)
                    .volumex(params.VOLUMEN_MUSICA)
                )
                video_final = video_final.set_audio(audio)
            except Exception as e:
                logger.warning("No se pudo agregar música a story: %s", e)

    return _exportar(video_final, "story", sufijo)


def imagen_a_video_story(
    ruta_imagen: str | Path,
    mood_musica: str = "chill_food",
    duracion: int = 15,
    sufijo: str = "",
) -> Path | None:
    """
    Convierte una imagen estática en un video MP4 9:16 de 15 s listo para Story.

    No agrega texto — la imagen ya tiene su propio diseño.
    Solo aplica: imagen → duración fija → música con fade in/out → H.264+AAC.

    Args:
        ruta_imagen: Ruta a la imagen (JPG, PNG, WEBP). Se redimensiona a 1080×1920.
        mood_musica: mood para seleccionar el track ('chill_food', 'upbeat_latino',
                     'energetico', 'humor'). Si no hay track disponible, exporta sin música.
        duracion: Duración en segundos (por defecto 15, máx 60 para Stories).
        sufijo: Sufijo opcional en el nombre del archivo de salida.

    Returns:
        Path al MP4 generado, o None si falla.
    """
    if not _cargar_moviepy():
        return None

    from moviepy.editor import ImageClip, AudioFileClip

    ruta = Path(ruta_imagen)
    if not ruta.exists():
        # Intentar resolución relativa al proyecto
        ruta = settings.BASE_DIR / ruta_imagen
    if not ruta.exists():
        logger.error("Imagen no encontrada para convertir a story: %s", ruta_imagen)
        return None

    res = params.VIDEO_STORIES["resolucion"]  # (1080, 1920)

    try:
        video = (
            ImageClip(str(ruta))
            .set_duration(duracion)
            .resize(res)
        )
    except Exception as e:
        logger.error("Error cargando imagen '%s': %s", ruta, e)
        return None

    # Música con fade in/out
    pista = _seleccionar_musica(mood_musica)
    if pista:
        try:
            audio = (
                AudioFileClip(str(pista))
                .subclip(0, min(duracion, AudioFileClip(str(pista)).duration))
                .audio_fadein(min(params.VOLUMEN_FADE_IN_SEG, 1.5))
                .audio_fadeout(min(params.VOLUMEN_FADE_OUT_SEG, 2.0))
                .volumex(params.VOLUMEN_MUSICA)
            )
            video = video.set_audio(audio)
            logger.info("Música agregada a story: %s (%s)", pista.name, mood_musica)
        except Exception as e:
            logger.warning("No se pudo agregar música a la story: %s — exportando sin audio", e)

    return _exportar(video, "story", sufijo)


def _preparar_imagen_9_16(ruta: Path, tmp_dir: Path | None = None) -> Path:
    """
    Convierte una imagen de cualquier proporción a 1080×1920 (9:16) con técnica de
    fondo desenfocado: la misma imagen escalada y muy borrosa llena el fondo, y la
    imagen original (ajustada a caber en 1080×1350) queda centrada encima.

    Esto es exactamente lo que Instagram hace cuando convierte un post 1:1 a Reel.
    Sin letras negras ni franjas — siempre se ve profesional.
    """
    from PIL import Image, ImageFilter, ImageEnhance
    import tempfile

    W, H = 1080, 1920
    MAX_FG_W, MAX_FG_H = 1080, 1350  # la imagen original no ocupa todo el alto

    img = Image.open(ruta).convert("RGB")

    # ── Fondo: escalar para LLENAR 1080×1920, recortar al centro, desenfocar ──
    scale_bg = max(W / img.width, H / img.height)
    bg = img.resize(
        (int(img.width * scale_bg), int(img.height * scale_bg)),
        Image.LANCZOS,
    )
    x0 = (bg.width - W) // 2
    y0 = (bg.height - H) // 2
    bg = bg.crop((x0, y0, x0 + W, y0 + H))
    bg = bg.filter(ImageFilter.GaussianBlur(radius=40))
    bg = ImageEnhance.Brightness(bg).enhance(0.55)  # oscurecer para contraste

    # ── Primer plano: escalar para CABER en MAX_FG, centrar sobre el fondo ────
    scale_fg = min(MAX_FG_W / img.width, MAX_FG_H / img.height)
    fg_w = int(img.width * scale_fg)
    fg_h = int(img.height * scale_fg)
    fg = img.resize((fg_w, fg_h), Image.LANCZOS)

    x_pos = (W - fg_w) // 2
    y_pos = (H - fg_h) // 2
    bg.paste(fg, (x_pos, y_pos))

    # ── Guardar en directorio temporal ────────────────────────────────────────
    if tmp_dir is None:
        tmp_dir = Path(tempfile.mkdtemp())
    else:
        tmp_dir.mkdir(parents=True, exist_ok=True)

    out = tmp_dir / f"_916_{ruta.stem}.jpg"
    bg.save(str(out), "JPEG", quality=92)
    return out


def imagen_a_reel(
    ruta_imagen: str | Path,
    mood_musica: str = "chill_food",
    duracion: int = 20,
    sufijo: str = "",
) -> Path | None:
    """
    Convierte una foto estática en un Reel MP4 9:16 con música.

    Pasos: foto → fondo blur 1080×1920 → música royalty-free → H.264+AAC.
    Ideal para posts de feed que necesitan audio (la API de Instagram no
    permite música en imágenes estáticas — solo en videos).

    Args:
        ruta_imagen: Ruta a la imagen (JPG, PNG, WEBP).
        mood_musica: 'chill_food' | 'upbeat_latino' | 'energetico' | 'humor'
        duracion: Duración en segundos (default 20, recomendado 15-30).
        sufijo: Sufijo opcional en el nombre del MP4.

    Returns:
        Path al MP4, o None si falla.
    """
    if not _cargar_moviepy():
        return None

    from moviepy.editor import ImageClip, AudioFileClip

    ruta = Path(ruta_imagen)
    if not ruta.is_absolute():
        ruta = settings.BASE_DIR / ruta_imagen
    if not ruta.exists():
        logger.error("imagen_a_reel: imagen no encontrada: %s", ruta)
        return None

    # Pre-procesar a 9:16 con fondo blur
    tmp_dir = settings.MATERIAL_AGENTE_DIR / "videos_generados" / "_tmp"
    try:
        ruta_916 = _preparar_imagen_9_16(ruta, tmp_dir)
    except Exception as e:
        logger.warning("No se pudo preparar imagen 9:16, usando original: %s", e)
        ruta_916 = ruta

    res = params.VIDEO_REELS["resolucion"]
    try:
        video = ImageClip(str(ruta_916)).set_duration(duracion).resize(res)
    except Exception as e:
        logger.error("Error creando clip de imagen para reel: %s", e)
        return None

    pista = _seleccionar_musica(mood_musica)
    if pista:
        try:
            audio = (
                AudioFileClip(str(pista))
                .subclip(0, min(duracion, AudioFileClip(str(pista)).duration))
                .audio_fadein(params.VOLUMEN_FADE_IN_SEG)
                .audio_fadeout(params.VOLUMEN_FADE_OUT_SEG)
                .volumex(params.VOLUMEN_MUSICA)
            )
            video = video.set_audio(audio)
            logger.info("Música agregada al reel de imagen: %s (%s)", pista.name, mood_musica)
        except Exception as e:
            logger.warning("No se pudo agregar música al reel: %s", e)
    else:
        logger.warning("No hay track disponible para mood '%s' — reel sin música", mood_musica)

    return _exportar(video, "reel", sufijo or f"_{ruta.stem}")


def carrusel_a_reel(
    rutas_slides: list,
    mood_musica: str = "chill_food",
    duracion_slide: float = 3.5,
    sufijo: str = "",
) -> Path | None:
    """
    Convierte los slides de un carrusel en un Reel MP4 9:16 con música.

    Cada slide se muestra duracion_slide segundos con fade in/out.
    La música corre durante todo el video.

    Args:
        rutas_slides: Lista de rutas a las imágenes de los slides.
        mood_musica: Track a usar según el pilar de contenido.
        duracion_slide: Segundos por slide (default 3.5s).
        sufijo: Sufijo opcional en el nombre del MP4.

    Returns:
        Path al MP4, o None si falla.
    """
    if not _cargar_moviepy():
        return None

    from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

    rutas = [Path(r) for r in rutas_slides]
    rutas = [r for r in rutas if r.exists()]
    if not rutas:
        logger.error("carrusel_a_reel: no se encontraron slides válidos")
        return None

    res = params.VIDEO_REELS["resolucion"]
    fade_dur = params.TRANSICIONES["fade"]["duracion_seg"]

    # Pre-procesar cada slide a 9:16 con fondo blur
    tmp_dir = settings.MATERIAL_AGENTE_DIR / "videos_generados" / "_tmp"
    clips = []
    for ruta in rutas:
        try:
            ruta_916 = _preparar_imagen_9_16(ruta, tmp_dir)
            clip = (
                ImageClip(str(ruta_916))
                .set_duration(duracion_slide)
                .resize(res)
                .fadein(fade_dur)
                .fadeout(fade_dur)
            )
            clips.append(clip)
        except Exception as e:
            logger.warning("Error procesando slide %s para reel: %s", ruta.name, e)

    if not clips:
        logger.error("carrusel_a_reel: no se generaron clips")
        return None

    video = concatenate_videoclips(clips, method="compose")
    duracion_total = video.duration

    pista = _seleccionar_musica(mood_musica)
    if pista:
        try:
            dur_audio = min(duracion_total, params.VIDEO_REELS["duracion_max_seg"])
            audio = (
                AudioFileClip(str(pista))
                .subclip(0, min(dur_audio, AudioFileClip(str(pista)).duration))
                .audio_fadein(params.VOLUMEN_FADE_IN_SEG)
                .audio_fadeout(params.VOLUMEN_FADE_OUT_SEG)
                .volumex(params.VOLUMEN_MUSICA)
            )
            video = video.set_audio(audio)
            logger.info(
                "carrusel_a_reel: %d slides, %.1fs, música '%s' (%s)",
                len(clips), duracion_total, pista.name, mood_musica,
            )
        except Exception as e:
            logger.warning("No se pudo agregar música al reel de carrusel: %s", e)

    return _exportar(video, "reel", sufijo or "_carrusel")


def _posicion_texto(posicion: str, res: tuple) -> tuple:
    margen = params.TEXTO_VIDEO["margen_px"]
    if posicion == "top":
        return ("center", margen)
    if posicion == "center":
        return ("center", "center")
    return ("center", res[1] - 180)


def _exportar(video, tipo: str, sufijo: str) -> Path | None:
    """Exporta el video final como MP4 con codec H.264 + AAC."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"{tipo}_{ts}{sufijo}.mp4"
    ruta = settings.MATERIAL_AGENTE_DIR / "videos_generados" / nombre
    ruta.parent.mkdir(exist_ok=True)

    cfg = params.VIDEO_REELS if tipo == "reel" else params.VIDEO_STORIES

    try:
        video.write_videofile(
            str(ruta),
            fps=cfg["fps"],
            codec=cfg["codec_video"],
            audio_codec=cfg["codec_audio"],
            bitrate=cfg["bitrate_video"],
            preset="medium",
            logger=None,
        )
        logger.info("Video exportado: %s (%.1f MB)", ruta.name, ruta.stat().st_size / 1_048_576)
        return ruta
    except Exception as e:
        logger.error("Error exportando video: %s", e)
        return None
