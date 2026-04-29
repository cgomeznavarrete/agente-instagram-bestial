"""
Generador profesional de imágenes para Instagram con Pillow.
Usa las fotos REALES del producto — sin compositing artificial.

Estrategia:
  - Template "orgánico":  foto del producto + overlay degradado + texto bold
  - Template "card":      fondo de marca + producto (recortado) + layout de texto
  - Template "story":     foto extendida a 9:16 + texto animado en video

El resultado se ve como contenido real, no generado por IA.
"""

import logging
import io
import random
from pathlib import Path
from datetime import datetime
from typing import Optional

from config import settings
from config import imagen_params as params
from config import brand_guidelines as brand

logger = logging.getLogger(__name__)

# ── Paleta de marca ───────────────────────────────────────────────────────────
ROJO_BESTIAL   = (180, 20,  20)    # #B41414  — rojo principal
ROJO_OSCURO    = ( 90,  8,   8)    # #5A0808  — rojo profundo
NARANJA        = (210, 90,  15)    # #D25A0F  — acento cálido
AMARILLO       = (240, 190, 30)    # #F0BE1E  — acento brillante
CREMA          = (245, 238, 220)   # #F5EEDC  — fondo claro
NEGRO_SUAVE    = ( 18,  12,  12)   # #120C0C  — negro cálido
BLANCO         = (255, 255, 255)
SOMBRA_TEXTO   = ( 0,   0,   0, 180)  # negro semitransparente para sombra

# ── Fuentes (orden de preferencia — las mejores primero) ─────────────────────
_FONTS_BOLD = [
    "C:/Windows/Fonts/impact.ttf",   # Impact — la más usada en contenido viral
    "C:/Windows/Fonts/ariblk.ttf",   # Arial Black
    "C:/Windows/Fonts/arialbd.ttf",  # Arial Bold
    "C:/Windows/Fonts/calibrib.ttf", # Calibri Bold
]
_FONTS_REGULAR = [
    "C:/Windows/Fonts/arialbd.ttf",  # Arial Bold para subtextos
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/calibri.ttf",
]


def _cargar_fuente(tamano: int, negrita: bool = True):
    """Carga la mejor fuente disponible en el sistema."""
    from PIL import ImageFont
    lista = _FONTS_BOLD if negrita else _FONTS_REGULAR
    for ruta in lista:
        if Path(ruta).exists():
            try:
                return ImageFont.truetype(ruta, tamano)
            except Exception:
                continue
    # Fallback: fuente básica de Pillow (siempre disponible)
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _obtener_producto_png() -> Optional[Path]:
    """
    Devuelve la ruta al PNG del producto recortado (remove.bg).
    Si no existe el recortado, intenta generarlo. Si falla, devuelve None.
    """
    cache_dir = settings.REFERENCIA_PRODUCTO_DIR / "recortados"
    # Buscar cualquier PNG recortado existente
    recortados = list(cache_dir.glob("*.png")) if cache_dir.exists() else []
    if recortados:
        return recortados[0]  # usar el primero disponible

    # Intentar recortar desde la foto completa
    try:
        from agente.generadores.imagen_compuesta import _recortar_producto
        foto_original = settings.REFERENCIA_PRODUCTO_DIR / brand.ARCHIVOS_REFERENCIA.get(
            "completa", "salsa_tatemada_completa.jpg"
        )
        if foto_original.exists():
            recortado = _recortar_producto(foto_original)
            return recortado
    except Exception as e:
        logger.warning("No se pudo obtener producto recortado: %s", e)
    return None


def _recortar_transparencia(img_rgba):
    """
    Recorta el espacio transparente alrededor del producto en un PNG RGBA.
    Evita que el producto parezca pequeño por márgenes vacíos en el PNG original.
    """
    from PIL import Image as PILImage
    bbox = img_rgba.getbbox()
    if bbox:
        margen = 10
        w, h = img_rgba.size
        x1 = max(0, bbox[0] - margen)
        y1 = max(0, bbox[1] - margen)
        x2 = min(w, bbox[2] + margen)
        y2 = min(h, bbox[3] + margen)
        return img_rgba.crop((x1, y1, x2, y2))
    return img_rgba


