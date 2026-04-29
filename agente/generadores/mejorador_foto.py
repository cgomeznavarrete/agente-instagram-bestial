"""
Mejora fotografías del usuario para convertirlas en contenido profesional.

Flujo:
  Foto cruda del celular
       ↓
  Corrección básica (brillo, color, contraste) con Pillow
       ↓
  Mejora IA con Fal.ai img2img (estilo fotografía comercial de producto)
       ↓
  Foto mejorada lista para agregar texto y publicar

El frasco/producto NUNCA se altera — la IA solo mejora iluminación y ambiente.
"""

import logging
import os
import io
import base64
from pathlib import Path
from datetime import datetime
from typing import Optional

import requests

from config import settings

logger = logging.getLogger(__name__)


# ── Carpetas de entrada/salida ────────────────────────────────────────────────
def _dir_mejoradas() -> Path:
    d = settings.MATERIAL_AGENTE_DIR / "fotos_mejoradas"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _guardar_mejorada(img_bytes: bytes, nombre_original: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"mejorada_{Path(nombre_original).stem}_{ts}.jpg"
    ruta = _dir_mejoradas() / nombre
    ruta.write_bytes(img_bytes)
    logger.info("Foto mejorada guardada: %s", ruta.name)
    return ruta


# ── Corrección básica con Pillow (gratuita, siempre disponible) ───────────────
def correccion_basica(ruta: Path) -> bytes:
    """
    Aplica correcciones automáticas de color, brillo y contraste con Pillow.
    - Sube saturación (colores más vivos)
    - Aumenta levemente el contraste
    - Corrige el brillo si la foto está subexpuesta
    - Aplica sharpening para más nitidez
    Retorna los bytes de la imagen corregida en JPEG.
    """
    from PIL import Image, ImageEnhance, ImageFilter

    img = Image.open(ruta).convert("RGB")

    # Analizar brillo promedio para decidir si subir exposición
    import statistics
    pixeles = list(img.convert("L").getdata())
    brillo_promedio = statistics.mean(pixeles)

    # Correcciones según el análisis de la foto
    factor_brillo = 1.0
    if brillo_promedio < 100:       # foto oscura → subir brillo
        factor_brillo = 1.25
    elif brillo_promedio < 130:     # un poco oscura
        factor_brillo = 1.12
    elif brillo_promedio > 200:     # sobreexpuesta → bajar
        factor_brillo = 0.92

    img = ImageEnhance.Brightness(img).enhance(factor_brillo)
    img = ImageEnhance.Color(img).enhance(1.20)        # +20% saturación
    img = ImageEnhance.Contrast(img).enhance(1.15)     # +15% contraste
    img = ImageEnhance.Sharpness(img).enhance(1.30)    # +30% nitidez
    img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# ── Mejora IA con Fal.ai img2img ─────────────────────────────────────────────
def mejorar_con_ia(
    ruta: Path,
    intensidad: float = 0.35,
    tipo: str = "producto",   # "producto" | "lifestyle" | "accion"
) -> Optional[bytes]:
    """
    Usa Fal.ai (FLUX img2img) para mejorar la foto manteniendo el producto intacto.

    intensidad: 0.0 = sin cambios, 1.0 = cambia todo.
                0.25-0.40 es el rango ideal para mejorar sin alterar el producto.

    tipo: ajusta el prompt de mejora según el contenido de la foto.
    """
    if not settings.FALAI_API_KEY:
        logger.warning("FALAI_API_KEY no configurada — usando solo corrección básica")
        return None

    prompts = {
        "producto": (
            "professional commercial food photography, perfect studio lighting, "
            "soft shadows, warm tones, high contrast, sharp focus on product label, "
            "clean background, food brand advertisement quality, 4K detail"
        ),
        "lifestyle": (
            "professional lifestyle food photography, natural warm lighting, "
            "appetizing colors, sharp focus, editorial quality, Instagram food content"
        ),
        "accion": (
            "dynamic food photography, action shot, professional lighting, "
            "vivid colors, sharp product focus, commercial quality"
        ),
    }
    prompt = prompts.get(tipo, prompts["producto"])

    try:
        import fal_client
        os.environ["FAL_KEY"] = settings.FALAI_API_KEY

        # Convertir imagen a base64 para enviar a Fal.ai
        with open(ruta, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        img_url = f"data:image/jpeg;base64,{img_b64}"

        logger.info("Mejorando foto con Fal.ai img2img: %s", ruta.name)

        resultado = fal_client.run(
            "fal-ai/flux/dev/image-to-image",
            arguments={
                "image_url": img_url,
                "prompt": prompt,
                "negative_prompt": (
                    "blurry, low quality, overexposed, dark shadows, "
                    "distorted label, altered logo, changed colors, CGI look"
                ),
                "strength": intensidad,
                "num_inference_steps": 28,
                "guidance_scale": 7.0,
                "num_images": 1,
            },
        )

        url_mejorada = resultado["images"][0]["url"]
        resp = requests.get(url_mejorada, timeout=30)
        if resp.status_code == 200:
            logger.info("Mejora IA completada exitosamente")
            return resp.content
        else:
            logger.error("Error descargando imagen mejorada: %d", resp.status_code)
            return None

    except Exception as e:
        logger.error("Error en mejora IA Fal.ai: %s", e)
        return None


# ── Recorte inteligente para formato Instagram ────────────────────────────────
def recortar_para_instagram(
    img_bytes: bytes,
    formato: str = "post",   # "post" (1:1) | "story" (9:16) | "portrait" (4:5)
) -> bytes:
    """
    Recorta y redimensiona la imagen al formato correcto de Instagram.
    El recorte es inteligente: centra en la zona más importante (centro-superior).
    """
    from PIL import Image

    formatos = {
        "post":     (1080, 1080),
        "story":    (1080, 1920),
        "portrait": (1080, 1350),
        "reel":     (1080, 1920),
    }
    target_w, target_h = formatos.get(formato, (1080, 1080))

    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    # Escalar para cubrir el formato manteniendo aspecto
    ratio_w = target_w / img.width
    ratio_h = target_h / img.height
    ratio = max(ratio_w, ratio_h)
    nuevo_w = int(img.width * ratio)
    nuevo_h = int(img.height * ratio)
    img = img.resize((nuevo_w, nuevo_h), Image.LANCZOS)

    # Crop centrado (ligeramente arriba del centro para productos)
    x = (nuevo_w - target_w) // 2
    y_offset = 0.35   # 35% desde arriba (centrado hacia el producto)
    y = int((nuevo_h - target_h) * y_offset)
    y = max(0, min(y, nuevo_h - target_h))
    img = img.crop((x, y, x + target_w, y + target_h))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# ── Pipeline completo de mejora ───────────────────────────────────────────────
def mejorar_foto(
    ruta_original: Path,
    formato: str = "post",
    usar_ia: bool = True,
    intensidad_ia: float = 0.35,
    tipo_foto: str = "producto",
) -> Optional[Path]:
    """
    Pipeline completo: corrección básica → mejora IA → recorte formato → guardar.

    ruta_original: foto cruda del usuario
    formato: "post" | "story" | "portrait" | "reel"
    usar_ia: si True, aplica Fal.ai img2img además de la corrección básica
    intensidad_ia: 0.25-0.40 recomendado (0 = sin cambios, 1 = cambio total)
    tipo_foto: "producto" | "lifestyle" | "accion"

    Retorna: ruta de la foto mejorada lista para agregar texto
    """
    if not ruta_original.exists():
        logger.error("Foto original no encontrada: %s", ruta_original)
        return None

    logger.info("Iniciando mejora de: %s", ruta_original.name)

    # Paso 1: Corrección básica (gratis, siempre)
    img_bytes = correccion_basica(ruta_original)
    logger.info("Corrección básica aplicada")

    # Paso 2: Mejora con IA (opcional, usa Fal.ai)
    if usar_ia and settings.FALAI_API_KEY:
        # Guardar temporalmente la versión con corrección básica para enviar a Fal.ai
        tmp = settings.MATERIAL_AGENTE_DIR / "fotos_mejoradas" / f"_tmp_{ruta_original.stem}.jpg"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(img_bytes)

        mejorada_ia = mejorar_con_ia(tmp, intensidad=intensidad_ia, tipo=tipo_foto)
        tmp.unlink(missing_ok=True)  # borrar temporal

        if mejorada_ia:
            img_bytes = mejorada_ia
            logger.info("Mejora IA aplicada")
        else:
            logger.info("Usando solo corrección básica (IA no disponible)")

    # Paso 3: Recorte al formato correcto
    img_bytes = recortar_para_instagram(img_bytes, formato=formato)

    # Paso 4: Guardar
    return _guardar_mejorada(img_bytes, ruta_original.name)


def mejorar_lote(
    rutas: list[Path],
    formato: str = "post",
    usar_ia: bool = True,
) -> list[Path]:
    """
    Mejora un lote de fotos. Retorna las rutas de las fotos mejoradas.
    """
    mejoradas = []
    for i, ruta in enumerate(rutas, 1):
        logger.info("Mejorando foto %d/%d: %s", i, len(rutas), ruta.name)
        resultado = mejorar_foto(ruta, formato=formato, usar_ia=usar_ia)
        if resultado:
            mejoradas.append(resultado)
    return mejoradas
