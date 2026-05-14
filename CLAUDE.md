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
/semana            → plan de la semana completa (7 días) + insights de métricas
/estado            → lista completa de material en biblioteca
/carrusel <tema>   → genera carrusel educativo (Claude + Pillow)
/venta             → genera serie de 3 stories de conversión
/ayuda             → todos los comandos
```

### Botones al enviar material (foto/video)

Cuando el usuario envía una foto, video o `video_note` (video circular) al bot:
1. El bot descarga el archivo de Telegram
2. Pregunta: **📚 Biblioteca** (guardar para después) o **🚀 Publicar ahora**
3. Pregunta el tipo: **📸 Post / 🎬 Reel / ⭕ Story**
4. Pregunta el pilar de contenido
5. Sube a Cloudinary inmediatamente (los archivos temporales se pierden si no)
6. Guarda en `datos/biblioteca.json` y commitea a GitHub

> Videos en álbum (media group): el tipo se detecta por extensión del archivo (`.mp4/.mov` → video, resto → imagen). No se hardcodea.

### Botones de aprobación en /publicar

```
✅ Publicar      → post/reel/story: publica en Instagram en un thread
                   carrusel: envía slides a Telegram para subida manual con música
✍️ Corregir      → escribe instrucción → Claude reescribe → nuevo preview
⏭ Saltar         → submenú: Corregir / Ya lo publiqué / Pasar al siguiente
✅ Ya lo publiqué → marca como publicado sin volver a subir
```

### Botones en /hoy

Muestra el plan del día con caption completo y un menú por slot:

```
📅 Aprobar para 12pm/7pm  → post/reel/story: guarda en aprobaciones_hoy.json (Flujo A)
                             carrusel: envía slides a Telegram INMEDIATAMENTE (sin esperar workflow)
✍️ Modificar caption      → escribe instrucción → Claude reescribe → guarda en biblioteca
✅ Ya publiqué            → marca el item como publicado
⏭ Saltar                 → pausa ese slot para hoy
```

Si el item no tiene caption al mostrar `/hoy`, se genera automáticamente con Claude en ese momento y se guarda en `biblioteca.json`.

> **Carruseles en /hoy:** al tocar `📅 Aprobar`, el bot envía las fotos a Telegram en el acto — no hay que esperar al workflow de las 11:30am/6:30pm. El item queda marcado como publicado en `biblioteca.json`.

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

`publicar_programado.yml` dispara a las **11:30am** y **6:30pm** hora Colombia con ventanas amplias (10h–16h y 17h–23h) para absorber retrasos de GitHub Actions:

| Día | Mediodía (10–16h) | Noche (17–23h) |
|---|---|---|
| Lunes | post | reel |
| Martes | post | reel |
| **Miércoles** | **carrusel** ← slot dedicado | story |
| Jueves | reel | story |
| Viernes | post | reel |
| Sábado | post | story |
| Domingo | story | story |

**Slot de carrusel (miércoles mediodía):** El workflow (`publicar_programado`) busca en este orden:
1. **Carrusel educativo** (`pilar="educacion_sobre_salsas"`) — generado automáticamente cada lunes por `ejecutar_semana` vía `siguiente_carrusel_educativo()`
2. **Carrusel del usuario** — cualquier carrusel pendiente en la biblioteca
3. **Auto-genera en el momento** — si no hay ninguno, genera datos curiosos con `generar_carrusel_html()`

`ejecutar_semana` (lunes 9am COL) genera 1 carrusel de datos curiosos por semana. Si ya hay uno pendiente, no genera otro (evita duplicados). Esto garantiza 1 carrusel educativo por semana sin depender del estado de la biblioteca.

**Dos flujos de aprobación:**

- **Flujo A (pre-aprobado):** si el usuario aprobó el item desde `/hoy` antes de que corra el workflow, se activa directamente sin pedir confirmación en Telegram.
- **Flujo B (sin pre-aprobación):** el workflow envía el preview en Telegram y espera hasta 20 minutos por `✅ Publicar ahora` o `⏭ Saltar`.

> **Tip:** aprobar desde `/hoy` antes de las 11:30am/6:30pm evita la ventana de 20 minutos y elimina la race condition entre el bot y el workflow.

**Carruseles — flujo manual con música:**

Los carruseles **nunca se auto-publican** en Instagram. En cambio, tanto el Flujo A como el Flujo B llaman a `_enviar_carrusel_manual()` que:
1. Envía cada slide a Telegram como foto individual (`Slide 1/N`, `Slide 2/N`…)
2. Envía el caption en un mensaje aparte para copiar y pegar
3. Marca el item como publicado en `biblioteca.json`

El usuario sube el carrusel manualmente desde la app de Instagram y puede agregar música. Los carruseles auto-generados de datos curiosos siguen el mismo flujo.

## Biblioteca de contenido (biblioteca.json)

Todos los items que el usuario envía al bot se guardan en `datos/biblioteca.json`. El bot commitea este archivo a GitHub via REST API después de cada operación, para que persista entre reinicios.

### Tipos de item

| tipo | es_carrusel | Etiqueta en bot | Descripción |
|---|---|---|---|
| `post` | false | `📸 POST` | Imagen estática para el feed |
| `post` | true | `📖 POST - CARRUSEL` | Carrusel de múltiples imágenes |
| `reel` | false | `🎬 REEL` | Video o imagen que se publica como Reel con música |
| `story` | false | `⭕ STORY` | Imagen o video para Stories |

> Los carruseles usan `tipo: "post"` con `es_carrusel: true`. La búsqueda por tipo `"carrusel"` busca automáticamente en `"post"` también.

### /biblioteca — orden y límite

Muestra los items ordenados **FIFO** (más antiguo primero = el próximo en publicarse), hasta un máximo de 10 items por página. Muestra el conteo correcto por tipo: `📸 X posts · 🎬 X reels · ⭕ X stories · 📖 X carruseles`.

### Estados de un item

```
pendiente → publicado
         → descartado
