"""
Genera carruseles educativos para Instagram usando HTML/CSS + Playwright.

Flujo:
  Claude genera N datos curiosos sobre el tema
  → Playwright captura cada slide HTML como JPEG 1080×1080
  → Lista de JPEGs lista para publicar como carrusel

Diseño base validado: portada con blobs, contenido left-aligned, cierre negro con logo.
El estilo de portada varía entre carruseles (blobs / diagonal / minimal / split).
"""

import base64
import json
import logging
import random
from pathlib import Path
from datetime import datetime
from typing import Optional

from config import settings
from config import brand_guidelines as brand

logger = logging.getLogger(__name__)

# ── Paleta ────────────────────────────────────────────────────────────────────
_ESQUEMAS = [
    {"fondo": "#120C0C", "acento": "#F0BE1E", "texto": "#FFFFFF", "sub": "#F5EEDC"},
    {"fondo": "#B41414", "acento": "#F0BE1E", "texto": "#FFFFFF", "sub": "#FFD9D9"},
    {"fondo": "#5A0808", "acento": "#D25A0F", "texto": "#FFFFFF", "sub": "#F5EEDC"},
    {"fondo": "#1A0A0A", "acento": "#B41414", "texto": "#F5EEDC", "sub": "#DDBBBB"},
    {"fondo": "#D25A0F", "acento": "#F0BE1E", "texto": "#FFFFFF", "sub": "#FFF0E0"},
]

_GOOGLE_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue'
    '&family=Inter:wght@400;500;700;900&display=swap" rel="stylesheet">'
)

CALIDAD_JPEG = 95

_FONT_SIZE_TITULO = {
    (0,  30): 76,
    (30, 50): 64,
    (50, 70): 54,
    (70, 999): 46,
}

def _font_size(texto: str) -> int:
    n = len(texto)
    for (lo, hi), size in _FONT_SIZE_TITULO.items():
        if lo <= n < hi:
            return size
    return 46


# ── Logo ──────────────────────────────────────────────────────────────────────

def _logo_b64() -> str:
    """Logo circulo amarillo como data URL base64 para embeber en HTML."""
    for nombre in ["logo_circulo_amarillo.png", "logo_principal.png"]:
        ruta = settings.REFERENCIA_PRODUCTO_DIR / nombre
        if ruta.exists():
            with open(ruta, "rb") as f:
                datos = base64.b64encode(f.read()).decode()
            return f"data:image/png;base64,{datos}"
    return ""


# ── Portadas (4 estilos dinámicos) ────────────────────────────────────────────

