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
