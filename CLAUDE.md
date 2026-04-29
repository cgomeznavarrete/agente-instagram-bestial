# Agente Instagram — Salsas Bestial

Agente de automatización de contenido para la cuenta de Instagram de **Salsas Bestial**, marca colombiana de salsas picantes artesanales. Genera captions con Claude, envía a Telegram para aprobación y publica en Instagram vía Graph API.

## Stack

- **Python 3.x** — CLI con `click`, UI con `rich`
- **Claude** (`claude-sonnet-4-6`) — generación de captions e ideas
- **Instagram Graph API v21.0** — publicación de posts, reels, stories y carruseles
- **Cloudinary** — hosting de imágenes/videos (URLs públicas requeridas por la API)
- **Telegram Bot API** — aprobación del contenido antes de publicar
- **Pillow** — generación de carruseles educativos
- **Fal.ai FLUX Kontext** — generación de imágenes del producto con IA
- **Google Drive** (local sync) — carpeta donde el usuario sube fotos desde el celular

## Comandos principales

```bash
# Flujo principal: imagen tuya → caption → Telegram → Instagram
python main.py publicar-imagen "ruta/foto.jpg" --pilar recetas_y_maridajes

# Publicar automáticamente archivos nuevos de Google Drive
python main.py publicar-carpeta
# Posts/ → post del feed | Stories/ → story | Reels/ → reel

# Carrusel educativo (Claude + Pillow, sin IA de imágenes)
python main.py generar-carrusel --tema "curiosidades del picante" --slides 3 --telegram

# Reel slideshow (fotos de Drive o FLUX Kontext + música)
python main.py generar-reel --pilar lifestyle_y_comunidad --telegram

# Flujo semanal completo (calendario + copies + imágenes + Telegram)
python main.py ejecutar-semana

# Ver estado del agente
python main.py estado

# Inicializar carpetas y verificar credenciales
python main.py inicializar
```

## Flujo de publicar-imagen (confirmado funcionando)

```
python main.py publicar-imagen foto.jpg --pilar recetas_y_maridajes
  │
  ├─ 1. Claude genera caption (identidad/experiencia, no venta directa)
  │       CTA fijo: "Pídela aquí → https://wa.me/573005864523"
  │
  ├─ 2. Foto + caption enviados a Telegram con botones ✅/❌
  │
  ├─ 3. Si rechazo: bot pregunta qué cambiar → usuario escribe instrucción
  │       → Claude reescribe → v2 enviada a Telegram
  │
  └─ 4. Si aprobado: Cloudinary upload → Graph API container → media_publish
```

## Flujo de publicar-carpeta

Lee las carpetas de Google Drive configuradas en `GOOGLE_DRIVE_LOCAL_PATH`:
- `Posts/` — imágenes → post del feed con caption generado por Claude
- `Reels/` — videos → Reel con caption
- `Stories/` — imágenes o videos → Story (sin caption)

Registra archivos procesados en `datos/archivos_publicados.json` para no repetir.

## Variables de entorno (.env)

```bash
ANTHROPIC_API_KEY=sk-ant-...
INSTAGRAM_ACCESS_TOKEN=...        # Token de Página de Facebook (60 días)
INSTAGRAM_BUSINESS_ACCOUNT_ID=... # ID de la cuenta de Instagram Business
CLOUDINARY_URL=cloudinary://...   # Requerido — imgbb no funciona con Instagram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
GOOGLE_DRIVE_LOCAL_PATH=G:\Mi unidad\Salsas Bestial - Instagram
FALAI_API_KEY=...                 # Opcional — para generación de imágenes con IA
```

## Token de Instagram — renovación

El token expira cada **60 días**. Es un **Page Access Token** (no de usuario).

Para renovar:
1. Ir a [developers.facebook.com/tools/explorer](https://developers.facebook.com/tools/explorer)
2. En el selector de token, cambiar de usuario a **"Salsas.Bestial"** (la página de Facebook)
3. Seleccionar permisos: `instagram_content_publish`, `instagram_basic`, `pages_read_engagement`
4. Generar token → copiarlo en `.env` como `INSTAGRAM_ACCESS_TOKEN`

> Si no aparece `instagram_content_publish` en el Explorer, asegúrate de estar usando el token de **Página**, no de usuario.

## Estructura de carpetas clave

```
Agente Instagram/
├── main.py                    ← CLI principal
├── config/
│   ├── settings.py            ← Variables de entorno y constantes
│   ├── brand_guidelines.py    ← Identidad de Salsas Bestial (tono, hashtags, CTAs)
│   └── prompts/               ← Plantillas Jinja2 para Claude
├── agente/
│   ├── claude/cliente_claude.py   ← Wrapper Anthropic SDK con retry
│   ├── telegram/notificador.py    ← Envío de fotos/mensajes + polling de botones
│   ├── instagram/publicador.py    ← Publicación en Instagram Graph API
│   ├── media/subidor_cloudinary.py
│   └── generadores/
│       ├── generador_carrusel.py  ← Carruseles con Pillow (Camino B)
│       ├── imagen_compuesta.py    ← FLUX Kontext para fotos del producto (Camino A)
│       └── video_automatico.py    ← Reels slideshow con MoviePy
├── datos/
│   ├── archivos_publicados.json   ← Registro de archivos ya publicados
│   ├── historial_publicaciones.json
│   └── calendario_semanal.json
├── referencia_producto/
│   ├── salsa_tatemada_completa.jpg  ← Imagen oficial del producto (nunca modificar)
│   └── logo_circulo_amarillo.png
└── material_agente/
    ├── imagenes_compuestas/     ← Imágenes generadas por IA
    ├── videos_generados/        ← Reels MP4 generados
    └── copies/                  ← Captions guardados por semana
```

## Estilo del copy (caption)

**Objetivo**: la persona se identifica con la experiencia, no con el producto.

- Primera línea: verdad/sensación que los amantes del picante reconocen
- Cuerpo: la experiencia — olor, sabor, el momento
- CTA fijo: `Pídela aquí → https://wa.me/573005864523`
- 15 hashtags mezcla español/inglés
- Máximo 3 emojis, estratégicos

**No hacer**: mencionar la marca de forma publicitaria, bullets de beneficios, frases como "¡Descubre...", promesas médicas.

## Reglas de publicación (Meta)

- Máximo 4 posts/día, 7 stories/día
- Mínimo 90 min entre publicaciones
- Solo Instagram Graph API oficial — no bots de terceros
- No auto-likes, auto-follows ni DMs masivos

## Imágenes en Instagram

Instagram Graph API solo acepta URLs públicas con HTTPS. Se probaron varias opciones:
- **Cloudinary** ✅ — única opción confirmada funcionando
- imgbb ❌ — rechazado con error 9004
- URLs locales ❌ — no accesibles desde los servidores de Meta

## Carruseles educativos

Generados con Pillow (sin IA de imágenes). Estructura estándar:
- Slide 0: portada (4 estilos de diseño aleatorios: blobs, diagonal, minimal, split)
- Slides 1-N: datos/curiosidades generadas por Claude
- Slide final: fondo negro + logo amarillo + CTA

```bash
python main.py generar-carrusel --tema "historia del chile" --slides 3
```

## Pilar de contenido disponibles

```python
recetas_y_maridajes | behind_the_scenes | humor_picante
educacion_sobre_salsas | testimonios_y_ugc | promociones_y_lanzamientos
como_comprar | beneficios_del_producto | retos_y_pruebas_de_picante
lifestyle_y_comunidad
```
