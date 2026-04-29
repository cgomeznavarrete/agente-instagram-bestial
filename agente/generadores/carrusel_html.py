"""
Generador de carruseles educativos HTML → JPEG 1080×1080.

6 temas visuales rotativos — ningún carrusel se verá igual:
  1. Bestial Rojo     — negro + rojo + amarillo (marca)
  2. Fuego Ámbar      — negro profundo + naranja quemado
  3. Carbón Naranja   — gris carbón + naranja fuego
  4. Verde Chile      — verde selva + lima eléctrica
  5. Índigo Picante   — azul índigo + naranja
  6. Borgoña Crema    — borgoña oscuro + crema cálida
"""

import base64
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from config import settings
from agente.claude.cliente_claude import ClienteClaude

logger = logging.getLogger(__name__)

SALIDA_DIR = settings.MATERIAL_AGENTE_DIR / "imagenes_compuestas"

_FONTS = '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap" rel="stylesheet">'

_BASE_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { width:1080px; height:1080px; overflow:hidden; position:relative; font-family:'Inter',sans-serif; }
"""

# ── Temas visuales ─────────────────────────────────────────────────────────────

TEMAS = {
    "bestial_rojo": {
        "nombre": "Bestial Rojo",
        "fondos": ["#000000", "#1A0000", "#6B0000", "#BB0000"],
        "acento": "#F5B800",
        "header_color": "#CC0000",
        "subtitulo_color": "rgba(255,255,255,0.88)",
        "ghost_base": "rgba(255,255,255,0.055)",
        "portada_numero_color": "#F5B800",
        "portada_fondo": "#000000",
        "dots_activo": "#CC0000",
        "dots_inactivo": "#555",
    },
    "fuego_ambar": {
        "nombre": "Fuego Ámbar",
        "fondos": ["#0D0800", "#241200", "#3D1F00", "#5C3000"],
        "acento": "#FF8C00",
        "header_color": "#FF6D00",
        "subtitulo_color": "rgba(255,220,180,0.90)",
        "ghost_base": "rgba(255,140,0,0.07)",
        "portada_numero_color": "#FF8C00",
        "portada_fondo": "#0D0800",
        "dots_activo": "#FF6D00",
        "dots_inactivo": "#4A3000",
    },
    "carbon_naranja": {
        "nombre": "Carbón Naranja",
        "fondos": ["#0E0E0E", "#161616", "#1E1E1E", "#282828"],
        "acento": "#FF5722",
        "header_color": "#FF7043",
        "subtitulo_color": "rgba(255,240,235,0.88)",
        "ghost_base": "rgba(255,87,34,0.06)",
        "portada_numero_color": "#FF5722",
        "portada_fondo": "#0E0E0E",
        "dots_activo": "#FF5722",
        "dots_inactivo": "#333",
    },
    "verde_chile": {
        "nombre": "Verde Chile",
        "fondos": ["#011A00", "#022800", "#043800", "#064A00"],
        "acento": "#76FF03",
        "header_color": "#64DD17",
        "subtitulo_color": "rgba(210,255,180,0.90)",
        "ghost_base": "rgba(118,255,3,0.06)",
        "portada_numero_color": "#76FF03",
        "portada_fondo": "#011A00",
        "dots_activo": "#64DD17",
        "dots_inactivo": "#1A3300",
    },
    "indigo_picante": {
        "nombre": "Índigo Picante",
        "fondos": ["#050014", "#0A0028", "#0F0040", "#160060"],
        "acento": "#FF6E40",
        "header_color": "#FF9100",
        "subtitulo_color": "rgba(255,235,210,0.90)",
        "ghost_base": "rgba(255,110,64,0.06)",
        "portada_numero_color": "#FF6E40",
        "portada_fondo": "#050014",
        "dots_activo": "#FF6E40",
        "dots_inactivo": "#1A0040",
    },
    "borgona_crema": {
        "nombre": "Borgoña Crema",
        "fondos": ["#150007", "#220010", "#35001A", "#4A0025"],
        "acento": "#F5E6C8",
        "header_color": "#E8D5A8",
        "subtitulo_color": "rgba(245,230,200,0.88)",
        "ghost_base": "rgba(245,230,200,0.055)",
        "portada_numero_color": "#F5E6C8",
        "portada_fondo": "#150007",
        "dots_activo": "#E8D5A8",
        "dots_inactivo": "#3A0015",
    },
}

TEMAS_KEYS = list(TEMAS.keys())


def _elegir_tema(semilla: str = "") -> dict:
    """Elige un tema visual basado en una semilla (el tema del carrusel).
    Mismo tema → mismo carrusel visual. Temas distintos → distintos colores.
    """
    if semilla:
        idx = int(hashlib.md5(semilla.encode()).hexdigest(), 16) % len(TEMAS_KEYS)
    else:
        idx = int(time.time()) % len(TEMAS_KEYS)
    clave = TEMAS_KEYS[idx]
    return TEMAS[clave]


# ── Logo embebido ──────────────────────────────────────────────────────────────

def _logo_b64() -> str:
    ruta = settings.BASE_DIR / "referencia_producto" / "logo_circulo_amarillo.png"
    if ruta.exists():
        return "data:image/png;base64," + base64.b64encode(ruta.read_bytes()).decode()
    return ""


# ── Claude genera datos ────────────────────────────────────────────────────────

def _generar_datos_claude(tema: str, n: int) -> list[dict]:
    cliente = ClienteClaude()
    raw = cliente.generar(
        prompt_sistema="Eres experto en gastronomía picante y cultura del chile.",
        prompt_usuario=(
            f"Genera {n} datos curiosos y sorprendentes sobre: \"{tema}\".\n"
            "Cada dato: verídico, impactante, relevante para amantes del picante.\n"
            "Devuelve SOLO este JSON sin markdown:\n"
            '[{"titulo":"máx 8 palabras en mayúsculas","subtitulo":"1-2 oraciones de detalle conciso"}]'
        ),
        temperatura=0.7,
        max_tokens=900,
    )
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return [{"titulo": f"DATO {i+1}", "subtitulo": tema} for i in range(n)]


# ── Puntos de progreso ─────────────────────────────────────────────────────────

def _dots(total: int, activo: int, tema: dict) -> str:
    partes = []
    for i in range(1, total + 1):
        if i == activo:
            partes.append(
                f'<span style="background:{tema["dots_activo"]};width:28px;height:5px;'
                f'border-radius:3px;display:inline-block;"></span>'
            )
        else:
            partes.append(
                f'<span style="background:{tema["dots_inactivo"]};width:10px;height:5px;'
                f'border-radius:50%;display:inline-block;"></span>'
            )
    return '<div style="display:flex;gap:8px;align-items:center;">' + "".join(partes) + '</div>'


# ── Portada ────────────────────────────────────────────────────────────────────

def _html_portada(tema_texto: str, n_slides: int, tema: dict) -> str:
    tema_upper = tema_texto.upper()
    fs_tema = "20px" if len(tema_upper) < 50 else "17px"
    acento = tema["acento"]
    header = tema["header_color"]
    num_color = tema["portada_numero_color"]
    fondo = tema["portada_fondo"]

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">{_FONTS}
<style>
{_BASE_CSS}
body {{ background:{fondo}; color:#FFFFFF; }}
.hdr-left {{ position:absolute;top:54px;left:72px;font-size:17px;font-weight:700;
  letter-spacing:3px;color:#666;text-transform:uppercase; }}
.hdr-right {{ position:absolute;top:54px;right:72px;font-size:17px;font-weight:700;
  letter-spacing:3px;color:{header};text-transform:uppercase; }}
.numero {{ position:absolute;left:60px;top:240px;
  font-size:310px;font-weight:900;line-height:1;color:{num_color};
  letter-spacing:-12px;opacity:0.95; }}
.subtexto {{ position:absolute;left:72px;top:590px;
  font-size:68px;font-weight:800;color:#FFFFFF;line-height:1.1; }}
.linea {{ position:absolute;left:72px;top:718px;
  width:60px;height:5px;background:{header};border-radius:3px; }}
.tema {{ position:absolute;left:72px;top:758px;
  font-size:{fs_tema};font-weight:700;letter-spacing:3px;
  color:#777;text-transform:uppercase;max-width:900px; }}
.footer-left {{ position:absolute;bottom:52px;left:72px;
  font-size:18px;font-weight:700;letter-spacing:3px;
  color:{acento};text-transform:uppercase; }}
.footer-right {{ position:absolute;bottom:52px;right:72px;
  font-size:17px;font-weight:400;letter-spacing:2px;color:#555; }}
</style></head><body>
  <div class="hdr-left">Salsas Bestial</div>
  <div class="hdr-right">Dato #</div>
  <div class="numero">{n_slides}</div>
  <div class="subtexto">datos que no<br>sabías</div>
  <div class="linea"></div>
  <div class="tema">Sobre {tema_upper}</div>
  <div class="footer-left">Desliza →</div>
  <div class="footer-right">@SalsasBestial</div>
</body></html>"""


