"""
Genera imágenes profesionales de producto usando fal-ai/flux-pro/kontext.

flux-pro/kontext recibe la foto completa del frasco (tapa + etiqueta visibles)
y genera una escena lifestyle con el producto integrado en ella.

Costo: ~$0.045/imagen (vs nano-banana-pro que era $1/imagen y no incluía el frasco).
Fallback: si Kontext falla → retorna la foto de referencia completa sin alterar.

Regla crítica: NUNCA recortar el frasco y pegarlo sobre otro fondo.
El producto va como aparece en la foto de referencia original.

Flujo:
  salsa_tatemada_completa.jpg → fal-ai/flux-pro/kontext → imagen profesional
"""

import base64
import io
import logging
import os
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional

from config import settings
from config import brand_guidelines as brand

logger = logging.getLogger(__name__)

# Escenas predefinidas por pilar de contenido
ESCENAS_POR_PILAR = {
    "recetas_y_maridajes": [
        "crea una imagen donde esta salsa sea la protagonista de la mesa, pon vegetales tatemados alrededor, mesa de madera rustica, humo suave, luz calida",
        "salsa sobre tabla de madera con ingredientes frescos: tomates, chiles, cilantro, limones, chips de maiz, luz natural lateral",
        "frasco de salsa abierto junto a un taco de carne con la salsa siendo vertida, fotografia de comida apetitosa",
    ],
    "lifestyle_y_comunidad": [
        "salsa bestial en una mesa de asado al aire libre, carbon, carne a la parrilla de fondo, ambiente festivo",
        "frasco de salsa en picnic familiar, cesped verde, comida latinoamericana alrededor, luz de tarde dorada",
        "salsa en mesa de cocina moderna con especias y hierbas frescas, fotografia lifestyle autentica",
    ],
    "humor_picante": [
        "salsa bestial en primer plano dramatico, chiles de fondo desenfocados, iluminacion intensa como pelicula de accion",
        "frasco de salsa con humo de chile picante alrededor, escena dramatica y divertida",
    ],
    "behind_the_scenes": [
        "salsa bestial artesanal sobre mesa rustica con ingredientes naturales: tomates tatemados, chiles secos, especias, ambiente autentico artesanal",
        "proceso artesanal: frasco de salsa con ingredientes crudos alrededor, tabla de madera, estilo rustico",
    ],
    "promociones_y_lanzamientos": [
        "salsa bestial en presentacion elegante, fondo oscuro dramatico, iluminacion de estudio profesional, producto hero shot",
        "frasco de salsa en centro de composicion perfecta, fondo negro con luz lateral dorada, fotografia comercial premium",
    ],
    "educacion_sobre_salsas": [
        "salsa con ingredientes que la componen alrededor: chiles tatemados, tomates asados, ajo, especias, vista cenital educativa",
        "composicion flat lay de salsa bestial con todos los ingredientes naturales organizados, vista desde arriba",
    ],
    "beneficios_del_producto": [
        "salsa bestial en mesa de desayuno colombiano: arepa, huevos, fruta, ambiente de hogar calido",
        "frasco de salsa en comida tradicional latina, ambiente familiar autentico",
    ],
    "como_comprar": [
        "salsa bestial en presentacion de regalo, caja artesanal, papel kraft, lazo, mesa de madera",
        "frasco de salsa en bolsa de mercado artesanal, ambiente de tienda gourmet",
    ],
    "retos_y_pruebas_de_picante": [
        "salsa bestial en primer plano extremo con vapor de picante, fondo rojo dramatico, sensacion de intensidad",
        "frasco de salsa rodeado de chiles habanero y ghost pepper, composicion intensa y atrevida",
    ],
    "testimonios_y_ugc": [
        "salsa bestial en mesa de comedor familiar, comida compartida, ambiente calido y autentico",
        "frasco de salsa con comida hecha en casa, cocina de hogar real, luz natural",
    ],
    "default": [
        "crea una imagen donde esta salsa sea la protagonista de la mesa, pon vegetales tatemados alrededor, mesa de madera rustica, luz calida profesional",
        "frasco de salsa bestial sobre superficie de madera con ingredientes latinos: tomates, chiles, cilantro, fotografia comercial",
        "salsa bestial hero shot: producto centrado, fondo desenfocado de cocina, iluminacion suave y calida",
    ],
}


