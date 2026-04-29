"""
Parámetros de generación de imágenes y video.
Define especificaciones técnicas para Instagram Graph API y herramientas de generación.
"""

# ── Especificaciones de video para Instagram Graph API ────────────────────────
VIDEO_REELS = {
    "resolucion": (1080, 1920),
    "fps": 30,
    "codec_video": "libx264",
    "codec_audio": "aac",
    "bitrate_video": "3500k",
    "bitrate_audio": "128k",
    "duracion_min_seg": 3,
    "duracion_max_seg": 90,
    "formato_salida": "mp4",
    "aspecto": "9:16",
    "duracion_default_seg": 25,
}

VIDEO_STORIES = {
    "resolucion": (1080, 1920),
    "fps": 30,
    "codec_video": "libx264",
    "codec_audio": "aac",
    "bitrate_video": "3500k",
    "bitrate_audio": "128k",
    "duracion_max_seg": 60,
    "formato_salida": "mp4",
    "aspecto": "9:16",
    "duracion_default_seg": 15,
}

IMAGEN_POST = {
    "resolucion": (1080, 1080),
    "formato": "JPEG",
    "calidad": 95,
    "aspecto": "1:1",
}

IMAGEN_CARRUSEL = {
    "resolucion": (1080, 1080),
    "formato": "JPEG",
    "calidad": 95,
    "max_imagenes": 10,
    "min_imagenes": 2,
}

IMAGEN_STORY_ESTATICA = {
    "resolucion": (1080, 1920),
    "formato": "JPEG",
    "calidad": 95,
    "aspecto": "9:16",
}

# ── Parámetros de generación de fondos con IA (Fal.ai) ───────────────────────
GENERACION_FONDO = {
    "modelo": "fal-ai/flux/dev",
    "resolucion_post": (1080, 1080),
    "resolucion_story": (1080, 1920),
    "steps": 28,
    "guidance_scale": 7.5,
    "prompt_base_lifestyle": (
        "food photography background, professional commercial photo, "
        "natural soft lighting, warm tones, authentic textures, "
        "no text, no people, no bottles, no products, empty scene "
        "ready for product placement, high quality, realistic"
    ),
    "prompt_negativo": (
        "artificial, plastic look, CGI, 3D render, text, watermark, "
        "logo, bottles, products, people, faces, hands, low quality, "
        "blurry, distorted, oversaturated"
    ),
    "estilos": {
        "rustico_madera": (
            "rustic wooden table, grain texture, warm wood tones, "
            "natural light from side window, salt and pepper, herbs"
        ),
        "cocina_moderna": (
            "modern kitchen counter, marble surface, clean lines, "
            "soft neutral tones, natural daylight"
        ),
        "outdoor_bbq": (
            "outdoor barbecue setting, grill texture, smoke atmosphere, "
            "golden hour light, rustic metal surface"
        ),
        "mercado_mexicano": (
            "colorful Mexican market setting, clay pots, dried chiles, "
            "vibrant textiles in background, warm ambient light"
        ),
        "restaurante_casual": (
            "casual restaurant table, linen texture, candlelight ambiance, "
            "warm bokeh background, wooden surface"
        ),
        "mesa_familiar": (
            "family dining table, bread, fresh vegetables around, "
            "warm home lighting, cozy atmosphere"
        ),
        "pizarra_chef": (
            "black slate surface, chef's workspace, fresh ingredients around, "
            "dramatic side lighting, droplets of water"
        ),
    },
}

# ── Compositing: producto real sobre fondo generado ───────────────────────────
COMPOSITING = {
    "escala_producto_pct_post": 38,
    "escala_producto_pct_story": 32,
    "posicion_producto_post": "center_right",
    "posicion_producto_story": "center",
    "sombra_suave": True,
    "sombra_opacidad": 0.35,
    "sombra_blur": 12,
    "sombra_offset_px": (8, 12),
    "ajuste_brillo_producto": 1.05,
    "referencia_dir": "referencia_producto",
    "recortados_cache_dir": "referencia_producto/recortados",
}

# ── Texto superpuesto en videos ───────────────────────────────────────────────
TEXTO_VIDEO = {
    "fuente_hook": "Impact",
    "fuente_cuerpo": "Arial Bold",
    "fuente_cta": "Arial Bold",
    "tamano_hook_px": 72,
    "tamano_cuerpo_px": 52,
    "tamano_cta_px": 58,
    "color_texto_principal": "#FFFFFF",
    "color_sombra_texto": "#000000",
    "sombra_texto_opacidad": 0.8,
    "posicion_hook": "top_center",
    "posicion_cta": "bottom_center",
    "margen_px": 60,
    "animacion_hook": "fade_in",
    "duracion_animacion_seg": 0.5,
}

# ── Transiciones entre clips ──────────────────────────────────────────────────
TRANSICIONES = {
    "fade": {"duracion_seg": 0.4},
    "slide_left": {"duracion_seg": 0.3},
    "slide_right": {"duracion_seg": 0.3},
    "zoom_in": {"duracion_seg": 0.5},
    "cut": {"duracion_seg": 0.0},
}

TRANSICION_DEFAULT = "fade"

# ── Duración por imagen en slideshow ─────────────────────────────────────────
DURACION_IMAGEN_REEL_SEG = 4.0
DURACION_IMAGEN_STORY_SEG = 3.5

# ── Música: catálogo de tracks royalty-free ───────────────────────────────────
MUSICA_POR_MOOD = {
    "upbeat_latino": ["upbeat_latino_01.mp3", "upbeat_latino_02.mp3"],
    "chill_food": ["chill_food_01.mp3", "chill_food_02.mp3"],
    "energetico": ["energetico_01.mp3"],
    "romantico_gastro": ["romantico_gastro_01.mp3"],
    "humor": ["humor_01.mp3"],
}

MUSICA_POR_TIPO_CONTENIDO = {
    "reel_producto": "upbeat_latino",
    "reel_receta": "chill_food",
    "reel_humor": "humor",
    "reel_lifestyle": "chill_food",
    "story_promocional": "upbeat_latino",
    "story_cta": "energetico",
    "story_receta": "romantico_gastro",
}

VOLUMEN_MUSICA = 0.25
VOLUMEN_FADE_IN_SEG = 1.0
VOLUMEN_FADE_OUT_SEG = 1.5