def _portada_blobs(titulo_serie: str, total: int) -> str:
    """Estilo original validado: fondo oscuro con blobs circulares rojos."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">{_GOOGLE_FONTS}
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:1080px; height:1080px; overflow:hidden;
  background:#120C0C;
  font-family:'Inter',sans-serif;
  display:flex; flex-direction:column;
  align-items:center; justify-content:center;
  position:relative;
}}
.blob {{ position:absolute; border-radius:50%; }}
.b1 {{ width:500px; height:500px; background:#5A0808; opacity:0.55; top:-100px; left:-120px; }}
.b2 {{ width:400px; height:400px; background:#5A0808; opacity:0.4; top:-80px; right:-80px; }}
.b3 {{ width:480px; height:480px; background:#3D0505; opacity:0.5; bottom:-120px; left:-60px; }}
.badge {{
  background:#B41414; color:#F0BE1E;
  font-size:16px; font-weight:700; letter-spacing:5px;
  text-transform:uppercase; padding:10px 28px;
  margin-bottom:36px; position:relative;
}}
.num {{
  font-family:'Bebas Neue',sans-serif;
  font-size:160px; line-height:1;
  color:#F0BE1E; position:relative;
  margin-bottom:4px;
}}
.titulo {{
  font-size:72px; font-weight:900;
  color:#FFFFFF; text-align:center;
  line-height:1.05; letter-spacing:-1px;
  position:relative; margin-bottom:8px;
}}
.titulo span {{ color:#F0BE1E; }}
.sep {{ width:48px; height:3px; background:#B41414; margin:24px auto; position:relative; }}
.subtema {{
  font-size:22px; font-weight:700;
  letter-spacing:4px; text-transform:uppercase;
  color:#F5EEDC; opacity:0.55;
  text-align:center; position:relative;
  margin-bottom:40px;
}}
.desliza {{
  font-size:15px; font-weight:700;
  letter-spacing:4px; text-transform:uppercase;
  color:#F0BE1E; opacity:0.7;
  position:relative;
}}
.ghost-num {{
  position:absolute; bottom:-20px; right:40px;
  font-family:'Bebas Neue',sans-serif;
  font-size:220px; line-height:1;
  color:#FFFFFF; opacity:0.04;
}}
.handle {{
  position:absolute; bottom:40px;
  left:50%; transform:translateX(-50%);
  font-size:15px; font-weight:700;
  letter-spacing:3px; color:#FFFFFF; opacity:0.25;
}}
</style></head>
<body>
  <div class="blob b1"></div>
  <div class="blob b2"></div>
  <div class="blob b3"></div>
  <div class="badge">Salsas Bestial</div>
  <div class="num">{total}</div>
  <div class="titulo">datos que<br>no sabías</div>
  <div class="sep"></div>
  <div class="subtema">sobre {titulo_serie}</div>
  <div class="desliza">Desliza para descubrir →</div>
  <div class="ghost-num">{total}</div>
  <div class="handle">@SalsasBestial</div>
</body></html>"""


def _portada_diagonal(titulo_serie: str, total: int) -> str:
    """Franja diagonal roja que divide el fondo."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">{_GOOGLE_FONTS}
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:1080px; height:1080px; overflow:hidden;
  background:#0E0808;
  font-family:'Inter',sans-serif;
  display:flex; flex-direction:column;
  justify-content:center;
  position:relative;
}}
.stripe {{
  position:absolute; top:0; left:-200px; right:-200px; bottom:0;
  background:#B41414;
  transform:skewY(-12deg) translateY(60%);
  opacity:0.18;
}}
.content {{
  padding:0 90px;
  position:relative;
}}
.eyebrow {{
  font-size:14px; font-weight:700; letter-spacing:6px;
  text-transform:uppercase; color:#B41414;
  margin-bottom:28px;
}}
.num {{
  font-family:'Bebas Neue',sans-serif;
  font-size:200px; line-height:0.85;
  color:#F0BE1E; margin-bottom:16px;
}}
.titulo {{
  font-size:76px; font-weight:900; line-height:1.0;
  color:#FFFFFF; margin-bottom:32px;
  letter-spacing:-1px;
}}
.subtema {{
  font-size:18px; font-weight:500; letter-spacing:4px;
  text-transform:uppercase; color:#F5EEDC; opacity:0.45;
  margin-bottom:44px;
}}
.desliza {{
  display:inline-flex; align-items:center; gap:14px;
  font-size:14px; font-weight:700; letter-spacing:4px;
  text-transform:uppercase; color:#F0BE1E;
}}
.line {{ width:40px; height:2px; background:#F0BE1E; }}
.handle {{
  position:absolute; bottom:44px; right:90px;
  font-size:14px; font-weight:700; letter-spacing:3px;
  color:#FFFFFF; opacity:0.2;
}}
</style></head>
<body>
  <div class="stripe"></div>
  <div class="content">
    <div class="eyebrow">Salsas Bestial presenta</div>
    <div class="num">{total}</div>
    <div class="titulo">datos que no sabías</div>
    <div class="subtema">sobre {titulo_serie}</div>
    <div class="desliza"><div class="line"></div>desliza para descubrir</div>
  </div>
  <div class="handle">@SalsasBestial</div>
</body></html>"""