def _fotos_referencia_base64() -> list[str]:
    """
    Convierte las fotos de referencia del producto a URLs base64 para Fal.ai.
    Usa hasta 2 fotos (frente + completa) para que el modelo tenga buena referencia.
    """
    fotos = []
    for nombre_ref in ["frente", "completa"]:
        archivo = brand.ARCHIVOS_REFERENCIA.get(nombre_ref)
        if not archivo:
            continue
        ruta = settings.REFERENCIA_PRODUCTO_DIR / archivo
        if not ruta.exists():
            continue
        with open(ruta, "rb") as f:
            datos = base64.b64encode(f.read()).decode()
        fotos.append(f"data:image/jpeg;base64,{datos}")
        if len(fotos) >= 2:
            break

    if not fotos:
        # Buscar cualquier foto disponible
        for ruta in settings.REFERENCIA_PRODUCTO_DIR.glob("*.jpg"):
            if "recortado" not in ruta.stem:
                with open(ruta, "rb") as f:
                    datos = base64.b64encode(f.read()).decode()
                fotos.append(f"data:image/jpeg;base64,{datos}")
                if len(fotos) >= 2:
                    break

    return fotos


def _fotos_usuario_base64(tipo: str = "fotos_producto") -> list[str]:
    """
    Agrega fotos del usuario de Google Drive como referencia adicional.
    Máximo 2 fotos adicionales.
    """
    from agente.media.google_drive import obtener_material
    fotos_usuario = obtener_material(tipo, max_archivos=2)
    resultado = []
    for ruta in fotos_usuario:
        try:
            with open(ruta, "rb") as f:
                datos = base64.b64encode(f.read()).decode()
            ext = ruta.suffix.lower().replace(".", "")
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            resultado.append(f"data:{mime};base64,{datos}")
        except Exception as e:
            logger.warning("No se pudo leer foto de usuario: %s", e)
    return resultado


def _seleccionar_prompt(pilar: str, concepto: str = "") -> str:
    """Selecciona el prompt más apropiado según el pilar de contenido."""
    import random
    opciones = ESCENAS_POR_PILAR.get(pilar, ESCENAS_POR_PILAR["default"])
    base = random.choice(opciones)

    # Enriquecer con detalles del concepto si están disponibles
    extras = []
    concepto_lower = concepto.lower()
    if any(w in concepto_lower for w in ["taco", "tacos"]):
        extras.append("tacos al fondo")
    if any(w in concepto_lower for w in ["asado", "parrilla", "bbq"]):
        extras.append("parrilla de fondo")
    if any(w in concepto_lower for w in ["familia", "reunion"]):
        extras.append("ambiente familiar calido")
    if any(w in concepto_lower for w in ["halloween", "navidad", "temporada"]):
        extras.append("decoracion de temporada sutil")

    if extras:
        base = base + ", " + ", ".join(extras)

    return base


def _foto_referencia_completa() -> Optional[Path]:
    """Retorna la ruta de la foto completa del frasco (tapa + etiqueta visibles)."""
    nombre = brand.ARCHIVOS_REFERENCIA.get("completa")
    if nombre:
        ruta = settings.REFERENCIA_PRODUCTO_DIR / nombre
        if ruta.exists():
            return ruta
    # Buscar cualquier foto de referencia disponible como último recurso
    for ruta in settings.REFERENCIA_PRODUCTO_DIR.glob("*.jpg"):
        if "recortado" not in ruta.stem.lower():
            return ruta
    return None


