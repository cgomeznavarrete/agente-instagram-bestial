# Agente Instagram — Salsas Bestial

Agente de automatización de contenido para la cuenta de Instagram de **Salsas Bestial**, marca colombiana de salsas picantes artesanales. El usuario sube fotos/videos al bot de Telegram; Claude genera el caption; el usuario aprueba o corrige desde el celular; el agente publica en Instagram vía Graph API. Corre 24/7 en GitHub Actions sin necesidad de tener el PC encendido.

## Stack

- **Python 3.11** — CLI con `click`, UI con `rich`
- **Claude** (`claude-sonnet-4-6`) — generación de captions, carruseles y correcciones
- **Instagram Graph API v21.0** — publicación de posts, reels, stories y carruseles
- **Cloudinary** — hosting de imágenes/videos (única opción que acepta la Graph API)
- **Telegram Bot API** — recepción de material, aprobación y publicación desde el celular
- **Pillow** — generación de carruseles educativos (sin IA de imágenes)
- **MoviePy + ffmpeg** — conversión de imágenes a Reels MP4 con música
- **Fal.ai FLUX Kontext** — generación de fotos del producto con IA (opcional)
- **GitHub Actions** — ejecución 24/7 del bot y publicaciones programadas

## Arquitectura principal

```
Usuario (celular)
    │  envía foto/video por Telegram
    ▼
Bot de Telegram (bot.py) — corre en GitHub Actions 24/7
    │  genera caption con Claude
    │  sube a Cloudinary
    │  manda preview + botones al usuario
    ▼
Usuario aprueba con ✅ Publicar
    │
    ▼
publicar_item.py → Instagram Graph API → publicado
    │
    └─ biblioteca.json actualizado en GitHub via REST API
```

## Comandos del bot de Telegram

Todos se usan directamente desde el chat con el bot:

```
/publicar          → muestra el siguiente item pendiente con botones
/publicar reel     → fuerza tipo Reel
/publicar post     → fuerza tipo Post
/publicar story    → fuerza tipo Story
/hoy               → plan de publicación de hoy con previews
/estado            → lista completa de material en biblioteca
/carrusel <tema>   → genera carrusel educativo (Claude + Pillow)
/venta             → genera serie de 3 stories de conversión
/ayuda             → todos los comandos
```

### Botones al enviar material (foto/video)

Cuando el usuario envía una foto o video al bot:
1. El bot descarga el archivo de Telegram
2. Pregunta: **📚 Biblioteca** (guardar para después) o **🚀 Publicar ahora**
3. Pregunta el tipo: **📸 Post / 🎬 Reel / ⭕ Story**
4. Pregunta el pilar de contenido
5. Sube a Cloudinary inmediatamente (los archivos temporales se pierden si no)
6. Guarda en `datos/biblioteca.json` y commitea a GitHub

### Botones de aprobación en /publicar

```
✅ Publicar      → publica en Instagram en un thread (no bloquea el bot)
✍️ Corregir      → escribe instrucción → Claude reescribe → nuevo preview
⏭ Saltar         → submenú: Corregir / Ya lo publiqué / Pasar al siguiente
✅ Ya lo publiqué → marca como publicado sin volver a subir
```

## Comandos CLI (main.py)

```bash
# Iniciar el bot de Telegram localmente
python main.py bot

# Publicar el siguiente item de la biblioteca según horario del día
python main.py publicar-programado
python main.py publicar-programado --forzar --tipo reel

# Generar carrusel educativo
python main.py generar-carrusel --tema "curiosidades del picante" --slides 3

# Ver estado
python main.py estado

# Inicializar carpetas y verificar credenciales
python main.py inicializar
```

## Variables de entorno (.env)

```bash
ANTHROPIC_API_KEY=sk-ant-...
INSTAGRAM_ACCESS_TOKEN=...        # Page Access Token (expira cada 60 días)
INSTAGRAM_BUSINESS_ACCOUNT_ID=... # ID de la cuenta de Instagram Business
CLOUDINARY_URL=cloudinary://...   # Requerido — imgbb no funciona con Instagram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
GOOGLE_DRIVE_LOCAL_PATH=G:\Mi unidad\Salsas Bestial - Instagram
FALAI_API_KEY=...                 # Opcional — generación de imágenes con IA
GITHUB_TOKEN=...                  # Se inyecta automáticamente en GitHub Actions
```

## GitHub Actions — workflows activos

