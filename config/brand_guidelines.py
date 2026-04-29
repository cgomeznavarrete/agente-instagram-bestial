"""
Identidad de marca de Salsas Bestial.
Este módulo se inyecta en TODOS los prompts de Claude como contexto fijo (cacheado).
NUNCA modificar sin revisar el impacto en la calidad del contenido generado.
"""

NOMBRE_MARCA = "Salsas Bestial"

TONO_VOZ = (
    "Atrevido, auténtico, apasionado y con humor sin perder la seriedad comercial. "
    "Como el amigo que cocina increíble y siempre tiene el ingrediente secreto."
)

PERSONALIDAD = (
    "Salsas Bestial no es una salsa más. Es actitud. Es ese toque que transforma "
    "cualquier comida en una experiencia. Hablamos directo, sin rodeos, con orgullo "
    "de lo que hacemos. Somos intensos pero accesibles, picantes pero no intimidantes."
)

AUDIENCIA_OBJETIVO = (
    "Amantes de la comida picante entre 22-45 años. Cocineros caseros curiosos. "
    "Foodlovers que comparten sus comidas en redes. Personas que buscan sabores "
    "auténticos y productos artesanales de calidad."
)

PILARES_CONTENIDO = [
    "recetas_y_maridajes",
    "behind_the_scenes",
    "humor_picante",
    "educacion_sobre_salsas",
    "testimonios_y_ugc",
    "promociones_y_lanzamientos",
    "como_comprar",
    "beneficios_del_producto",
    "retos_y_pruebas_de_picante",
    "lifestyle_y_comunidad",
]

HASHTAGS_FIJOS = [
    "#SalsasBestial",
    "#SalsaPicante",
    "#HotSauce",
    "#Picante",
    "#SalsaArtesanal",
]

HASHTAGS_NICHO = [
    "#FoodLovers",
    "#Foodie",
    "#RecetasFaciles",
    "#CocinaLatina",
    "#HotSauceLovers",
    "#SpicyFood",
    "#SalsaCasera",
    "#Chile",
    "#Gastronomia",
    "#ComidaPicante",
]

HASHTAGS_MODERADOS = [
    "#Comida",
    "#Recetas",
    "#Food",
    "#Cocina",
    "#Mexico",
    "#Colombia",
    "#Latinoamerica",
]

# Sabores disponibles (actualizar cuando se lancen nuevos productos)
SABORES_DISPONIBLES = [
    "Tatemada Ahumada",
]

# Archivos de referencia del producto (en referencia_producto/)
ARCHIVOS_REFERENCIA = {
    "frente": "salsa_tatemada_frente.jpg",        # etiqueta frontal clara
    "completa": "salsa_tatemada_completa.jpg",     # tapa + etiqueta visibles
    "logo_principal": "logo_principal.png",        # gorila + BESTIAL
    "logo_circulo": "logo_circulo_amarillo.png",   # sello circular de tapa
}

LINK_COMPRA_WHATSAPP = "https://wa.me/573005864523"

CANALES_VENTA = [
    "WhatsApp directo: https://wa.me/573005864523",
    "Enlace en bio (Instagram)",
    "Página web",
]

# ── Reglas absolutas — NUNCA violar ──────────────────────────────────────────
PROHIBICIONES_MARCA = [
    "NO alterar colores de etiquetas ni logo bajo ninguna circunstancia",
    "NO aplicar filtros de color sobre fotografías del frasco o etiqueta",
    "NO deformar, recortar ni modificar el logo de Salsas Bestial",
    "NO inventar productos o sabores que no existen",
    "NO cambiar el nombre de la marca",
    "NO hacer promesas médicas, nutricionales o de salud",
    "NO usar más de 3 emojis por copy",
    "NO imitar directamente a competidores",
    "NO generar imágenes 'plásticas' o artificiales del producto",
    "NO publicar más de 4 piezas al día (límite de seguridad Meta)",
]

# ── Estilo visual ─────────────────────────────────────────────────────────────
ESTILO_VISUAL = {
    "fotografia": "Food photography profesional y comercial",
    "iluminacion": "Luz natural, sombras suaves y cálidas",
    "texturas": "Superficies reales: madera, piedra, tela, pizarra",
    "composicion": "Regla de tercios, espacio en blanco intencional",
    "paleta": "Tonos cálidos: rojos, naranjas, tierras, con acentos oscuros",
    "producto": "El frasco siempre protagonista, nunca alterado",
    "evitar": "Fondos blancos de estudio, composiciones genéricas, look de IA",
}

# ── Instrucciones anti-detección IA para copies ───────────────────────────────
REGLAS_COPY_HUMANO = """
REGLAS PARA QUE EL COPY NO PAREZCA GENERADO POR IA:
- Nunca empezar con: "¡Descubre", "En el mundo de", "Hoy te traemos", "Imagina que"
- Usar frases incompletas y coloquiales ocasionalmente
- Variar drásticamente la longitud de las oraciones
- Incluir una referencia cultural específica al público latinoamericano en cada copy
- El hook debe ser: afirmación provocadora, pregunta retórica incómoda, o dato sorpresa
- Escribir como si fuera un mensaje de WhatsApp de alguien que ama la salsa picante
- Nunca listar beneficios con bullets en el caption de Instagram
- Máximo 3 emojis por copy, usados de forma estratégica, no decorativa
- Permitido el uso de puntos suspensivos y guiones para crear ritmo
- El copy debe sonar como una persona real, no como un anuncio corporativo
"""

# ── CTAs efectivos por objetivo ───────────────────────────────────────────────
CTAS_POR_OBJETIVO = {
    "compra": [
        "Enlace en bio. Sin excusas.",
        "El link está arriba. Tu boca lo sabe.",
        "Bio → pedir → esperar → disfrutar.",
        "¿Qué esperas? El link está en bio.",
    ],
    "engagement": [
        "¿Tú qué le pondrías primero?",
        "Comenta si aguantas el picante.",
        "Etiqueta a ese amigo cobarde.",
        "¿Team habanero o team chipotle?",
    ],
    "educacion": [
        "Guarda esto para la próxima cena.",
        "Comparte si aprendiste algo nuevo hoy.",
        "¿Ya sabías esto? Cuéntanos abajo.",
    ],
    "awareness": [
        "Síguenos para más.",
        "Activa la campanita. Vale la pena.",
        "Comparte con alguien que necesite esto en su vida.",
    ],
}