def _foto_referencia_a_url_base64() -> Optional[str]:
    """Convierte la foto completa del frasco a data URL base64 para Fal.ai."""
    ruta = _foto_referencia_completa()
    if not ruta:
        return None
    with open(ruta, "rb") as f:
        datos = base64.b64encode(f.read()).decode()
    ext = ruta.suffix.lower().replace(".", "")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    return f"data:{mime};base64,{datos}"


def generar_foto_kontext(
    pilar: str = "default",
    concepto: str = "",
    formato: str = "post",
    sufijo: str = "",
) -> Optional[Path]:
    """
    Genera una fotografía profesional del producto usando fal-ai/flux-pro/kontext.

    Envía la foto completa del frasco (tapa con logo visible) como imagen de entrada.
    El modelo genera la misma botella integrada en una escena lifestyle nueva.

    Costo: ~$0.045/imagen. Fallback: foto de referencia completa sin modificar.
    """
    if not settings.FALAI_API_KEY:
        logger.warning("FALAI_API_KEY no configurada — generación kontext omitida")
        return None

    foto_b64 = _foto_referencia_a_url_base64()
    if not foto_b64:
        logger.error("No hay foto de referencia del producto (completa.jpg)")
        return None

    prompt = _seleccionar_prompt(pilar, concepto)
    logger.info("Generando foto con flux-pro/kontext | pilar: %s | formato: %s", pilar, formato)
    logger.debug("Prompt: %s", prompt)

    try:
        import fal_client
        os.environ["FAL_KEY"] = settings.FALAI_API_KEY

        resultado = fal_client.run(
            "fal-ai/flux-pro/kontext",
            arguments={
                "prompt": prompt,
                "image_url": foto_b64,
                "strength": 0.65,
                "num_inference_steps": 28,
                "guidance_scale": 3.5,
                "num_images": 1,
                "output_format": "jpeg",
            },
        )

        url_imagen = resultado["images"][0]["url"]
        resp = requests.get(url_imagen, timeout=60)
        if resp.status_code != 200:
            logger.error("Error descargando imagen kontext: %d", resp.status_code)
            return None

        # Redimensionar al formato de Instagram correcto
        imagen_bytes = _ajustar_formato_jpeg(resp.content, formato)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre = f"kontext_{pilar}_{formato}_{ts}{sufijo}.jpg"
        ruta_salida = settings.MATERIAL_AGENTE_DIR / "imagenes_compuestas" / nombre
        ruta_salida.parent.mkdir(exist_ok=True)
        ruta_salida.write_bytes(imagen_bytes)

        logger.info("Foto kontext generada: %s", ruta_salida.name)
        return ruta_salida

    except Exception as e:
        logger.error("Error en flux-pro/kontext: %s", e)
        return None


def _ajustar_formato_jpeg(imagen_bytes: bytes, formato: str) -> bytes:
    """Redimensiona la imagen al formato de Instagram correcto."""
    try:
        import io
        from PIL import Image
        resoluciones = {
            "post":     (1080, 1080),
            "story":    (1080, 1920),
            "portrait": (1080, 1350),
            "reel":     (1080, 1920),
        }
        target_w, target_h = resoluciones.get(formato, (1080, 1080))
        img = Image.open(io.BytesIO(imagen_bytes)).convert("RGB")

        ratio = max(target_w / img.width, target_h / img.height)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)

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


# Alias para compatibilidad con código existente
def generar_foto_producto_ia(
    pilar: str = "default",
    concepto: str = "",
    formato: str = "post",
    sufijo: str = "",
    incluir_fotos_usuario: bool = True,
) -> Optional[Path]:
    """Alias → usa flux-pro/kontext (reemplazó nano-banana-pro)."""
    return generar_foto_kontext(pilar=pilar, concepto=concepto, formato=formato, sufijo=sufijo)