| Workflow | Trigger | Qué hace |
|---|---|---|
| `bot_telegram.yml` | Cron cada 5h + push a bot.py | Bot de Telegram 24/7 (auto-reinicio) |
| `publicar_programado.yml` | Cron 11:30am y 6:30pm COL | Publica según biblioteca + avisa por Telegram |
| `ejecutar_semana.yml` | Cron lunes 9am COL | Genera calendario + contenido semanal |
| `analizar_metricas.yml` | Cron domingo 10pm COL | Descarga métricas y genera reporte |

### Bot 24/7 sin PC

El workflow `bot_telegram.yml` tiene `cron: '0 */5 * * *'` — se reinicia automáticamente cada 5 horas antes de que GitHub Actions lo corte (límite: 6h por job). Con `cancel-in-progress: true`, el nuevo run cancela el anterior sin interrupción perceptible.

### Horarios de publicación automática

`publicar_programado.yml` dispara a las **11:30am** y **6:30pm** hora Colombia:
- Lunes, Miércoles, Viernes → Story + Post
- Martes, Jueves → Reel
- El workflow envía preview a Telegram 30 min antes, espera aprobación manual, luego publica

## Biblioteca de contenido (biblioteca.json)

Todos los items que el usuario envía al bot se guardan en `datos/biblioteca.json`. El bot commitea este archivo a GitHub via REST API después de cada operación, para que persista entre reinicios.

### Tipos de item

| tipo | es_carrusel | Descripción |
|---|---|---|
| `post` | false | Imagen estática para el feed |
| `post` | true | Carrusel de múltiples imágenes |
| `reel` | false | Video o imagen que se publica como Reel con música |
| `story` | false | Imagen o video para Stories |

> Los carruseles usan `tipo: "post"` con `es_carrusel: true`. La búsqueda por tipo `"carrusel"` busca automáticamente en `"post"` también.

### Estados de un item

```
pendiente → publicado
         → descartado
```

## Publicación en Instagram (publicar_item.py)

| Tipo de archivo | Cómo se publica |
|---|---|
| Imagen → Reel | Convertida a MP4 9:16 con música via MoviePy → Cloudinary → Graph API REELS |
| Imagen → Post | Intentar como Reel con música; si falla → imagen estática |
| Imagen → Story | Convertida a video con música; si falla → imagen estática |
| Video → Reel/Story | Subido a Cloudinary → Graph API con `media_type=REELS/STORIES` |
| Carrusel | Sube slides individualmente → container CAROUSEL → media_publish |

**Polling REELS**: después de crear el container, el bot hace polling cada 10s hasta `status_code == FINISHED` (máx 180s). Si hay timeout → aborta con error.

## Token de Instagram — renovación

El token expira cada **60 días**. Es un **Page Access Token** (no de usuario).