def _obtener_foto_producto(nombre_ref: str = "completa") -> Optional[Path]:
    """Devuelve la ruta a la foto oficial del producto."""
    archivo = brand.ARCHIVOS_REFERENCIA.get(nombre_ref, "salsa_tatemada_completa.jpg")
    ruta = settings.REFERENCIA_PRODUCTO_DIR / archivo
    if ruta.exists():
        return ruta
    # Buscar cualquier foto JPG disponible
    fotos = list(settings.REFERENCIA_PRODUCTO_DIR.glob("*.jpg"))
    if fotos:
        return fotos[0]
    logger.error("No se encontró foto de producto en %s", settings.REFERENCIA_PRODUCTO_DIR)
    return None


def _texto_envuelto(draw, texto: str, fuente, ancho_max: int) -> list[str]:
    """Divide el texto en líneas que quepan dentro de ancho_max."""
    palabras = texto.split()
    lineas = []
    linea_actual = ""
    for palabra in palabras:
        prueba = f"{linea_actual} {palabra}".strip()
        bbox = draw.textbbox((0, 0), prueba, font=fuente)
        w = bbox[2] - bbox[0]
        if w <= ancho_max:
            linea_actual = prueba
        else:
            if linea_actual:
                lineas.append(linea_actual)
            linea_actual = palabra
    if linea_actual:
        lineas.append(linea_actual)
    return lineas


def _dibujar_texto_con_sombra(
    draw,
    texto: str,
    fuente,
    posicion_y: int,
    ancho_imagen: int,
    margen: int = 60,
    color_texto: tuple = BLANCO,
    alineacion: str = "center",
) -> int:
    """
    Dibuja texto con sombra suave. Retorna la Y final (para apilar textos).
    """
    lineas = _texto_envuelto(draw, texto, fuente, ancho_imagen - margen * 2)
    y = posicion_y
    interlineado = 8

    for linea in lineas:
        bbox = draw.textbbox((0, 0), linea, font=fuente)
        w_texto = bbox[2] - bbox[0]
        h_texto = bbox[3] - bbox[1]

        if alineacion == "center":
            x = (ancho_imagen - w_texto) // 2
        elif alineacion == "left":
            x = margen
        else:
            x = ancho_imagen - w_texto - margen

        # Sombra (offset + blur simulado con múltiples offsets)
        for ox, oy in [(2, 2), (2, -2), (-2, 2), (-2, -2), (0, 3)]:
            draw.text((x + ox, y + oy), linea, font=fuente, fill=(0, 0, 0, 160))

        # Texto principal
        draw.text((x, y), linea, font=fuente, fill=color_texto)
        y += h_texto + interlineado

    return y + 10  # espacio extra entre bloques


def _aplicar_degradado_oscuro(imagen, zona: str = "bottom", intensidad: float = 0.75):
    """
    Aplica un degradado oscuro sobre la imagen para hacer el texto legible.
    zona: "bottom" | "top" | "both" | "full"
    """
    from PIL import Image as PILImage
    w, h = imagen.size
    overlay = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
    pixels = overlay.load()

    for y in range(h):
        if zona == "bottom":
            progreso = max(0, (y - h * 0.45) / (h * 0.55))
        elif zona == "top":
            progreso = max(0, (h * 0.45 - y) / (h * 0.45))
        elif zona == "both":
            prog_top = max(0, (h * 0.35 - y) / (h * 0.35))
            prog_bot = max(0, (y - h * 0.65) / (h * 0.35))
            progreso = max(prog_top, prog_bot)
        else:  # full
            progreso = intensidad
            pixels[0, y]  # just to test access
            for x in range(w):
                pixels[x, y] = (0, 0, 0, int(intensidad * 255))
            continue

        alpha = int(progreso * intensidad * 255)
        for x in range(w):
            pixels[x, y] = (0, 0, 0, alpha)

    if imagen.mode != "RGBA":
        imagen = imagen.convert("RGBA")
    resultado = PILImage.alpha_composite(imagen, overlay)
    return resultado.convert("RGB")


def _smart_crop(img, objetivo_w: int, objetivo_h: int):
    """
    Recorta inteligentemente centrando la imagen (center crop).
    Primero escala para cubrir el objetivo manteniendo aspecto.
    """
    from PIL import Image as PILImage
    ratio_w = objetivo_w / img.width
    ratio_h = objetivo_h / img.height
    ratio = max(ratio_w, ratio_h)
    nuevo_w = int(img.width * ratio)
    nuevo_h = int(img.height * ratio)
    img = img.resize((nuevo_w, nuevo_h), PILImage.LANCZOS)
    x = (nuevo_w - objetivo_w) // 2
    y = (nuevo_h - objetivo_h) // 3  # ligeramente arriba del centro (mejor para productos)
    return img.crop((x, y, x + objetivo_w, y + objetivo_h))