```

## Helpers de módulo en bot.py

Dos funciones de módulo (fuera de la clase) reutilizables en todo el bot:

| Helper | Qué hace |
|---|---|
| `_tipo_display(item)` | Devuelve la etiqueta de tipo legible (`📸 POST`, `📖 POST - CARRUSEL`, etc.) revisando `es_carrusel` |
| `_enviar_carrusel_telegram(item)` | Envía slides numerados + caption a Telegram y marca el item como publicado. Usada en `/publicar`, `/hoy` y `publicar_programado` |

> Ambas están en `agente/telegram/bot.py` a nivel de módulo (no dentro de la clase `BotTelegram`). `main.py` tiene su propia copia de `_enviar_carrusel_manual()` con la misma lógica (corre en proceso separado de GitHub Actions).

## Comando /semana

`_mostrar_plan_semana_impl()` en `bot.py` — muestra:

1. **Plan 7 días**: simula la asignación FIFO de la biblioteca para cada slot del HORARIO (sin modificar datos). Indica qué item se publicará en cada slot, el tipo real (si hay fallback de tipo) y el pilar. Marca con ⚠️ los slots sin material.
2. **Insights de métricas** (desde `datos/metricas_instagram.json` y `datos/reel_ganador.json`):
   - Formato ganador (reel/post/carrusel) con likes promedio comparativo
   - Mejor día de la semana y mejor hora COL según historial
   - Reel ganador de la semana anterior con concepto y link
3. **Resumen**: slots cubiertos vs total, alerta si hay slots sin material.

La simulación FIFO usa contadores internos por tipo (`consumidos: dict[str, int]`) — no toca `biblioteca.json`.

## Publicación en Instagram (publicar_item.py)

| Tipo de archivo | Cómo se publica |
|---|---|
| Imagen → Reel | Convertida a MP4 9:16 con música via MoviePy → Cloudinary → Graph API `REELS` |
| Imagen → Post | Convertida a MP4 con música → Graph API `REELS`; si falla → imagen estática |
| Imagen → Story | Convertida a MP4 con música → Graph API `STORIES`; si falla → imagen estática |
| Video → Reel/Story | Subido a Cloudinary → Graph API con `media_type=REELS/STORIES` |
| Carrusel | ⚠️ **No se publica via API** — se envía a Telegram para subida manual con música |

**`media_type` correcto:** usar `REELS` (no `VIDEO` — deprecado). Para stories: `STORIES`. Siempre incluir `share_to_feed: true` en Reels.

**Polling REELS**: después de crear el container, el agente hace polling cada 10s hasta `status_code == FINISHED` (máx 180s). Si hay timeout → aborta con error.

**Pre-conversión en preview:** cuando el Flujo B envía el preview a Telegram, las imágenes se convierten a MP4 con música **antes** de mandar el mensaje. El video resultante se guarda en `biblioteca.json` (campo `cloudinary_url` + `nombre_archivo → .mp4`) para no volver a convertir al publicar.

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

Tracks actuales en git: `upbeat_latino_01.mp3`, `upbeat_latino_02.mp3`, `chill_food_01.mp3`, `energetico_01.mp3`, `humor_01.mp3`.

## Archivos de estado efímero (no se versionan)

| Archivo | Contenido | Se borra |
|---|---|---|
| `datos/aprobaciones_hoy.json` | Items aprobados desde `/hoy` para el día actual | Al día siguiente (fecha no coincide) |
| `datos/pausas_hoy.json` | Slots pausados desde `/hoy` | Al día siguiente |
| `datos/bot_ultimo_inicio.json` | Timestamp del último aviso de arranque | Nunca (cooldown 4h) |
| `datos/bot_estado.json` | Estado interno del bot entre reinicios | Nunca |
| `datos/pending_pubs.json` | Publicaciones en cola del bot | Nunca |

Estos archivos están en `.gitignore` — no se commitean al repo.

## Callbacks Telegram — prefijos y responsables

| Prefijo | Quién lo procesa | Qué hace |
|---|---|---|
| `pub_aprobar:` / `pub_rechazar:` | `bot.py` | Aprobación en flujo `/publicar` del bot |
| `prog_si:` / `prog_no:` | `publicar_programado` (main.py) | Aprobación en Flujo B del workflow |
| `hoy:aprobar:` | `bot.py` | Pre-aprobación desde `/hoy` |
| `hoy:modificar:` | `bot.py` | Modificar caption desde `/hoy` |
| `hoy:ya_publique:` | `bot.py` | Marcar publicado desde `/hoy` |
| `hoy:pausar_slot:` | `bot.py` | Pausar slot desde `/hoy` |

> El bot ignora callbacks `prog_si:`/`prog_no:` (son del workflow). El workflow usa offset propio y no compite con el bot porque los prefijos son distintos.

## Bugs conocidos resueltos (historial)

| Fecha | Bug | Fix |
|---|---|---|
| May-2026 | Bot borraba todos los updates al arrancar → `/publicar` no respondía | Eliminado el drain; filtro por edad de 5 min (luego 10 min) |
| May-2026 | `tipo_forzado="carrusel"` mostraba "biblioteca vacía" con 16 items | Fallback completo `[reel, post, story]` siempre incluido |
| May-2026 | `rutas_slides` NameError al publicar carrusel | `rutas_slides = [Path(r) for r in item.archivos_carrusel]` |
| May-2026 | Carrusel no se publicaba — slides vacíos | Usar `urls_guardadas` directamente cuando existen, sin iterar `rutas_slides` vacío |
| May-2026 | `media_type: VIDEO` deprecado → error en Graph API | Cambiado a `REELS` en todos los paths de video |
| May-2026 | Claude falla → excepción silenciosa → sin respuesta al usuario | `try/except` con mensaje de error visible en Telegram |
| May-2026 | Botón Saltar no mostraba submenú | Submenú con 3 opciones (Corregir / Ya lo publiqué / Siguiente) |
| May-2026 | Imagen enviada como Reel fallaba en Cloudinary | Detectar extensión de imagen y convertir a MP4 primero |
| May-2026 | Bot se congelaba 3 min durante publicación de video | `_publicar_aprobado` corre en `threading.Thread(daemon=True)` |
| May-2026 | Caption truncado a 1024 chars en Telegram | Separar preview de media y texto en mensajes distintos |
| May-2026 | Post aprobado pero nunca publicado (race condition) | Flujo A: pre-aprobados se publican directamente; Flujo B usa prefijos `prog_si/prog_no` distintos al bot |
| May-2026 | `/hoy` no mostraba el caption | Caption generado on-demand si el item no tiene uno; mostrado completo (800 chars) |
| May-2026 | Sin opción de modificar caption antes de aprobar | Botón `✍️ Modificar caption` en `/hoy`; Claude reescribe con instrucción del usuario |
| May-2026 | Video enviado al bot sin respuesta | `video_note` (video circular) sin manejar; tipo de album hardcodeado a "imagen" | Añadido handler `video_note`; tipo detectado por extensión |
| May-2026 | Imágenes de preview llegaban sin música | Flujo B convierte imagen a MP4+música antes de enviar el preview; guarda URL en biblioteca |
| May-2026 | Bot enviaba "🤖 Agente activo" cada 5h | Cooldown de 4h usando `bot_ultimo_inicio.json` |
| May-2026 | Posts publicados sin música (imagen estática) | `ffmpeg` binario no instalado en GitHub Actions → MoviePy fallaba silenciosamente → fallback a imagen. Fix: `sudo apt-get install -y ffmpeg` en ambos workflows |
| May-2026 | Carruseles sin preview visual al aprobar | `if cloudinary_url and not item.es_carrusel` excluía carruseles del preview. Fix: bloque dedicado que envía todos los slides individualmente antes de los botones |
| May-2026 | Carruseles se auto-publicaban sin música via Graph API | `publicar_programado` llamaba a `_ejecutar_publicacion()` para carruseles. Fix: helper `_enviar_carrusel_manual()` que envía slides a Telegram para subida manual |
| May-2026 | `/biblioteca` no mostraba los carruseles | Sort `reverse=True` ponía los items más nuevos al tope; carruseles antiguos quedaban fuera del límite MAX_VISIBLE. Fix: sort FIFO (`reverse=False`) + MAX_VISIBLE subido de 6 a 10 |
| May-2026 | Carrusel mostraba `📸 POST` en lugar de `📖 POST - CARRUSEL` | `tipo_label` usaba `item.tipo` ("post") sin revisar `es_carrusel`. Fix: helper `_tipo_display(item)` en bot.py aplicado en todos los puntos de display |
| May-2026 | `/hoy aprobar` en carrusel esperaba al workflow (podía auto-publicarse sin música) | Handler `hoy:aprobar` guardaba en `aprobaciones_hoy.json` para todos los tipos. Fix: si `es_carrusel`, llama `_enviar_carrusel_telegram()` en thread daemon inmediatamente |
| May-2026 | Carruseles de datos curiosos nunca se generaban (biblioteca tenía carruseles del usuario) | Condición "si vacío → genera" bloqueada por carruseles del usuario. Fix: `ejecutar_semana` genera 1 carrusel educativo cada lunes; slot miércoles prioriza `siguiente_carrusel_educativo()` (`pilar=educacion_sobre_salsas`) |

## Sistema de contexto (Obsidian + context/)

Para mantener coherencia entre sesiones de Claude:

- **`context/current.md`** (gitignored): estado actual del proyecto. Punto de entrada para Claude. Leer al iniciar cualquier sesión antes de hacer cambios.
- **Bóveda Obsidian**: `D:\20210729\cgome\Documents\Claude\Obsidian-Instagram-Bestial\` (local, fuera del repo)
  - `00-Context/` — estado activo (ProjectState, OpenThreads, NextActions)
  - `01-Sessions/` — historial de sesiones (una nota por sesión)
  - `02-Architecture/` — 10 ADRs con decisiones técnicas documentadas
  - `03-TribalKnowledge/` — 13 notas con gotchas y conocimiento implícito
  - `04-Strategy/` — pilares de contenido y experimentos
  - `05-Runbooks/` — procedimientos operativos paso a paso

> **Separación crítica**: existe una segunda bóveda `Obsidian-Bestial/` para el proyecto App Bestial (Flask). **Nunca** escribir en esa bóveda desde el Agente Instagram.

Al cerrar una sesión significativa: invocar `/save-session-instagram`.