def generar_contenido_completo(
    pilar: str,
    hook: str,
    cta: str = "",
    concepto: str = "",
    tipo_contenido: str = "post",
    sufijo: str = "",
) -> Optional[Path]:
    """
    Pipeline Camino A:
      1. flux-pro/kontext genera foto profesional del frasco en escena lifestyle
      2. Retorna la imagen generada (sin texto encima — el texto va en el caption de Instagram)

    Fallback: si Kontext falla → retorna la foto de referencia completa sin alterar.
    NO se recorta el frasco ni se hace compositing.
    """
    formato = "story" if tipo_contenido in ("story", "story_video", "reel") else "post"

    foto = generar_foto_kontext(
        pilar=pilar,
        concepto=concepto,
        formato=formato,
        sufijo=sufijo,
    )

    if not foto:
        # Fallback: foto de referencia completa tal como está
        logger.warning("Kontext falló — usando foto de referencia completa como fallback")
        foto = _foto_referencia_completa()
        if not foto:
            logger.error("No hay foto de referencia disponible como fallback")
            return None

    return foto


def generar_escenas_para_video(
    pilar: str,
    concepto: str = "",
    n: int = 4,
    formato: str = "story",
    sufijo: str = "",
) -> list[Path]:
    """
    Genera N imágenes del producto en escenas distintas para usar como frames
    de un slideshow de Reel o Story.

    Selecciona N prompts distintos del pilar (rotando la lista de ESCENAS_POR_PILAR)
    para que cada frame muestre el producto en una escena diferente.

    Retorna lista de rutas (puede ser menor a N si algunas fallan).
    Fallback por cada imagen fallida: foto de referencia completa.
    """
    import random
    opciones = ESCENAS_POR_PILAR.get(pilar, ESCENAS_POR_PILAR["default"])
    # Seleccionar N prompts distintos (con repetición si hay menos de N)
    seleccionados = (opciones * ((n // len(opciones)) + 1))[:n]
    random.shuffle(seleccionados)

    fotos: list[Path] = []
    for i, prompt_escena in enumerate(seleccionados):
        foto = generar_foto_kontext(
            pilar=pilar,
            concepto=f"{concepto} — escena: {prompt_escena[:50]}",
            formato=formato,
            sufijo=f"{sufijo}_frame{i+1}",
        )
        if foto:
            fotos.append(foto)
        else:
            # Frame fallido → usar foto de referencia como reemplazo
            ref = _foto_referencia_completa()
            if ref:
                fotos.append(ref)
            logger.warning("Frame %d/%d falló — usando referencia como reemplazo", i + 1, n)

    logger.info("Escenas generadas para video: %d/%d | pilar: %s", len(fotos), n, pilar)
    return fotos


# Mantener compatibilidad con código existente
def _recortar_producto(ruta_original: Path) -> Optional[Path]:
    """Extrae el producto con remove.bg. Cachea el resultado."""
    if not settings.REMOVEBG_API_KEY:
        logger.warning("REMOVEBG_API_KEY no configurada")
        return None

    cache_dir = settings.REFERENCIA_PRODUCTO_DIR / "recortados"
    cache_dir.mkdir(exist_ok=True)
    ruta_cache = cache_dir / f"{ruta_original.stem}_recortado.png"

    if ruta_cache.exists():
        return ruta_cache

    logger.info("Llamando remove.bg para: %s", ruta_original.name)
    with open(ruta_original, "rb") as f:
        respuesta = requests.post(
            "https://api.remove.bg/v1.0/removebg",
            files={"image_file": f},
            data={"size": "auto"},
            headers={"X-Api-Key": settings.REMOVEBG_API_KEY},
            timeout=30,
        )

    if respuesta.status_code != 200:
        logger.error("remove.bg error %d: %s", respuesta.status_code, respuesta.text[:200])
        return None

    ruta_cache.write_bytes(respuesta.content)
    return ruta_cache