def _guardar_imagen(img, tipo: str, sufijo: str = "") -> Path:
    """Guarda la imagen en el directorio de imágenes compuestas."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"{tipo}_{ts}{sufijo}.jpg"
    ruta = settings.MATERIAL_AGENTE_DIR / "imagenes_compuestas" / nombre
    ruta.parent.mkdir(exist_ok=True)
    img.save(str(ruta), format="JPEG", quality=95)
    logger.info("Imagen generada: %s", ruta.name)
    return ruta


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE 1: POST ORGÁNICO — foto real + overlay + texto
# ─────────────────────────────────────────────────────────────────────────────
def generar_post_organico(
    hook: str,
    cta: str = "",
    foto_ref: str = "completa",
    sufijo: str = "",
) -> Optional[Path]:
    """
    El template más profesional: foto real del producto 1080x1080,
    degradado oscuro en parte inferior, hook bold arriba, CTA abajo.
    Resultado: idéntico a un post de food photographer real.
    """
    try:
        from PIL import Image as PILImage, ImageDraw, ImageEnhance
    except ImportError:
        logger.error("Pillow no instalado")
        return None

    foto_path = _obtener_foto_producto(foto_ref)
    if not foto_path:
        return None

    # Cargar y procesar foto
    img = PILImage.open(foto_path).convert("RGB")
    img = _smart_crop(img, 1080, 1080)

    # Ligero boost de saturación y contraste (food photography feel)
    img = ImageEnhance.Color(img).enhance(1.15)
    img = ImageEnhance.Contrast(img).enhance(1.08)

    # Degradado oscuro en zona inferior (donde va el texto)
    img = _aplicar_degradado_oscuro(img, zona="bottom", intensidad=0.82)

    # Capa de dibujo
    draw = ImageDraw.Draw(img)

    # ── Hook text (grande, arriba del degradado — ~65% Y) ──
    fuente_hook = _cargar_fuente(68, negrita=True)
    fuente_cta  = _cargar_fuente(42, negrita=False)

    y_hook = int(1080 * 0.62)
    y_hook = _dibujar_texto_con_sombra(draw, hook.upper(), fuente_hook, y_hook, 1080, margen=70)

    # ── CTA (más pequeño, debajo del hook) ──
    if cta:
        fuente_cta_actual = _cargar_fuente(40, negrita=False)
        _dibujar_texto_con_sombra(
            draw, cta, fuente_cta_actual, y_hook + 12, 1080,
            margen=70, color_texto=(255, 220, 100)  # amarillo cálido
        )

    return _guardar_imagen(img, "post_organico", sufijo)


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE 2: POST CARD — fondo de marca + producto prominente + texto
# ─────────────────────────────────────────────────────────────────────────────
def generar_post_card(
    hook: str,
    subtexto: str = "",
    cta: str = "",
    esquema_color: str = "rojo",  # "rojo" | "crema" | "negro"
    sufijo: str = "",
) -> Optional[Path]:
    """
    Card de marca: fondo degradado en colores de la marca, producto como protagonista central.
    Ideal para promociones, anuncios y contenido de brand awareness.
    """
    try:
        from PIL import Image as PILImage, ImageDraw, ImageFilter
    except ImportError:
        logger.error("Pillow no instalado")
        return None

    res = (1080, 1080)

    # ── Paleta por esquema ──
    esquemas = {
        "rojo":  {"fondo_top": (140, 10, 10), "fondo_bot": (30, 5, 5),
                  "texto": BLANCO, "acento": AMARILLO},
        "crema": {"fondo_top": (245, 238, 218), "fondo_bot": (215, 195, 165),
                  "texto": NEGRO_SUAVE, "acento": ROJO_BESTIAL},
        "negro": {"fondo_top": (22, 15, 15), "fondo_bot": (8, 5, 5),
                  "texto": BLANCO, "acento": NARANJA},
    }
    pal = esquemas.get(esquema_color, esquemas["rojo"])

    # ── Fondo degradado vertical ──
    fondo = PILImage.new("RGB", res)
    pixels = fondo.load()
    top = pal["fondo_top"]
    bot = pal["fondo_bot"]
    for y in range(res[1]):
        t = y / res[1]
        r = int(top[0] * (1 - t) + bot[0] * t)
        g = int(top[1] * (1 - t) + bot[1] * t)
        b = int(top[2] * (1 - t) + bot[2] * t)
        for x in range(res[0]):
            pixels[x, y] = (r, g, b)

    # ── Textura sutil (grano) ──
    import random as rnd
    for _ in range(15000):
        x = rnd.randint(0, res[0] - 1)
        y = rnd.randint(0, res[1] - 1)
        v = rnd.randint(-8, 8)
        px = pixels[x, y]
        pixels[x, y] = (
            max(0, min(255, px[0] + v)),
            max(0, min(255, px[1] + v)),
            max(0, min(255, px[2] + v)),
        )

    # ── Producto PNG (recortado con transparencia recortada) ──
    prod_path = _obtener_producto_png()
    if prod_path:
        prod = PILImage.open(prod_path).convert("RGBA")
        prod = _recortar_transparencia(prod)  # quitar márgenes vacíos
        # Escalar a 68% del alto de la imagen (producto prominente)
        nuevo_alto = int(res[1] * 0.68)
        ratio = nuevo_alto / prod.height
        nuevo_ancho = int(prod.width * ratio)
        prod = prod.resize((nuevo_ancho, nuevo_alto), PILImage.LANCZOS)

        # Centrar producto en la mitad inferior de la imagen
        x_prod = (res[0] - nuevo_ancho) // 2
        y_prod = int(res[1] * 0.26)

        # Sombra debajo del producto
        sombra = PILImage.new("RGBA", prod.size, (0, 0, 0, 0))
        canal_a = prod.split()[3]
        mask_sombra = canal_a.point(lambda p: int(p * 0.5))
        sombra.putalpha(mask_sombra)
        sombra_blur = sombra.filter(ImageFilter.GaussianBlur(25))
        fondo_rgba = fondo.convert("RGBA")
        fondo_rgba.paste(sombra_blur, (x_prod + 18, y_prod + 30), sombra_blur.split()[3])
        fondo = fondo_rgba.convert("RGB")

        fondo = fondo.convert("RGBA")
        fondo.paste(prod, (x_prod, y_prod), prod.split()[3])
        fondo = fondo.convert("RGB")
    else:
        # Sin recortado: usar foto normal escalada
        foto_path = _obtener_foto_producto()
        if foto_path:
            foto = PILImage.open(foto_path).convert("RGB")
            # Escalar y centrar en zona media
            escala_h = int(res[1] * 0.65)
            ratio = escala_h / foto.height
            escala_w = int(foto.width * ratio)
            foto = foto.resize((escala_w, escala_h), PILImage.LANCZOS)
            x = (res[0] - escala_w) // 2
            y = int(res[1] * 0.26)
            fondo.paste(foto, (x, y))

    # ── Texto ──
    draw = ImageDraw.Draw(fondo)
    fuente_hook = _cargar_fuente(72, negrita=True)
    fuente_sub   = _cargar_fuente(42, negrita=False)
    fuente_cta   = _cargar_fuente(36, negrita=True)

    margen = 70
    y_texto = 55

    y_texto = _dibujar_texto_con_sombra(
        draw, hook, fuente_hook, y_texto, res[0],
        margen=margen, color_texto=pal["texto"]
    )

    if subtexto:
        y_texto = _dibujar_texto_con_sombra(
            draw, subtexto, fuente_sub, y_texto + 8, res[0],
            margen=margen, color_texto=(*pal["acento"],)
        )

    if cta:
        y_cta = res[1] - 120
        _dibujar_texto_con_sombra(
            draw, f"→ {cta}", fuente_cta, y_cta, res[0],
            margen=margen, color_texto=pal["acento"]
        )

    # ── Logo marca (si existe) ──
    logo_path = settings.REFERENCIA_PRODUCTO_DIR / brand.ARCHIVOS_REFERENCIA.get(
        "logo_principal", "logo_principal.png"
    )
    if logo_path.exists():
        try:
            logo = PILImage.open(logo_path).convert("RGBA")
            logo_h = 80
            ratio_l = logo_h / logo.height
            logo_w = int(logo.width * ratio_l)
            logo = logo.resize((logo_w, logo_h), PILImage.LANCZOS)
            fondo_rgba2 = fondo.convert("RGBA")
            fondo_rgba2.paste(logo, (res[0] - logo_w - 30, 30), logo.split()[3])
            fondo = fondo_rgba2.convert("RGB")
        except Exception as e:
            logger.debug("No se pudo pegar logo: %s", e)

    return _guardar_imagen(fondo, "post_card", sufijo)


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE 3: STORY ORGÁNICA — foto extendida a 9:16 + texto
# ─────────────────────────────────────────────────────────────────────────────
def generar_story_organica(
    hook: str,
    cta: str = "",
    foto_ref: str = "completa",
    sufijo: str = "",
) -> Optional[Path]:
    """
    Story 1080x1920 con la foto real del producto.
    El fondo es la foto misma (blur extendido) con el producto centrado encima.
    Degradados arriba y abajo para texto.
    """
    try:
        from PIL import Image as PILImage, ImageDraw, ImageFilter, ImageEnhance
    except ImportError:
        logger.error("Pillow no instalado")
        return None

    res = (1080, 1920)
    foto_path = _obtener_foto_producto(foto_ref)
    if not foto_path:
        return None

    # ── Fondo: foto del producto expandida a 9:16, blur fuerte ──
    img_orig = PILImage.open(foto_path).convert("RGB")
    # Foto de fondo: escalada y recortada al formato story (blur)
    fondo = _smart_crop(img_orig.copy().filter(ImageFilter.GaussianBlur(40)), res[0], res[1])
    fondo = _aplicar_degradado_oscuro(fondo, zona="full", intensidad=0.60)

    # ── Producto PNG recortado (sin fondo) — si disponible, más limpio ──
    prod_path_png = _obtener_producto_png()
    if prod_path_png:
        prod_nit = PILImage.open(prod_path_png).convert("RGBA")
        prod_nit = _recortar_transparencia(prod_nit)
        prod_h = int(res[1] * 0.60)
        ratio = prod_h / prod_nit.height
        prod_w = int(prod_nit.width * ratio)
        prod_nit = prod_nit.resize((prod_w, prod_h), PILImage.LANCZOS)
        x_prod = (res[0] - prod_w) // 2
        y_prod = (res[1] - prod_h) // 2 + 40  # ligeramente bajo del centro
        # Sombra
        sombra = PILImage.new("RGBA", prod_nit.size, (0, 0, 0, 0))
        sombra.putalpha(prod_nit.split()[3].point(lambda p: int(p * 0.45)))
        sombra_blur = sombra.filter(ImageFilter.GaussianBlur(22))
        fondo_rgba = fondo.convert("RGBA")
        fondo_rgba.paste(sombra_blur, (x_prod + 15, y_prod + 25), sombra_blur.split()[3])
        fondo_rgba.paste(prod_nit, (x_prod, y_prod), prod_nit.split()[3])
        fondo = fondo_rgba.convert("RGB")
    else:
        # Foto original nítida centrada (fill vertical zone)
        prod_nit = PILImage.open(foto_path).convert("RGB")
        prod_h = int(res[1] * 0.62)
        ratio = prod_h / prod_nit.height
        prod_w = int(prod_nit.width * ratio)
        prod_nit = prod_nit.resize((prod_w, prod_h), PILImage.LANCZOS)
        x_prod = (res[0] - prod_w) // 2
        y_prod = (res[1] - prod_h) // 2 + 40
        fondo.paste(prod_nit, (x_prod, y_prod))

    # ── Degradados arriba y abajo para texto ──
    fondo = _aplicar_degradado_oscuro(fondo, zona="both", intensidad=0.88)

    # ── Texto ──
    draw = ImageDraw.Draw(fondo)
    fuente_hook = _cargar_fuente(78, negrita=True)
    fuente_cta  = _cargar_fuente(46, negrita=True)

    # Hook arriba
    y_hook = 80
    _dibujar_texto_con_sombra(draw, hook.upper(), fuente_hook, y_hook, res[0], margen=65)

    # CTA abajo
    if cta:
        _dibujar_texto_con_sombra(
            draw, cta, fuente_cta,
            res[1] - 180, res[0], margen=65,
            color_texto=(255, 220, 100)
        )

    return _guardar_imagen(fondo, "story_organica", sufijo)


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE 4: STORY CARD — fondo de marca + producto + texto prominente
# ─────────────────────────────────────────────────────────────────────────────
def generar_story_card(
    hook: str,
    subtexto: str = "",
    cta: str = "",
    esquema_color: str = "rojo",
    sufijo: str = "",
) -> Optional[Path]:
    """
    Story 1080x1920 con fondo de marca (degradado) y producto prominente.
    Igual que post_card pero en formato vertical.
    """
    try:
        from PIL import Image as PILImage, ImageDraw, ImageFilter
    except ImportError:
        logger.error("Pillow no instalado")
        return None

    res = (1080, 1920)

    esquemas = {
        "rojo":  {"top": (140, 10, 10), "bot": (20, 3, 3),
                  "texto": BLANCO, "acento": AMARILLO},
        "crema": {"top": (248, 240, 220), "bot": (210, 190, 155),
                  "texto": NEGRO_SUAVE, "acento": ROJO_BESTIAL},
        "negro": {"top": (25, 15, 15), "bot": (5, 3, 3),
                  "texto": BLANCO, "acento": NARANJA},
    }
    pal = esquemas.get(esquema_color, esquemas["rojo"])

    # Fondo degradado
    fondo = PILImage.new("RGB", res)
    px = fondo.load()
    for y in range(res[1]):
        t = y / res[1]
        r = int(pal["top"][0] * (1 - t) + pal["bot"][0] * t)
        g = int(pal["top"][1] * (1 - t) + pal["bot"][1] * t)
        b = int(pal["top"][2] * (1 - t) + pal["bot"][2] * t)
        for x in range(res[0]):
            px[x, y] = (r, g, b)

    # Producto
    prod_path = _obtener_producto_png()
    if prod_path:
        prod = PILImage.open(prod_path).convert("RGBA")
        prod = _recortar_transparencia(prod)  # quitar márgenes vacíos
        prod_h = int(res[1] * 0.58)  # 58% del alto de la story
        ratio = prod_h / prod.height
        prod_w = int(prod.width * ratio)
        prod = prod.resize((prod_w, prod_h), PILImage.LANCZOS)
        x_p = (res[0] - prod_w) // 2
        y_p = int(res[1] * 0.33)

        sombra = PILImage.new("RGBA", prod.size, (0, 0, 0, 0))
        sombra.putalpha(prod.split()[3].point(lambda p: int(p * 0.50)))
        sombra_blur = sombra.filter(ImageFilter.GaussianBlur(28))
        fondo_rgba = fondo.convert("RGBA")
        fondo_rgba.paste(sombra_blur, (x_p + 20, y_p + 35), sombra_blur.split()[3])
        fondo_rgba.paste(prod, (x_p, y_p), prod.split()[3])
        fondo = fondo_rgba.convert("RGB")
    else:
        foto_path = _obtener_foto_producto()
        if foto_path:
            foto = PILImage.open(foto_path).convert("RGB")
            fh = int(res[1] * 0.55)
            fw = int(foto.width * (fh / foto.height))
            foto = foto.resize((fw, fh), PILImage.LANCZOS)
            fondo.paste(foto, ((res[0] - fw) // 2, int(res[1] * 0.33)))

    draw = ImageDraw.Draw(fondo)
    fuente_hook = _cargar_fuente(88, negrita=True)
    fuente_sub  = _cargar_fuente(50, negrita=False)
    fuente_cta  = _cargar_fuente(44, negrita=True)

    y = 80
    y = _dibujar_texto_con_sombra(draw, hook, fuente_hook, y, res[0], margen=70, color_texto=pal["texto"])

    if subtexto:
        y = _dibujar_texto_con_sombra(draw, subtexto, fuente_sub, y + 10, res[0],
                                       margen=70, color_texto=(*pal["acento"],))

    if cta:
        _dibujar_texto_con_sombra(draw, f"↓  {cta}", fuente_cta,
                                   res[1] - 200, res[0], margen=70,
                                   color_texto=pal["acento"])

    # Logo — top center
    logo_path = settings.REFERENCIA_PRODUCTO_DIR / brand.ARCHIVOS_REFERENCIA.get(
        "logo_principal", "logo_principal.png"
    )
    if logo_path.exists():
        try:
            logo = PILImage.open(logo_path).convert("RGBA")
            lh = 100
            lw = int(logo.width * (lh / logo.height))
            logo = logo.resize((lw, lh), PILImage.LANCZOS)
            fa = fondo.convert("RGBA")
            fa.paste(logo, (res[0] - lw - 30, 30), logo.split()[3])
            fondo = fa.convert("RGB")
        except Exception:
            pass

    return _guardar_imagen(fondo, "story_card", sufijo)


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE 5: POST DESDE MATERIAL DEL USUARIO
# ─────────────────────────────────────────────────────────────────────────────
def generar_post_desde_material(
    ruta_foto: Path,
    hook: str,
    cta: str = "",
    tipo_contenido: str = "post",  # "post" | "story"
    sufijo: str = "",
) -> Optional[Path]:
    """
    Genera un post o story usando una foto aportada por el usuario
    (de Google Drive o material_usuario/).
    Simplemente la formatea, aplica texto de marca y lo guarda.
    """
    try:
        from PIL import Image as PILImage, ImageDraw, ImageEnhance
    except ImportError:
        logger.error("Pillow no instalado")
        return None

    if not ruta_foto.exists():
        logger.error("Foto de material no encontrada: %s", ruta_foto)
        return None

    if tipo_contenido in ("story", "reel"):
        res = (1080, 1920)
        zona_degradado = "both"
        tam_hook = 80
        y_hook = 85
    else:
        res = (1080, 1080)
        zona_degradado = "bottom"
        tam_hook = 70
        y_hook = int(1080 * 0.60)

    img = PILImage.open(ruta_foto).convert("RGB")
    img = _smart_crop(img, res[0], res[1])
    img = ImageEnhance.Color(img).enhance(1.12)
    img = ImageEnhance.Contrast(img).enhance(1.06)
    img = _aplicar_degradado_oscuro(img, zona=zona_degradado, intensidad=0.80)

    draw = ImageDraw.Draw(img)
    fuente_hook = _cargar_fuente(tam_hook, negrita=True)
    fuente_cta  = _cargar_fuente(44, negrita=True)

    y = _dibujar_texto_con_sombra(draw, hook.upper(), fuente_hook, y_hook, res[0], margen=65)

    if cta:
        y_cta = res[1] - 170 if tipo_contenido in ("story",) else y + 15
        _dibujar_texto_con_sombra(draw, cta, fuente_cta, y_cta, res[0],
                                   margen=65, color_texto=(255, 220, 100))

    tipo_label = "story_material" if tipo_contenido in ("story",) else "post_material"
    return _guardar_imagen(img, tipo_label, sufijo)


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL — selecciona template según tipo de contenido
# ─────────────────────────────────────────────────────────────────────────────
def generar_imagen(
    tipo_contenido: str,
    hook: str,
    cta: str = "",
    subtexto: str = "",
    pilar: str = "",
    ruta_material_usuario: Optional[Path] = None,
    sufijo: str = "",
) -> Optional[Path]:
    """
    Punto de entrada unificado para generar imágenes.

    Flujo prioritario:
      1. Si hay foto del usuario  → mejorar con IA → agregar texto → listo
      2. Sin foto del usuario     → usar foto de referencia del producto → agregar texto

    tipo_contenido: "post" | "carrusel" | "story" | "reel" | "story_video"
    """
    from agente.generadores.mejorador_foto import mejorar_foto

    es_story = tipo_contenido in ("story", "story_video", "reel")
    formato = "story" if es_story else "post"

    # ── Caso 1: el usuario aportó una foto → mejorar y usar como base ──
    if ruta_material_usuario and ruta_material_usuario.exists():
        logger.info("Mejorando foto del usuario: %s", ruta_material_usuario.name)
        foto_mejorada = mejorar_foto(
            ruta_original=ruta_material_usuario,
            formato=formato,
            usar_ia=bool(settings.FALAI_API_KEY),
            intensidad_ia=0.30,   # leve — solo mejora, no altera
        )
        if foto_mejorada:
            return generar_post_desde_material(
                foto_mejorada, hook, cta,
                tipo_contenido=formato,
                sufijo=sufijo,
            )

    # ── Caso 2: sin material del usuario → usar foto oficial del producto ──
    logger.info("Sin material del usuario — usando foto de referencia del producto")
    foto_ref = _obtener_foto_producto()
    if foto_ref:
        foto_mejorada = mejorar_foto(
            ruta_original=foto_ref,
            formato=formato,
            usar_ia=bool(settings.FALAI_API_KEY),
            intensidad_ia=0.25,
        )
        base = foto_mejorada if foto_mejorada else foto_ref
        return generar_post_desde_material(
            base, hook, cta,
            tipo_contenido=formato,
            sufijo=sufijo,
        )

    logger.error("No hay material disponible para generar imagen")
    return None
