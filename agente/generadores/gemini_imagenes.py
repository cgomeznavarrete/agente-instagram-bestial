"""
Genera fotografías profesionales de producto usando Google Gemini 2.0 Flash.

Recibe las fotos de referencia del frasco y genera escenas lifestyle
con el producto como protagonista, respetando la etiqueta y el logo.

Ventaja sobre otros modelos: el usuario tiene cuenta Pro de Google
(incluido en su suscripción, sin costo adicional por imagen).
"""

import base64
import io
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

from config import settings
from config import brand_guidelines as brand

logger = logging.getLogger(__name__)

# Escenas por pilar — prompts optimizados para Gemini
ESCENAS = {
    "recetas_y_maridajes": (
        "Crea una fotografía profesional de producto de nivel comercial. "
        "El frasco de Salsa Bestial Tatemada Ahumada es el protagonista absoluto en el centro. "
        "Ubícalo sobre una mesa de madera rústica con vegetales tatemados alrededor: "
        "tomates asados, chiles, limones, cilantro fresco y chips de maíz. "
        "Luz natural cálida desde la izquierda, sombras suaves. "
        "Mantén el frasco EXACTAMENTE como está en la foto de referencia: "
        "no alteres la etiqueta, el logo del gorila ni los colores naranja y dorado. "
        "Estilo: fotografía editorial de alimentos de revista gastronómica."
    ),
    "lifestyle_y_comunidad": (
        "Fotografía lifestyle profesional. El frasco de Salsa Bestial es el protagonista "
        "en una mesa de asado familiar: carbón de fondo, carne a la parrilla, ambiente festivo. "
        "Luz cálida de tarde. El frasco está completo, etiqueta visible, sin ninguna alteración. "
        "Estilo: Instagram food photography auténtico y apetitoso."
    ),
    "promociones_y_lanzamientos": (
        "Hero shot de producto comercial premium. El frasco de Salsa Bestial Tatemada Ahumada "
        "está perfectamente centrado sobre superficie de pizarra negra con iluminación dramática "
        "lateral. Chiles secos decorativos alrededor. Fondo oscuro profesional. "
        "El frasco debe verse exactamente como en la referencia: etiqueta naranja, tapa dorada, logo del gorila. "
        "Calidad fotográfica de catálogo comercial."
    ),
    "behind_the_scenes": (
        "Fotografía artesanal auténtica. El frasco de Salsa Bestial sobre una mesa rústica "
        "de madera con los ingredientes naturales que componen la salsa: tomates tatemados, "
        "chiles, especias, ajo. Ambiente de cocina tradicional. Luz natural. "
        "Frasco completo y sin alteraciones, etiqueta visible."
    ),
    "humor_picante": (
        "Fotografía dramática y divertida. El frasco de Salsa Bestial en primer plano "
        "con chiles habanero alrededor y vapor sutil de picante. Fondo rojo oscuro. "
        "Iluminación de producto intensa y llamativa. "
        "El frasco idéntico a la referencia: naranja, dorado, gorila en el logo."
    ),
    "educacion_sobre_salsas": (
        "Flat lay educativo profesional. Vista desde arriba. El frasco de Salsa Bestial "
        "en el centro rodeado de sus ingredientes: tomates tatemados, chiles secos variados, "
        "especias en cucharitas, ajo, cebolla asada. Superficie de madera clara. "
        "Frasco completo sin ninguna alteración visual."
    ),
    "default": (
        "Fotografía profesional de producto. El frasco de Salsa Bestial Tatemada Ahumada "
        "es el protagonista en una escena de fotografía gastronómica: mesa de madera rústica, "
        "ingredientes naturales alrededor, iluminación cálida profesional. "
        "Mantén el frasco exactamente como aparece en la referencia proporcionada: "
        "etiqueta naranja, tapa dorada, logo del gorila Bestial intactos. "
        "Resultado: imagen de nivel comercial lista para Instagram."
    ),
}


def _leer_imagen_bytes(ruta: Path) -> tuple[bytes, str]:
    """Lee una imagen y retorna (bytes, mime_type)."""
    with open(ruta, "rb") as f:
        datos = f.read()
    ext = ruta.suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
    return datos, mime


def _obtener_fotos_referencia() -> list[tuple[bytes, str]]:
    """Carga las fotos de referencia del producto para enviar a Gemini."""
    fotos = []
    for nombre_ref in ["frente", "completa"]:
        archivo = brand.ARCHIVOS_REFERENCIA.get(nombre_ref)
        if not archivo:
            continue
        ruta = settings.REFERENCIA_PRODUCTO_DIR / archivo
        if ruta.exists():
            fotos.append(_leer_imagen_bytes(ruta))

    if not fotos:
        for ruta in settings.REFERENCIA_PRODUCTO_DIR.glob("*.jpg"):
            if "recortado" not in ruta.stem.lower():
                fotos.append(_leer_imagen_bytes(ruta))
                if len(fotos) >= 2:
                    break
    return fotos[:2]


def _obtener_fotos_usuario() -> list[tuple[bytes, str]]:
    """Carga fotos del usuario de Google Drive como referencia adicional."""
    from agente.media.google_drive import obtener_material
    fotos_usuario = obtener_material("fotos_producto", max_archivos=1)
    resultado = []
    for ruta in fotos_usuario:
        try:
            resultado.append(_leer_imagen_bytes(ruta))
        except Exception:
            pass
    return resultado