def _portada_minimal(titulo_serie: str, total: int) -> str:
    """Solo tipografía, sin decoraciones. Elegante y directo."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">{_GOOGLE_FONTS}
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:1080px; height:1080px; overflow:hidden;
  background:#0A0606;
  font-family:'Inter',sans-serif;
  display:flex; flex-direction:column;
  justify-content:space-between;
  padding:72px 90px;
}}
.top {{ display:flex; justify-content:space-between; align-items:center; }}
.marca {{ font-size:13px; font-weight:700; letter-spacing:5px; text-transform:uppercase; color:#FFFFFF; opacity:0.2; }}
.tag {{ font-size:13px; font-weight:700; letter-spacing:4px; text-transform:uppercase; color:#B41414; }}
.center {{ flex:1; display:flex; flex-direction:column; justify-content:center; }}
.num-row {{ display:flex; align-items:baseline; gap:16px; margin-bottom:24px; }}
.num {{
  font-family:'Bebas Neue',sans-serif;
  font-size:220px; line-height:0.85;
  color:#F0BE1E;
}}
.datos {{ font-size:32px; font-weight:900; color:#FFFFFF; opacity:0.15; }}
.titulo {{
  font-size:68px; font-weight:900; line-height:1.0;
  color:#FFFFFF; letter-spacing:-1px; margin-bottom:20px;
}}
.sep {{ width:56px; height:4px; background:#B41414; margin-bottom:24px; }}
.subtema {{
  font-size:19px; font-weight:500; letter-spacing:4px;
  text-transform:uppercase; color:#F5EEDC; opacity:0.4;
}}
.bottom {{ display:flex; justify-content:space-between; align-items:center; }}
.desliza {{
  font-size:13px; font-weight:700; letter-spacing:4px;
  text-transform:uppercase; color:#F0BE1E; opacity:0.6;
}}
.handle {{ font-size:13px; font-weight:700; letter-spacing:3px; color:#FFFFFF; opacity:0.2; }}
</style></head>
<body>
  <div class="top">
    <div class="marca">Salsas Bestial</div>
    <div class="tag">Dato #</div>
  </div>
  <div class="center">
    <div class="num">{total}</div>
    <div class="titulo">datos que no<br>sabías</div>
    <div class="sep"></div>
    <div class="subtema">sobre {titulo_serie}</div>
  </div>
  <div class="bottom">
    <div class="desliza">Desliza →</div>
    <div class="handle">@SalsasBestial</div>
  </div>
</body></html>"""


def _portada_split(titulo_serie: str, total: int) -> str:
    """Mitad izquierda negra, mitad derecha roja oscura. Número gigante a la derecha."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">{_GOOGLE_FONTS}
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:1080px; height:1080px; overflow:hidden;
  font-family:'Inter',sans-serif;
  display:flex;
}}
.left {{
  width:560px; background:#0E0808;
  display:flex; flex-direction:column;
  justify-content:center; padding:72px 64px;
  position:relative;
}}
.right {{
  flex:1; background:#5A0808;
  display:flex; flex-direction:column;
  align-items:center; justify-content:center;
  position:relative; overflow:hidden;
}}
.badge {{
  background:#B41414; color:#F0BE1E;
  font-size:13px; font-weight:700; letter-spacing:5px;
  text-transform:uppercase; padding:8px 20px;
  display:inline-block; margin-bottom:36px;
}}
.titulo {{
  font-size:66px; font-weight:900; line-height:1.02;
  color:#FFFFFF; letter-spacing:-1px; margin-bottom:28px;
}}
.subtema {{
  font-size:16px; font-weight:500; letter-spacing:4px;
  text-transform:uppercase; color:#F5EEDC; opacity:0.4;
  margin-bottom:40px;
}}
.desliza {{
  font-size:13px; font-weight:700; letter-spacing:4px;
  text-transform:uppercase; color:#F0BE1E;
}}
.big-num {{
  font-family:'Bebas Neue',sans-serif;
  font-size:320px; line-height:1;
  color:#F0BE1E; opacity:0.9;
  position:relative;
}}
.datos-label {{
  font-size:22px; font-weight:700; letter-spacing:3px;
  text-transform:uppercase; color:#FFFFFF; opacity:0.4;
  margin-top:-20px;
}}
.handle {{
  position:absolute; bottom:40px; left:64px;
  font-size:13px; font-weight:700; letter-spacing:3px;
  color:#FFFFFF; opacity:0.2;
}}
</style></head>
<body>
  <div class="left">
    <div class="badge">Salsas Bestial</div>
    <div class="titulo">datos que no sabías</div>
    <div class="subtema">sobre {titulo_serie}</div>
    <div class="desliza">Desliza para descubrir →</div>
    <div class="handle">@SalsasBestial</div>
  </div>
  <div class="right">
    <div class="big-num">{total}</div>
    <div class="datos-label">datos</div>
  </div>
</body></html>"""


