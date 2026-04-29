"""
Generador de carruseles educativos HTML → JPEG 1080×1080.

Estilo: minimalismo tipográfico — fondo sólido negro/rojo, sin ilustraciones,
texto alineado a la izquierda, número ghost en esquina inferior derecha,
puntos de progreso en la parte inferior.
"""

import base64
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

# Paleta de fondos — se rotan slide a slide
FONDOS = ["#000000", "#1A0000", "#6B0000", "#BB0000"]

_FONTS = '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap" rel="stylesheet">'

_BASE_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { width:1080px; height:1080px; overflow:hidden; position:relative; font-family:'Inter',sans-serif; }
"""


# ── Logo embebido ─────────────────────────────────────────────────────────────

def _logo_b64() -> str:
    ruta = settings.BASE_DIR / "referencia_producto" / "logo_circulo_amarillo.png"
    if ruta.exists():
        return "data:image/png;base64," + base64.b64encode(ruta.read_bytes()).decode()
    return ""


# ── Claude genera datos ───────────────────────────────────────────────────────

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


# ── Puntos de progreso ────────────────────────────────────────────────────────

def _dots(total: int, activo: int) -> str:
    """Genera indicador de puntos de progreso: •  •  —"""
    partes = []
    for i in range(1, total + 1):
        if i == activo:
            partes.append('<span style="background:#CC0000;width:28px;height:5px;border-radius:3px;display:inline-block;"></span>')
        else:
            partes.append('<span style="background:#555;width:10px;height:5px;border-radius:50%;display:inline-block;"></span>')
    return '<div style="display:flex;gap:8px;align-items:center;">' + "".join(partes) + '</div>'


# ── Portada ───────────────────────────────────────────────────────────────────

def _html_portada(tema: str, n_slides: int) -> str:
    tema_upper = tema.upper()
    # Ajustar tamaño del texto del tema según longitud
    fs_tema = "20px" if len(tema_upper) < 50 else "17px"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">{_FONTS}
<style>
{_BASE_CSS}
body {{ background:#000000; color:#FFFFFF; }}
.hdr-left {{ position:absolute;top:54px;left:72px;font-size:17px;font-weight:700;
  letter-spacing:3px;color:#666;text-transform:uppercase; }}
.hdr-right {{ position:absolute;top:54px;right:72px;font-size:17px;font-weight:700;
  letter-spacing:3px;color:#CC0000;text-transform:uppercase; }}
.numero {{ position:absolute;left:72px;top:260px;
  font-size:300px;font-weight:900;line-height:1;color:#F5B800;
  letter-spacing:-10px; }}
.subtexto {{ position:absolute;left:72px;top:590px;
  font-size:70px;font-weight:800;color:#FFFFFF;line-height:1.1; }}
.linea {{ position:absolute;left:72px;top:720px;
  width:60px;height:5px;background:#CC0000;border-radius:3px; }}
.tema {{ position:absolute;left:72px;top:760px;
  font-size:{fs_tema};font-weight:700;letter-spacing:3px;
  color:#888;text-transform:uppercase;max-width:900px; }}
.footer-left {{ position:absolute;bottom:52px;left:72px;
  font-size:18px;font-weight:700;letter-spacing:3px;
  color:#F5B800;text-transform:uppercase; }}
.footer-right {{ position:absolute;bottom:52px;right:72px;
  font-size:17px;font-weight:400;letter-spacing:2px;color:#666; }}
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


# ── Slide de contenido ────────────────────────────────────────────────────────

def _html_contenido(numero: int, total: int, titulo: str, subtitulo: str) -> str:
    fondo = FONDOS[numero % len(FONDOS)]

    n_chars = len(titulo)
    fs_titulo = "84px" if n_chars < 30 else "68px" if n_chars < 50 else "54px"

    # Color de detalles según fondo
    es_oscuro = fondo in ("#000000", "#1A0000")
    amarillo = "#F5B800"
    gris_header = "#888" if es_oscuro else "rgba(255,255,255,0.5)"
    color_ghost = "rgba(255,255,255,0.06)" if es_oscuro else "rgba(0,0,0,0.12)"

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">{_FONTS}
<style>
{_BASE_CSS}
body {{ background:{fondo}; color:#FFFFFF; }}
.hdr-left {{ position:absolute;top:54px;left:72px;font-size:17px;font-weight:700;
  letter-spacing:3px;color:{amarillo};text-transform:uppercase; }}
.hdr-right {{ position:absolute;top:54px;right:72px;font-size:17px;font-weight:700;
  letter-spacing:3px;color:{gris_header};text-transform:uppercase; }}
.etiqueta {{ position:absolute;left:72px;top:360px;
  font-size:18px;font-weight:700;letter-spacing:4px;color:{amarillo};text-transform:uppercase; }}
.titulo {{ position:absolute;left:72px;top:410px;right:72px;
  font-size:{fs_titulo};font-weight:900;line-height:1.08;
  text-transform:uppercase;color:#FFFFFF; }}
.linea {{ position:absolute;left:72px;top:700px;
  width:55px;height:5px;background:{amarillo};border-radius:3px; }}
.subtitulo {{ position:absolute;left:72px;top:738px;right:100px;
  font-size:30px;font-weight:400;line-height:1.55;color:rgba(255,255,255,0.88); }}
.ghost {{ position:absolute;bottom:-30px;right:50px;
  font-size:340px;font-weight:900;color:{color_ghost};
  line-height:1;letter-spacing:-15px;user-select:none; }}
.footer-dots {{ position:absolute;bottom:52px;left:72px; }}
.footer-right {{ position:absolute;bottom:52px;right:72px;
  font-size:17px;font-weight:400;letter-spacing:2px;color:{gris_header}; }}
</style></head><body>
  <div class="hdr-left">{numero:02d} / {total:02d}</div>
  <div class="hdr-right">Salsas Bestial</div>
  <div class="etiqueta">¿Sabías que?</div>
  <div class="titulo">{titulo.upper()}</div>
  <div class="linea"></div>
  <div class="subtitulo">{subtitulo}</div>
  <div class="ghost">{numero:02d}</div>
  <div class="footer-dots">{_dots(total, numero)}</div>
  <div class="footer-right">@SalsasBestial</div>
</body></html>"""