1. Ir a [developers.facebook.com/tools/explorer](https://developers.facebook.com/tools/explorer)
2. En el selector de token, cambiar de usuario a **"Salsas.Bestial"** (la Página de Facebook)
3. Seleccionar permisos: `instagram_content_publish`, `instagram_basic`, `pages_read_engagement`
4. Generar token → copiar en `.env` como `INSTAGRAM_ACCESS_TOKEN`
5. Actualizar el secret `INSTAGRAM_ACCESS_TOKEN` en GitHub → Settings → Secrets

> Si no aparece `instagram_content_publish` en el Explorer, verificar que se está usando el token de **Página**, no de usuario.

## Estructura de carpetas clave

```
Agente Instagram/
├── main.py                          ← CLI principal (click)
├── CLAUDE.md                        ← Este archivo
├── .github/workflows/
│   ├── bot_telegram.yml             ← Bot 24/7 (cron cada 5h)
│   ├── publicar_programado.yml      ← Publicación automática 2x/día
│   ├── ejecutar_semana.yml          ← Calendario semanal (lunes 9am)
│   └── analizar_metricas.yml        ← Métricas (domingo 10pm)
├── config/
│   ├── settings.py                  ← Variables de entorno y constantes
│   ├── brand_guidelines.py          ← Identidad Salsas Bestial (tono, hashtags, CTAs)
│   ├── imagen_params.py             ← Specs de video/imagen para Instagram API
│   └── prompts/                     ← Plantillas Jinja2 para Claude
├── agente/
│   ├── telegram/
│   │   ├── bot.py                   ← Bot principal — polling + state machine
│   │   └── notificador.py           ← Helpers para enviar mensajes/fotos/videos
│   ├── instagram/
│   │   └── publicar_item.py         ← Publicación en Graph API (posts/reels/stories/carruseles)
│   ├── gestores/
│   │   └── biblioteca.py            ← CRUD de biblioteca.json (cola de publicación)
│   ├── claude/
│   │   └── cliente_claude.py        ← Wrapper Anthropic SDK con retry
│   ├── media/
│   │   └── subidor_cloudinary.py    ← Sube archivos a Cloudinary
│   └── generadores/
│       ├── generador_carrusel.py    ← Carruseles con Pillow
│       ├── imagen_compuesta.py      ← FLUX Kontext para fotos del producto
│       └── video_automatico.py      ← Conversión imagen→Reel/Story MP4
├── datos/
│   ├── biblioteca.json              ← Cola de publicación (commitada a GitHub)
│   ├── calendario_semanal.json      ← Calendario generado por ejecutar_semana
│   ├── metricas_instagram.json      ← Métricas descargadas de Graph API
│   └── historial_publicaciones.json ← Historial de lo publicado
├── musica/                          ← Tracks royalty-free para videos
│   ├── upbeat_latino_01.mp3
│   ├── chill_food_01.mp3
│   ├── energetico_01.mp3
│   └── humor_01.mp3
├── referencia_producto/
│   ├── salsa_tatemada_completa.jpg  ← Imagen oficial del producto (NUNCA modificar)
│   └── logo_circulo_amarillo.png
└── material_agente/
    ├── biblioteca/                  ← Copias locales del material subido (posts/reels/stories)
    ├── imagenes_compuestas/         ← Fotos generadas con FLUX Kontext
    ├── videos_generados/            ← Reels MP4 generados por MoviePy
    └── copies/                      ← Captions guardados por semana
```

## Estilo del copy (caption)

**Objetivo**: la persona se identifica con la experiencia, no con el producto.

- Primera línea: verdad/sensación que los amantes del picante reconocen al instante
- Cuerpo: la experiencia — olor, sabor, el momento (2-3 líneas)
- Pregunta de cierre obligatoria (genera conversación)
- CTA fijo: `Pídela aquí → https://wa.me/573005864523`
- 15 hashtags (mezcla español/inglés, definidos en `brand_guidelines.py`)
- Máximo 3 emojis, estratégicos

**No hacer**: mencionar la marca de forma publicitaria, bullets de beneficios, frases como "¡Descubre...", promesas médicas.

## Pilares de contenido

```python
recetas_y_maridajes | behind_the_scenes | humor_picante
educacion_sobre_salsas | testimonios_y_ugc | promociones_y_lanzamientos
como_comprar | beneficios_del_producto | retos_y_pruebas_de_picante
lifestyle_y_comunidad
```

## Reglas de publicación (Meta)

- Máximo 4 posts/día, 7 stories/día
- Mínimo 90 min entre publicaciones
- Solo Instagram Graph API oficial — no bots de terceros
- No auto-likes, auto-follows ni DMs masivos
- Cloudinary es la única opción de hosting que funciona con la Graph API (imgbb → error 9004)

## Música para videos automáticos

Los tracks royalty-free están en `/musica/`. Se seleccionan por mood según el pilar:

| Pilar | Mood |
|---|---|
| humor_picante | humor |
| retos_y_pruebas_de_picante | energetico |
| promociones_y_lanzamientos, como_comprar, beneficios_del_producto, lifestyle_y_comunidad | upbeat_latino |
| recetas_y_maridajes, behind_the_scenes, educacion_sobre_salsas, testimonios_y_ugc | chill_food |

Para agregar un track nuevo: copiar el MP3 a `/musica/` con el nombre `<mood>_02.mp3` y agregar al array en `config/imagen_params.py → MUSICA_POR_MOOD`.

## Bugs conocidos resueltos (historial)

| Fecha | Bug | Fix |
|---|---|---|
| May-2026 | Bot borraba todos los updates al arrancar → `/publicar` no respondía | Eliminado el drain; filtro por edad de 5 min |
| May-2026 | `tipo_forzado="carrusel"` mostraba "biblioteca vacía" con 16 items | Fallback completo `[reel, post, story]` siempre incluido |
| May-2026 | `rutas_slides` NameError al publicar carrusel | `rutas_slides = [Path(r) for r in item.archivos_carrusel]` |
| May-2026 | Claude falla → excepción silenciosa → sin respuesta al usuario | `try/except` con mensaje de error visible en Telegram |
| May-2026 | Boton Saltar no mostraba submenú | Submenú con 3 opciones (Corregir / Ya lo publiqué / Siguiente) |
| May-2026 | Imagen enviada como Reel fallaba en Cloudinary | Detectar extensión de imagen y convertir a MP4 primero |
| May-2026 | Bot se congelaba 3 min durante publicación de video | `_publicar_aprobado` corre en `threading.Thread(daemon=True)` |
| May-2026 | Caption truncado a 1024 chars en Telegram | Separar preview de media y texto en mensajes distintos |