def _html_portada(titulo_serie: str, total: int, estilo: str = "blobs") -> str:
    fns = {
        "blobs":    _portada_blobs,
        "diagonal": _portada_diagonal,
        "minimal":  _portada_minimal,
        "split":    _portada_split,
    }
    return fns.get(estilo, _portada_blobs)(titulo_serie, total)


# ── Slide de contenido ────────────────────────────────────────────────────────

def _html_slide_contenido(
    numero: int,
    total: int,
    titulo: str,
    subtitulo: Optional[str],
    esquema: dict,
) -> str:
    num_display = f"{numero:02d}"
    size = _font_size(titulo)
    sub_html = f'<p class="sub">{subtitulo}</p>' if subtitulo else ""
    dots = "".join(
        f'<div class="dot{"--on" if i + 1 == numero else ""}"></div>'
        for i in range(total)
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">{_GOOGLE_FONTS}
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:1080px; height:1080px; overflow:hidden;
  background:{esquema['fondo']};
  font-family:'Inter',sans-serif;
  display:flex; flex-direction:column;
}}
.topbar {{
  padding:44px 80px 0;
  display:flex; justify-content:space-between; align-items:center;
  flex-shrink:0;
}}
.num {{
  font-family:'Bebas Neue',sans-serif;
  font-size:22px; letter-spacing:4px;
  color:{esquema['acento']};
}}
.marca-top {{
  font-size:13px; font-weight:700; letter-spacing:4px;
  text-transform:uppercase; color:{esquema['texto']}; opacity:0.3;
}}
.content {{
  flex:1; display:flex; flex-direction:column; justify-content:center;
  padding:40px 80px; position:relative; overflow:hidden;
}}
.bg-num {{
  position:absolute; bottom:-20px; right:40px;
  font-family:'Bebas Neue',sans-serif; font-size:280px; line-height:1;
  color:{esquema['acento']}; opacity:0.07;
  pointer-events:none; user-select:none;
}}
.eyebrow {{
  font-size:13px; font-weight:700; letter-spacing:5px;
  text-transform:uppercase; color:{esquema['acento']}; opacity:0.8;
  margin-bottom:24px; position:relative;
}}
.titulo {{
  font-size:{size}px; font-weight:900; line-height:1.08;
  letter-spacing:-0.5px; color:{esquema['texto']};
  max-width:880px; position:relative; margin-bottom:30px;
  text-transform:uppercase;
}}
.sep {{
  width:44px; height:3px; border-radius:2px;
  background:{esquema['acento']}; margin-bottom:28px; position:relative;
}}
.sub {{
  font-size:24px; font-weight:400; line-height:1.6;
  color:{esquema['sub']}; max-width:820px; opacity:0.8; position:relative;
}}
.bottombar {{
  padding:0 80px 44px;
  display:flex; justify-content:space-between; align-items:center;
  flex-shrink:0;
}}
.dots {{ display:flex; gap:10px; align-items:center; }}
.dot {{
  width:7px; height:7px; border-radius:50%;
  background:{esquema['texto']}; opacity:0.2;
}}
.dot--on {{
  width:22px; height:7px; border-radius:4px;
  background:{esquema['acento']}; opacity:1;
}}
.marca-bot {{
  font-size:13px; font-weight:700; letter-spacing:3px;
  color:{esquema['texto']}; opacity:0.3;
}}
</style></head>
<body>
  <div class="topbar">
    <div class="num">{num_display} / {total:02d}</div>
    <div class="marca-top">Salsas Bestial</div>
  </div>
  <div class="content">
    <div class="bg-num">{num_display}</div>
    <div class="eyebrow">¿Sabías que?</div>
    <div class="titulo">{titulo}</div>
    <div class="sep"></div>
    {sub_html}
  </div>
  <div class="bottombar">
    <div class="dots">{dots}</div>
    <div class="marca-bot">@SalsasBestial</div>
  </div>