def generar_foto_con_gemini(
    pilar: str = "default",
    concepto: str = "",
    formato: str = "post",
    sufijo: str = "",
) -> Optional[Path]:
    """
    Genera una fotografía profesional del producto usando Gemini 2.0 Flash.

    Envía las fotos de referencia del frasco + un prompt descriptivo.
    Gemini genera una escena lifestyle completa con el producto integrado.

    Retorna la ruta de la imagen generada o None si falla.
    """
    google_api_key = os.getenv("GOOGLE_API_KEY", "")
    if not google_api_key:
        logger.warning("GOOGLE_API_KEY no configurada — generación Gemini omitida")
        return None

    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        logger.error("SDK de Gemini no instalado. Ejecuta: pip install google-genai")
        return None

    # Seleccionar prompt según pilar
    prompt = ESCENAS.get(pilar, ESCENAS["default"])
    if concepto:
        prompt += f"\n\nConcepto específico del contenido: {concepto}"

    # Cargar imágenes de referencia
    fotos_ref = _obtener_fotos_referencia()
    fotos_usuario = _obtener_fotos_usuario()
    todas_las_fotos = fotos_ref + fotos_usuario

    if not todas_las_fotos:
        logger.error("No hay fotos de referencia del producto")
        return None

    logger.info(
        "Generando foto con Gemini 2.0 Flash | pilar: %s | %d fotos referencia",
        pilar, len(todas_las_fotos)
    )

    try:
        client = genai.Client(api_key=google_api_key)

        # Construir el contenido: fotos de referencia + prompt
        partes = []

        # Instrucción inicial
        partes.append(gtypes.Part.from_text(
            "Estas son las fotos de referencia del producto. "
            "Úsalas para entender exactamente cómo es el frasco, la etiqueta y el logo. "
            "NO alteres ningún elemento visual del producto."
        ))

        # Fotos de referencia
        for datos, mime in todas_las_fotos:
            partes.append(gtypes.Part.from_bytes(data=datos, mime_type=mime))

        # Prompt de generación
        partes.append(gtypes.Part.from_text(prompt))

        # Llamar a Gemini
        response = client.models.generate_content(
            model="gemini-2.0-flash-preview-image-generation",
            contents=[gtypes.Content(role="user", parts=partes)],
            config=gtypes.GenerateContentConfig(
                response_modalities=["image", "text"],
                temperature=0.7,
            ),
        )

        # Extraer imagen de la respuesta
        imagen_bytes = None
        for candidate in response.candidates:
            for part in candidate.content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    imagen_bytes = part.inline_data.data
                    break
            if imagen_bytes:
                break

        if not imagen_bytes:
            logger.error("Gemini no devolvió imagen en la respuesta")
            return None

        # Redimensionar al formato correcto si es necesario
        imagen_bytes = _ajustar_formato(imagen_bytes, formato)

        # Guardar
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre = f"gemini_{pilar}_{formato}_{ts}{sufijo}.jpg"
        ruta_salida = settings.MATERIAL_AGENTE_DIR / "imagenes_compuestas" / nombre
        ruta_salida.parent.mkdir(exist_ok=True)
        ruta_salida.write_bytes(imagen_bytes)

        logger.info("Foto generada con Gemini: %s", ruta_salida.name)
        return ruta_salida

    except Exception as e:
        logger.error("Error generando con Gemini: %s", e)
        return None


def _ajustar_formato(imagen_bytes: bytes, formato: str) -> bytes:
    """Redimensiona la imagen al formato de Instagram correcto."""
    try:
        from PIL import Image
        resoluciones = {
            "post":     (1080, 1080),
            "story":    (1080, 1920),
            "portrait": (1080, 1350),
            "reel":     (1080, 1920),
        }
        target_w, target_h = resoluciones.get(formato, (1080, 1080))
        img = Image.open(io.BytesIO(imagen_bytes)).convert("RGB")

        # Scale to cover
        ratio = max(target_w / img.width, target_h / img.height)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)

        # Center crop
        x = (img.width - target_w) // 2
        y = (img.height - target_h) // 3
        y = max(0, min(y, img.height - target_h))
        img = img.crop((x, y, x + target_w, y + target_h))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return buf.getvalue()
    except Exception as e:
        logger.warning("No se pudo ajustar formato: %s", e)
        return imagen_bytes


def generar_contenido_completo_gemini(
    pilar: str,
    hook: str,
    cta: str = "",
    concepto: str = "",
    tipo_contenido: str = "post",
    sufijo: str = "",
) -> Optional[Path]:
    """
    Pipeline completo con Gemini:
      1. Genera foto profesional del producto
      2. Agrega hook y CTA encima con tipografía de marca
      3. Retorna imagen lista para publicar en Instagram
    """
    from agente.generadores.generador_imagenes import generar_post_desde_material

    formato = "story" if tipo_contenido in ("story", "story_video", "reel") else "post"

    # 1. Generar foto profesional
    foto = generar_foto_con_gemini(
        pilar=pilar,
        concepto=concepto,
        formato=formato,
        sufijo=sufijo,
    )

    if not foto:
        logger.warning("Gemini no generó imagen — usando foto de referencia directa")
        from agente.generadores.generador_imagenes import _obtener_foto_producto
        foto = _obtener_foto_producto()
        if not foto:
            return None

    # 2. Agregar texto de marca
    return generar_post_desde_material(
        foto, hook, cta,
        tipo_contenido=formato,
        sufijo=sufijo,
    )