# ── Slide de cierre ───────────────────────────────────────────────────────────

def _html_cierre(total: int) -> str:
    logo_src = _logo_b64()
    logo_html = (
        f'<img src="{logo_src}" style="width:200px;height:200px;object-fit:contain;border-radius:50%;"/>'
        if logo_src else '<div style="width:200px;height:200px;background:#F5B800;border-radius:50%;"></div>'
    )

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">{_FONTS}
<style>
{_BASE_CSS}
body {{ background:#000000; color:#FFFFFF;
  display:flex;flex-direction:column;align-items:center;justify-content:center; }}
.glow {{ position:absolute;width:700px;height:700px;border-radius:50%;
  background:radial-gradient(circle,rgba(100,0,0,0.5) 0%,transparent 70%);
  top:50%;left:50%;transform:translate(-50%,-50%);pointer-events:none; }}
.logo {{ position:relative;z-index:1;margin-bottom:48px; }}
.frase {{ position:relative;z-index:1;
  font-size:72px;font-weight:900;text-align:center;line-height:1.1;
  max-width:840px; }}
.frase-yellow {{ color:#F5B800; }}
.linea {{ width:60px;height:5px;background:#CC0000;border-radius:3px;margin:36px auto; }}
.cta {{ font-size:22px;font-weight:400;letter-spacing:2px;
  color:#888;text-align:center; }}
.handle {{ margin-top:28px;font-size:28px;font-weight:700;
  letter-spacing:4px;color:#F5B800;text-transform:uppercase; }}
</style></head><body>
  <div class="glow"></div>
  <div class="logo">{logo_html}</div>
  <div class="frase">Ya lo sabes,<br>prueba lo <span class="frase-yellow">Bestial</span></div>
  <div class="linea"></div>
  <div class="cta">Link en bio · WhatsApp en bio</div>
  <div class="handle">@SalsasBestial</div>
</body></html>"""


# ── Renderer ──────────────────────────────────────────────────────────────────

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


# ── Pipeline principal ────────────────────────────────────────────────────────

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

    logger.info("Generando %d datos sobre '%s' con Claude...", n_slides, tema)
    datos = _generar_datos_claude(tema, n_slides)
    total = len(datos[:n_slides])

    rutas: list[Path] = []

    # Portada
    ruta_p = carpeta / "slide_00_portada.jpg"
    if _renderizar(_html_portada(tema, total), ruta_p):
        rutas.append(ruta_p)
        logger.info("Portada OK")

    # Slides de contenido
    for i, dato in enumerate(datos[:n_slides], 1):
        ruta_s = carpeta / f"slide_{i:02d}.jpg"
        html = _html_contenido(
            numero=i,
            total=total,
            titulo=dato.get("titulo", f"DATO {i}"),
            subtitulo=dato.get("subtitulo", ""),
        )
        if _renderizar(html, ruta_s):
            rutas.append(ruta_s)
            logger.info("Slide %d/%d OK", i, n_slides)

    # Cierre
    ruta_c = carpeta / f"slide_{n_slides+1:02d}_cierre.jpg"
    if _renderizar(_html_cierre(total), ruta_c):
        rutas.append(ruta_c)
        logger.info("Cierre OK")

    logger.info("Carrusel completo: %d slides en %s", len(rutas), carpeta.name)
    return rutas