</body></html>"""


# ── Slide de cierre ───────────────────────────────────────────────────────────

def _html_slide_cierre(logo_b64: str = "") -> str:
    """Fondo negro, logo amarillo centrado, CTA, handle."""
    logo_html = (
        f'<img src="{logo_b64}" class="logo" alt="Salsas Bestial">'
        if logo_b64
        else '<div class="logo-text">SB</div>'
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">{_GOOGLE_FONTS}
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:1080px; height:1080px; overflow:hidden;
  background:#0A0606;
  font-family:'Inter',sans-serif;
  display:flex; flex-direction:column;
  align-items:center; justify-content:center;
  position:relative;
}}
/* Acento sutil en parte superior */
.top-accent {{
  position:absolute; top:0; left:0; right:0;
  height:5px; background:#B41414;
}}
/* Círculo decorativo de fondo */
.bg-circle {{
  position:absolute;
  width:700px; height:700px; border-radius:50%;
  background:#B41414; opacity:0.05;
  top:50%; left:50%;
  transform:translate(-50%,-50%);
}}
.logo {{ width:180px; height:180px; object-fit:contain; margin-bottom:44px; position:relative; }}
.logo-text {{
  width:180px; height:180px; border-radius:50%;
  background:#F0BE1E; display:flex; align-items:center; justify-content:center;
  font-family:'Bebas Neue',sans-serif; font-size:80px; color:#0A0606;
  margin-bottom:44px; position:relative;
}}
.titulo {{
  font-family:'Bebas Neue',sans-serif;
  font-size:88px; line-height:1.0; letter-spacing:1px;
  color:#FFFFFF; text-align:center;
  margin-bottom:32px; position:relative;
}}
.titulo span {{ color:#F0BE1E; }}
.sep {{
  width:52px; height:3px; background:#B41414; border-radius:2px;
  margin-bottom:32px; position:relative;
}}
.cta {{
  font-size:20px; font-weight:400; line-height:1.7;
  color:#F5EEDC; opacity:0.55; text-align:center;
  position:relative; margin-bottom:52px;
}}
.handle {{
  font-family:'Bebas Neue',sans-serif;
  font-size:36px; letter-spacing:4px;
  color:#F0BE1E; position:relative;
}}
</style></head>
<body>
  <div class="top-accent"></div>
  <div class="bg-circle"></div>
  {logo_html}
  <div class="titulo">Ya lo sabes,<br>prueba lo <span>bestial</span></div>
  <div class="sep"></div>
  <div class="cta">Link en bio · WhatsApp en bio</div>
  <div class="handle">@SalsasBestial</div>
</body></html>"""


# ── Screenshot ────────────────────────────────────────────────────────────────

def _screenshot_html(html: str, ruta: Path) -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1080, "height": 1080})
            page.set_content(html, wait_until="networkidle")
            page.screenshot(path=str(ruta), type="jpeg", quality=CALIDAD_JPEG, full_page=False)
            browser.close()
        return True
    except Exception as e:
        logger.error("Error screenshot Playwright: %s", e)
        return False


# ── Claude genera los datos ───────────────────────────────────────────────────