# ── Slide de contenido ─────────────────────────────────────────────────────────

def _html_contenido(numero: int, total: int, titulo: str, subtitulo: str, tema: dict) -> str:
    fondos = tema["fondos"]
    fondo = fondos[numero % len(fondos)]
    acento = tema["acento"]
    header = tema["header_color"]
    subtitulo_color = tema["subtitulo_color"]
    ghost_color = tema["ghost_base"]

    n_chars = len(titulo)
    fs_titulo = "84px" if n_chars < 30 else "68px" if n_chars < 50 else "54px"

    # Para fondos muy oscuros el header va en acento; para fondos más claros va semitransparente
    gris_header = "rgba(255,255,255,0.45)"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">{_FONTS}
<style>
{_BASE_CSS}
body {{ background:{fondo}; color:#FFFFFF; }}
.hdr-left {{ position:absolute;top:54px;left:72px;font-size:17px;font-weight:700;
  letter-spacing:3px;color:{acento};text-transform:uppercase; }}
.hdr-right {{ position:absolute;top:54px;right:72px;font-size:17px;font-weight:700;
  letter-spacing:3px;color:{gris_header};text-transform:uppercase; }}
.etiqueta {{ position:absolute;left:72px;top:360px;
  font-size:18px;font-weight:700;letter-spacing:4px;color:{acento};text-transform:uppercase; }}
.titulo {{ position:absolute;left:72px;top:410px;right:72px;
  font-size:{fs_titulo};font-weight:900;line-height:1.08;
  text-transform:uppercase;color:#FFFFFF; }}
.linea {{ position:absolute;left:72px;top:700px;
  width:55px;height:5px;background:{acento};border-radius:3px; }}
.subtitulo {{ position:absolute;left:72px;top:738px;right:100px;
  font-size:30px;font-weight:400;line-height:1.55;color:{subtitulo_color}; }}
.ghost {{ position:absolute;bottom:-30px;right:44px;
  font-size:340px;font-weight:900;color:{ghost_color};
  line-height:1;letter-spacing:-15px;user-select:none; }}
.footer-dots {{ position:absolute;bottom:52px;left:72px; }}
.footer-right {{ position:absolute;bottom:52px;right:72px;
  font-size:17px;font-weight:400;letter-spacing:2px;color:{gris_header}; }}
/* Línea decorativa lateral */
.side-line {{ position:absolute;top:340px;left:42px;
  width:4px;height:420px;background:{header};border-radius:2px;opacity:0.6; }}
</style></head><body>
  <div class="hdr-left">{numero:02d} / {total:02d}</div>
  <div class="hdr-right">Salsas Bestial</div>
  <div class="side-line"></div>
  <div class="etiqueta">¿Sabías que?</div>
  <div class="titulo">{titulo.upper()}</div>
  <div class="linea"></div>
  <div class="subtitulo">{subtitulo}</div>
  <div class="ghost">{numero:02d}</div>
  <div class="footer-dots">{_dots(total, numero, tema)}</div>
  <div class="footer-right">@SalsasBestial</div>
</body></html>"""


# ── Slide de cierre ────────────────────────────────────────────────────────────

def _html_cierre(total: int, tema: dict) -> str:
    logo_src = _logo_b64()
    logo_html = (
        f'<img src="{logo_src}" style="width:200px;height:200px;object-fit:contain;border-radius:50%;"/>'
        if logo_src else
        f'<div style="width:200px;height:200px;background:{tema["acento"]};border-radius:50%;"></div>'
    )
    acento = tema["acento"]
    header = tema["header_color"]
    fondo = tema["portada_fondo"]

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">{_FONTS}
<style>
{_BASE_CSS}
body {{ background:{fondo}; color:#FFFFFF;
  display:flex;flex-direction:column;align-items:center;justify-content:center; }}
.glow {{ position:absolute;width:700px;height:700px;border-radius:50%;
  background:radial-gradient(circle,{header}55 0%,transparent 68%);
  top:50%;left:50%;transform:translate(-50%,-50%);pointer-events:none; }}
.logo {{ position:relative;z-index:1;margin-bottom:48px; }}
.frase {{ position:relative;z-index:1;
  font-size:72px;font-weight:900;text-align:center;line-height:1.1;
  max-width:840px; }}
.frase-accent {{ color:{acento}; }}
.linea {{ width:60px;height:5px;background:{header};border-radius:3px;margin:36px auto;
  position:relative;z-index:1; }}
.cta {{ font-size:22px;font-weight:400;letter-spacing:2px;
  color:#777;text-align:center;position:relative;z-index:1; }}
.handle {{ margin-top:28px;font-size:28px;font-weight:700;
  letter-spacing:4px;color:{acento};text-transform:uppercase;
  position:relative;z-index:1; }}
</style></head><body>
  <div class="glow"></div>
  <div class="logo">{logo_html}</div>
  <div class="frase">Ya lo sabes,<br>prueba lo <span class="frase-accent">Bestial</span></div>
  <div class="linea"></div>
  <div class="cta">Link en bio · WhatsApp en bio</div>
  <div class="handle">@SalsasBestial</div>
</body></html>"""


# ── Renderer ───────────────────────────────────────────────────────────────────

def _renderizar(html: str, ruta: Path) -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1080, "height": 1080})
            page.set_content(html, wait_until="networkidle")
            page.wait_for_timeout(2000)
            page.screenshot(path=str(ruta), full_page=False, type="jpeg", quality=95)
            browser.close()
        return True
    except Exception as e:
        logger.error("Error renderizando: %s", e)
        return False


# ── Pipeline principal ─────────────────────────────────────────────────────────

def generar_carrusel_html(
    tema: str,
    n_slides: int = 3,
    pilar: str = "educacion_sobre_salsas",
    sufijo: str = "",
) -> list[Path]:
    SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    carpeta = SALIDA_DIR / f"carrusel_html_{ts}{sufijo}"
    carpeta.mkdir(parents=True, exist_ok=True)

    # Elegir tema visual basado en el contenido — mismo tema = mismos colores
    tema_visual = _elegir_tema(tema)
    logger.info("Tema visual: %s | Generando %d datos sobre '%s' con Claude...",
                tema_visual["nombre"], n_slides, tema)

    datos = _generar_datos_claude(tema, n_slides)
    total = len(datos[:n_slides])

    rutas: list[Path] = []

    # Portada
    ruta_p = carpeta / "slide_00_portada.jpg"
    if _renderizar(_html_portada(tema, total, tema_visual), ruta_p):
        rutas.append(ruta_p)
        logger.info("Portada OK [%s]", tema_visual["nombre"])

    # Slides de contenido
    for i, dato in enumerate(datos[:n_slides], 1):
        ruta_s = carpeta / f"slide_{i:02d}.jpg"
        html = _html_contenido(
            numero=i,
            total=total,
            titulo=dato.get("titulo", f"DATO {i}"),
            subtitulo=dato.get("subtitulo", ""),
            tema=tema_visual,
        )
        if _renderizar(html, ruta_s):
            rutas.append(ruta_s)
            logger.info("Slide %d/%d OK", i, n_slides)

    # Cierre
    ruta_c = carpeta / f"slide_{n_slides+1:02d}_cierre.jpg"
    if _renderizar(_html_cierre(total, tema_visual), ruta_c):
        rutas.append(ruta_c)
        logger.info("Cierre OK")

    logger.info("Carrusel completo: %d slides en %s — tema: %s",
                len(rutas), carpeta.name, tema_visual["nombre"])
    return rutas