def _generar_datos_claude(tema: str, n: int) -> list[dict]:
    from agente.claude.cliente_claude import ClienteClaude

    prompt = (
        f"Eres copywriter experto de Salsas Bestial, marca de salsas artesanales picantes colombianas.\n"
        f"Genera {n} datos curiosos, sorprendentes o poco conocidos sobre: \"{tema}\".\n\n"
        f"Cada dato:\n"
        f"- Verídico y sorprendente, no obvio\n"
        f"- titulo: máximo 8 palabras, frase impactante (irá en letra grande, MAYÚSCULAS)\n"
        f"- subtitulo: 1 oración corta con el detalle/contexto (o null si no aplica)\n"
        f"- Escrito en español, tono atrevido y directo\n\n"
        f"Devuelve ÚNICAMENTE este JSON (sin markdown):\n"
        f'[{{"titulo": "...", "subtitulo": "..."}}, ...]\n'
    )

    cliente = ClienteClaude()
    try:
        respuesta = cliente.generar(
            prompt_sistema="Experto en contenido de redes sociales para marcas de alimentos picantes.",
            prompt_usuario=prompt,
            temperatura=0.85,
            max_tokens=1000,
            formato_json=True,
        )
        texto = respuesta.strip()
        if "```" in texto:
            texto = texto[texto.find("["):texto.rfind("]") + 1]
        datos = json.loads(texto)
        if isinstance(datos, list) and datos:
            return datos[:n]
    except Exception as e:
        logger.error("Error generando datos con Claude: %s", e)

    return [{"titulo": f"Dato {i+1} sobre {tema}", "subtitulo": None} for i in range(n)]


# ── Pipeline principal ────────────────────────────────────────────────────────

_ESTILOS_PORTADA = ["blobs", "diagonal", "minimal", "split"]

def generar_carrusel_educativo(
    tema: str,
    n_slides: int = 3,
    pilar: str = "educacion_sobre_salsas",
    sufijo: str = "",
) -> list[Path]:
    """
    Genera un carrusel educativo completo: portada + N datos + cierre.

    El estilo de portada varía aleatoriamente entre carruseles.
    Los esquemas de color de contenido rotan entre slides.
    Retorna lista de JPEGs 1080×1080 listos para carrusel de Instagram.
    """
    logger.info("Generando carrusel: tema='%s' | %d slides | pilar=%s", tema, n_slides, pilar)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta = settings.MATERIAL_AGENTE_DIR / "imagenes_compuestas" / f"carrusel_{ts}{sufijo}"
    carpeta.mkdir(parents=True, exist_ok=True)

    estilo = random.choice(_ESTILOS_PORTADA)
    logo = _logo_b64()
    rutas: list[Path] = []

    # Portada
    ruta = carpeta / "slide_00_portada.jpg"
    if _screenshot_html(_html_portada(tema, n_slides, estilo), ruta):
        rutas.append(ruta)
        logger.debug("Portada OK (estilo=%s)", estilo)
    else:
        logger.error("Portada falló")

    # Slides de contenido
    datos = _generar_datos_claude(tema, n_slides)
    for i, dato in enumerate(datos, start=1):
        esquema = _ESQUEMAS[(i - 1) % len(_ESQUEMAS)]
        ruta = carpeta / f"slide_{i:02d}.jpg"
        html = _html_slide_contenido(
            numero=i,
            total=n_slides,
            titulo=dato.get("titulo", f"Dato {i}"),
            subtitulo=dato.get("subtitulo"),
            esquema=esquema,
        )
        if _screenshot_html(html, ruta):
            rutas.append(ruta)
            logger.debug("Slide %d/%d OK", i, n_slides)
        else:
            logger.error("Slide %d falló", i)

    # Cierre
    ruta = carpeta / f"slide_{n_slides + 1:02d}_cierre.jpg"
    if _screenshot_html(_html_slide_cierre(logo), ruta):
        rutas.append(ruta)
        logger.debug("Cierre OK")
    else:
        logger.error("Cierre falló")

    logger.info("Carrusel generado: %d slides | estilo=%s | %s", len(rutas), estilo, carpeta.name)
    return rutas
