"""
Bot de Telegram — interfaz principal del agente.

El usuario envía fotos/videos desde el celular. El bot pregunta:
  [📚 Biblioteca] → guarda para publicación programada
  [🚀 Publicar ahora] → flujo inmediato con aprobación

Comando /carrusel <tema> → genera carrusel HTML→PNG y pregunta dónde enviarlo.
Comando /estado → muestra cuánto material hay en la biblioteca.
"""

import json
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

import requests

from config import settings, brand_guidelines as brand
from agente.claude.cliente_claude import ClienteClaude
from agente.gestores.biblioteca import (
    agregar_item, agregar_carrusel, siguiente_pendiente,
    contar_pendientes, listar_pendientes, marcar_publicado, marcar_descartado,
    EXTENSIONES_IMAGEN, EXTENSIONES_VIDEO,
)
from agente.telegram.notificador import (
    _enviar_mensaje, _enviar_foto, _enviar_video,
    _enviar_foto_url, _enviar_video_url, BASE_URL,
)
from agente.media.subidor_cloudinary import SubidorCloudinary

logger = logging.getLogger(__name__)

PILARES_OPCIONES = [
    "recetas_y_maridajes",
    "lifestyle_y_comunidad",
    "humor_picante",
    "educacion_sobre_salsas",
    "behind_the_scenes",
    "promociones_y_lanzamientos",
]


# ── Helpers de polling ────────────────────────────────────────────────────────

def _get_updates(offset: Optional[int] = None, timeout: int = 20) -> list:
    params = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
    if offset:
        params["offset"] = offset
    try:
        resp = requests.get(f"{BASE_URL}/getUpdates", params=params, timeout=timeout + 10)
        return resp.json().get("result", [])
    except Exception as e:
        logger.error("Error getUpdates: %s", e)
        return []


def _answer_callback(callback_id: str, texto: str = ""):
    requests.post(f"{BASE_URL}/answerCallbackQuery", data={
        "callback_query_id": callback_id, "text": texto,
    }, timeout=10)


def _commit_json_github(ruta_local: str, repo_path: str, mensaje: str):
    """Sube cualquier archivo JSON a GitHub via REST API."""
    import base64, os
    import requests as _req
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return
    try:
        api_url = f"https://api.github.com/repos/cgomeznavarrete/agente-instagram-bestial/contents/{repo_path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        r_get = _req.get(api_url, headers=headers, timeout=15)
        sha = r_get.json().get("sha", "") if r_get.status_code == 200 else ""
        contenido = Path(ruta_local).read_text(encoding="utf-8")
        payload = {
            "message": mensaje,
            "content": base64.b64encode(contenido.encode("utf-8")).decode("ascii"),
            "committer": {"name": "Agente Bestial", "email": "agente@salsasbestial.com"},
        }
        if sha:
            payload["sha"] = sha
        _req.put(api_url, headers=headers, json=payload, timeout=15)
    except Exception as e:
        logger.warning("No se pudo subir %s a GitHub: %s", repo_path, e)


def _commit_biblioteca(nombre_archivo: str = ""):
    """Actualiza biblioteca.json en GitHub via REST API — sin git commands."""
    import base64, os
    import requests as _req
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return  # Local: no es necesario
    try:
        api_url = "https://api.github.com/repos/cgomeznavarrete/agente-instagram-bestial/contents/datos/biblioteca.json"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # Obtener SHA actual del archivo
        r_get = _req.get(api_url, headers=headers, timeout=15)
        sha = r_get.json().get("sha", "") if r_get.status_code == 200 else ""

        # Contenido actual del JSON
        contenido = Path("datos/biblioteca.json").read_text(encoding="utf-8")
        contenido_b64 = base64.b64encode(contenido.encode("utf-8")).decode("ascii")

        payload = {
            "message": f"chore: biblioteca +{nombre_archivo}" if nombre_archivo else "chore: biblioteca actualizada",
            "content": contenido_b64,
            "committer": {"name": "Agente Bestial", "email": "agente@salsasbestial.com"},
        }
        if sha:
            payload["sha"] = sha

        r_put = _req.put(api_url, headers=headers, json=payload, timeout=15)
        if r_put.status_code in (200, 201):
            logger.info("biblioteca.json actualizado en GitHub via API: %s", nombre_archivo)
        else:
            logger.warning("GitHub API error %s: %s", r_put.status_code, r_put.text[:200])
    except Exception as e:
        logger.warning("No se pudo actualizar biblioteca.json via API: %s", e)


def _descargar_archivo(file_id: str, extension: str, tipo: str = "media") -> Optional[Path]:
    """Descarga un archivo de Telegram con nombre limpio (sin UUIDs).

    Límite Telegram Bot API: 20MB. Si el archivo es mayor, retorna None
    y envía un mensaje explicativo al chat.
    """
    try:
        r = requests.get(f"{BASE_URL}/getFile", params={"file_id": file_id}, timeout=15)
        data = r.json()

        # Telegram retorna ok=False cuando el archivo supera 20MB
        if not data.get("ok"):
            desc = data.get("description", "")
            logger.warning("getFile falló: %s", desc)
            if "file is too big" in desc.lower() or "too large" in desc.lower():
                _enviar_mensaje(
                    "⚠️ <b>Archivo demasiado grande</b>\n\n"
                    "Telegram limita la descarga de archivos a <b>20MB</b> por bot.\n\n"
                    "Opciones:\n"
                    "• Comprime el video antes de enviarlo\n"
                    "• Recórtalo en clips más cortos\n"
                    "• Envía la foto/video desde la app de Telegram (no como archivo)"
                )
            else:
                _enviar_mensaje(f"❌ No se pudo obtener el archivo de Telegram: {desc}")
            return None

        file_path = data["result"]["file_path"]
        # Verificar tamaño si viene en la respuesta
        file_size = data["result"].get("file_size", 0)
        if file_size and file_size > 20 * 1024 * 1024:
            _enviar_mensaje(
                f"⚠️ <b>Archivo demasiado grande</b> ({file_size // (1024*1024)}MB)\n\n"
                "El límite de Telegram Bot API es <b>20MB</b>.\n"
                "Comprime el video o recórtalo en clips más cortos."
            )
            return None

        url = f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}"
        contenido = requests.get(url, timeout=120).content
        from datetime import datetime
        nombre = f"salsas_bestial_{tipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{extension}"
        ruta = Path(tempfile.gettempdir()) / nombre
        ruta.write_bytes(contenido)
        logger.info("Archivo descargado: %s (%.1fMB)", nombre, len(contenido) / (1024*1024))
        return ruta
    except Exception as e:
        logger.error("Error descargando archivo Telegram: %s", e)
        return None


def _generar_caption(tipo: str, pilar: str) -> str:
    cliente = ClienteClaude()
    caption_raw = cliente.generar(
        prompt_sistema=(
            "Eres el community manager de Salsas Bestial, marca colombiana de salsas picantes. "
            "Haz que la persona se identifique con la experiencia del picante. "
            "Tono: cercano, real, apasionado. Sin frases publicitarias genéricas."
        ),
        prompt_usuario=(
            f"Tipo de publicación: {tipo.upper()}. Pilar: {pilar}.\n\n"
            "Escribe un caption para Instagram:\n"
            "- Primera línea: verdad que los amantes del picante reconocen al instante\n"
            "- Cuerpo (2-3 líneas): la experiencia — olor, sabor, el momento\n"
            f"- CTA de compra: Pídela aquí → {brand.LINK_COMPRA_WHATSAPP}\n"
            f"- Pregunta de cierre (OBLIGATORIA, genera conversación): elige la más apropiada de esta lista y ponla como última línea antes de los hashtags: {brand.PREGUNTAS_ENGAGEMENT}\n"
            f"- Incluye exactamente estos hashtags al final (no inventes otros): {' '.join(brand.seleccionar_hashtags())}\n"
            "- Máximo 3 emojis"
        ),
        temperatura=0.85,
        max_tokens=600,
    )
    from agente.claude.cliente_claude import limpiar_caption
    return limpiar_caption(re.sub(r"\*\*(.+?)\*\*", r"\1", caption_raw))


def _publicar_ahora_imagen(ruta: Path, caption: str) -> Optional[str]:
    """Sube imagen a Cloudinary y publica en Instagram. Retorna media_id o None."""
    subidor = SubidorCloudinary()
    url = subidor.subir(ruta)
    if not url:
        return None
    r = requests.post(
        f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
        data={"image_url": url, "caption": caption, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
        timeout=60,
    )
    if r.status_code != 200:
        logger.error("Error container IG: %s", r.json())
        return None
    creation_id = r.json()["id"]
    r2 = requests.post(
        f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
        timeout=60,
    )
    return r2.json().get("id") if r2.status_code == 200 else None


def _publicar_ahora_story_imagen(ruta: Path) -> Optional[str]:
    subidor = SubidorCloudinary()
    url = subidor.subir(ruta)
    if not url:
        return None
    r = requests.post(
        f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
        data={"image_url": url, "media_type": "STORIES", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
        timeout=60,
    )
    if r.status_code != 200:
        return None
    creation_id = r.json()["id"]
    r2 = requests.post(
        f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
        timeout=60,
    )
    return r2.json().get("id") if r2.status_code == 200 else None


# ── Manejadores de mensajes ───────────────────────────────────────────────────

class BotTelegram:
    """Bot de Telegram con polling largo. Ejecutar con python main.py bot."""

    def __init__(self):
        self.offset: Optional[int] = None
        self._estado_path = Path("datos/bot_estado.json")
        self._pausas_path = Path("datos/pausas_hoy.json")
        self._pending_pubs: dict = {}  # rev_id -> item

    def _leer_pausas_hoy(self) -> dict:
        try:
            if self._pausas_path.exists():
                return json.loads(self._pausas_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _guardar_pausas_hoy(self, pausas: dict):
        self._pausas_path.parent.mkdir(parents=True, exist_ok=True)
        self._pausas_path.write_text(json.dumps(pausas, ensure_ascii=False, indent=2), encoding="utf-8")
        _commit_json_github(str(self._pausas_path), "datos/pausas_hoy.json", "chore: pausas publicacion actualizadas")

    def _set_estado(self, chat_id: str, paso: str, datos: dict = None):
        estado = self._leer_estado_disco()
        estado[chat_id] = {"paso": paso, "datos": datos or {}, "ts": time.time()}
        self._escribir_estado_disco(estado)

    def _get_estado(self, chat_id: str) -> dict:
        estado = self._leer_estado_disco()
        entrada = estado.get(chat_id, {"paso": "idle", "datos": {}})
        # Expirar estado con más de 2 horas de antigüedad
        if time.time() - entrada.get("ts", 0) > 7200:
            return {"paso": "idle", "datos": {}}
        return entrada

    def _clear_estado(self, chat_id: str):
        estado = self._leer_estado_disco()
        estado.pop(chat_id, None)
        self._escribir_estado_disco(estado)

    def _leer_estado_disco(self) -> dict:
        try:
            if self._estado_path.exists():
                return json.loads(self._estado_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _escribir_estado_disco(self, estado: dict):
        try:
            self._estado_path.parent.mkdir(parents=True, exist_ok=True)
            self._estado_path.write_text(
                json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("No se pudo guardar estado en disco: %s", e)

    def ejecutar(self):
        """Loop principal de polling."""
        logger.info("Bot Telegram iniciado — escuchando mensajes...")
        _enviar_mensaje(
            "🤖 <b>Agente Salsas Bestial activo</b>\n\n"
            "Mándame una foto o video y te digo qué hacer con él.\n\n"
            "Comandos:\n"
            "/carrusel <tema> — genera carrusel educativo\n"
            "/estado — ver material en biblioteca\n"
            "/ayuda — ver todos los comandos"
        )

        while True:
            updates = _get_updates(self.offset, timeout=20)
            for update in updates:
                self.offset = update["update_id"] + 1
                logger.info("Update recibido: id=%s tipos=%s", update["update_id"], list(update.keys()))
                try:
                    self._procesar_update(update)
                except Exception as e:
                    logger.error("Error procesando update %s: %s", update["update_id"], e, exc_info=True)

            # Procesar álbumes completos (media groups cuyo último mensaje llegó hace >2s)
            self._procesar_albumes_pendientes()

    def _procesar_update(self, update: dict):
        if "callback_query" in update:
            self._manejar_callback(update["callback_query"])
        elif "message" in update:
            self._manejar_mensaje(update["message"])

    def _manejar_mensaje(self, msg: dict):
        chat_id = str(msg.get("chat", {}).get("id", ""))
        logger.info("Mensaje recibido | chat_id=%s | match=%s | keys=%s",
                    chat_id,
                    chat_id == str(settings.TELEGRAM_CHAT_ID),
                    list(msg.keys()))
        if chat_id != str(settings.TELEGRAM_CHAT_ID):
            logger.warning("Ignorando mensaje de chat_id=%s (no autorizado)", chat_id)
            return  # Solo responder al chat autorizado

        texto = msg.get("text", "").strip()
        foto = msg.get("photo")
        video = msg.get("video")
        documento = msg.get("document")
        media_group_id = msg.get("media_group_id")  # álbum de varias fotos

        # ── Comandos de texto ─────────────────────────────────────────────
        if texto.startswith("/carrusel"):
            tema = texto.replace("/carrusel", "").strip()
            if not tema:
                _enviar_mensaje("Escribe el tema: <code>/carrusel curiosidades del picante</code>")
                return
            self._flujo_carrusel(tema, chat_id)
            return

        if texto.startswith("/estado"):
            self._mostrar_estado()
            return

        if texto.startswith("/hoy"):
            self._mostrar_plan_hoy()
            return

        if texto.startswith("/venta"):
            self._flujo_venta()
            return

        if texto.startswith("/publicar"):
            # /publicar          → publica el siguiente item pendiente (cualquier tipo)
            # /publicar reel     → fuerza tipo reel
            # /publicar post     → fuerza tipo post
            # /publicar story    → fuerza tipo story
            partes_pub = texto.split()
            tipo_forzado = partes_pub[1].lower() if len(partes_pub) > 1 else None
            self._flujo_publicar_ahora(tipo_forzado)
            return

        if texto.startswith("/ayuda") or texto.startswith("/start"):
            self._mostrar_ayuda()
            return

        # ── Foto recibida ─────────────────────────────────────────────────
        if foto:
            logger.info("Foto recibida, procesando...")
            file_id = foto[-1]["file_id"]  # La de mayor resolución
            self._recibir_media(file_id, ".jpg", "imagen", chat_id, media_group_id)
            return

        # ── Video recibido ────────────────────────────────────────────────
        if video:
            logger.info("Video recibido, procesando...")
            file_id = video["file_id"]
            self._recibir_media(file_id, ".mp4", "video", chat_id, media_group_id)
            return

        # ── Documento recibido (foto enviada como archivo) ────────────────
        if documento:
            mime = documento.get("mime_type", "")
            logger.info("Documento recibido, mime_type=%s", mime)
            if mime.startswith("image/"):
                ext = ".jpg" if "jpeg" in mime else ".png" if "png" in mime else ".jpg"
                self._recibir_media(documento["file_id"], ext, "imagen", chat_id, media_group_id)
            elif mime.startswith("video/"):
                self._recibir_media(documento["file_id"], ".mp4", "video", chat_id, media_group_id)
            else:
                _enviar_mensaje(
                    f"Recibí un archivo ({mime}), pero solo proceso imágenes y videos.\n"
                    "Envíame una foto directamente desde la galería."
                )
            return

        # ── Contexto: esperando pilar ─────────────────────────────────────
        estado = self._get_estado(chat_id)
        if estado["paso"] == "esperando_pilar_texto" and texto:
            pilar = estado["datos"].get("pilar", "lifestyle_y_comunidad")
            self._continuar_flujo_con_pilar(chat_id, pilar)
            return

        # ── Mensaje no reconocido ─────────────────────────────────────────
        if not texto:
            logger.info("Mensaje sin contenido reconocido: %s", list(msg.keys()))
            _enviar_mensaje(
                "Recibí tu mensaje pero no lo pude procesar.\n\n"
                "Envíame una <b>foto</b> desde tu galería directamente.\n"
                "O escribe /ayuda para ver los comandos disponibles."
            )

    def _recibir_media(self, file_id: str, extension: str, tipo_media: str, chat_id: str, media_group_id: str = None):
        """Recibe un archivo y pregunta qué hacer con él.
        Si viene en un álbum (media_group_id), acumula hasta que lleguen todos.
        """
        if media_group_id:
            # Acumular en el estado del álbum — preguntar cuando lleguen todos
            estado = self._leer_estado_disco()
            clave_album = f"album_{media_group_id}"
            album = estado.get(clave_album, {
                "chat_id": chat_id,
                "archivos": [],
                "ts_ultimo": 0,
            })
            album["archivos"].append({"file_id": file_id, "extension": extension})
            album["ts_ultimo"] = time.time()
            estado[clave_album] = album
            self._escribir_estado_disco(estado)
            logger.info("Álbum %s: %d foto(s) acumuladas", media_group_id, len(album["archivos"]))
            return

        # Archivo individual — preguntar inmediatamente
        self._set_estado(chat_id, "recibido", {
            "file_id": file_id,
            "extension": extension,
            "tipo_media": tipo_media,
        })

        emoji = "📸" if tipo_media == "imagen" else "🎬"

        resultado = _enviar_mensaje(
            f"{emoji} <b>Archivo recibido</b>\n\n¿Qué hago con este {tipo_media}?",
            reply_markup={"inline_keyboard": [
                [
                    {"text": "📚 Guardar en biblioteca", "callback_data": "accion:biblioteca"},
                    {"text": "🚀 Publicar ahora",        "callback_data": "accion:ahora"},
                ],
                [
                    {"text": "❌ Cancelar",              "callback_data": "accion:cancelar"},
                ],
            ]}
        )
        if not resultado.get("ok"):
            logger.error("Error enviando opciones de media: %s", resultado)

    def _procesar_albumes_pendientes(self):
        """Procesa álbumes cuyo último mensaje llegó hace >2 segundos (álbum completo)."""
        estado = self._leer_estado_disco()
        ahora = time.time()
        claves_album = [k for k in estado if k.startswith("album_")]
        modificado = False

        for clave in claves_album:
            album = estado[clave]
            if ahora - album.get("ts_ultimo", ahora) < 2.0:
                continue  # Todavía puede llegar más fotos

            chat_id = album["chat_id"]
            archivos = album["archivos"]
            del estado[clave]
            modificado = True

            if not archivos:
                continue

            n = len(archivos)
            logger.info("Álbum completo: %d fotos para chat %s", n, chat_id)

            if n == 1:
                # Solo llegó una — tratar como foto individual
                a = archivos[0]
                estado[chat_id] = {
                    "paso": "recibido",
                    "datos": {"file_id": a["file_id"], "extension": a["extension"], "tipo_media": "imagen"},
                    "ts": ahora,
                }
                _enviar_mensaje(
                    "📸 <b>Foto recibida</b>\n\n¿Qué hago con esta imagen?",
                    reply_markup={"inline_keyboard": [
                        [
                            {"text": "📚 Guardar en biblioteca", "callback_data": "accion:biblioteca"},
                            {"text": "🚀 Publicar ahora",        "callback_data": "accion:ahora"},
                        ],
                        [{"text": "❌ Cancelar", "callback_data": "accion:cancelar"}],
                    ]}
                )
            else:
                # Múltiples fotos — ofrecer como carrusel
                estado[chat_id] = {
                    "paso": "recibido_album",
                    "datos": {"archivos": archivos},
                    "ts": ahora,
                }
                _enviar_mensaje(
                    f"📖 <b>{n} fotos recibidas</b>\n\n¿Las publico como carrusel?",
                    reply_markup={"inline_keyboard": [
                        [
                            {"text": "📚 Guardar carrusel en biblioteca", "callback_data": "album:biblioteca"},
                            {"text": "🚀 Publicar carrusel ahora",        "callback_data": "album:ahora"},
                        ],
                        [{"text": "❌ Cancelar", "callback_data": "album:cancelar"}],
                    ]}
                )

        if modificado:
            self._escribir_estado_disco(estado)

    def _manejar_callback(self, cb: dict):
        chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
        data = cb.get("data", "")
        cb_id = cb["id"]

        if not data:
            return

        partes = data.split(":")

        # ── Acción principal: biblioteca o ahora ──────────────────────────
        if partes[0] == "accion" and len(partes) >= 2:
            destino = partes[1]

            # ── Cancelar ──────────────────────────────────────────────────
            if destino == "cancelar":
                _answer_callback(cb_id, "❌ Cancelado")
                self._clear_estado(chat_id)
                _enviar_mensaje("❌ <b>Cancelado.</b>\n\nEl archivo fue descartado. Mándame otro cuando quieras.")
                return

            _answer_callback(cb_id, "📥 Recibido")

            # Recuperar file_id y tipo del estado (guardado cuando llegó la foto)
            estado = self._get_estado(chat_id)
            datos = estado.get("datos", {})
            tipo_media = datos.get("tipo_media", "imagen")

            # Actualizar estado con destino
            self._set_estado(chat_id, "recibido", {**datos, "destino": destino})

            # Preguntar tipo de contenido
            es_video = tipo_media == "video"
            if es_video:
                botones = [
                    [
                        {"text": "🎬 Reel",    "callback_data": "tipo:reel"},
                        {"text": "⭕ Story",   "callback_data": "tipo:story"},
                    ],
                    [{"text": "❌ Cancelar",   "callback_data": "tipo:cancelar"}],
                ]
            else:
                botones = [
                    [
                        {"text": "📸 Post",    "callback_data": "tipo:post"},
                        {"text": "⭕ Story",   "callback_data": "tipo:story"},
                    ],
                    [{"text": "❌ Cancelar",   "callback_data": "tipo:cancelar"}],
                ]

            _enviar_mensaje("¿Qué tipo de publicación es?", reply_markup={"inline_keyboard": botones})
            return

        # ── Tipo seleccionado ─────────────────────────────────────────────
        if partes[0] == "tipo" and len(partes) >= 2:
            tipo_pub = partes[1]

            # ── Cancelar ──────────────────────────────────────────────────
            if tipo_pub == "cancelar":
                _answer_callback(cb_id, "❌ Cancelado")
                self._clear_estado(chat_id)
                _enviar_mensaje("❌ <b>Cancelado.</b>\n\nEl archivo fue descartado. Mándame otro cuando quieras.")
                return

            estado = self._get_estado(chat_id)
            datos = estado.get("datos", {})
            destino = datos.get("destino", "biblioteca")

            _answer_callback(cb_id, f"{'📚' if destino == 'biblioteca' else '🚀'} {tipo_pub.upper()}")
            self._set_estado(chat_id, "recibido", {**datos, "tipo_pub": tipo_pub})

            # Preguntar pilar (solo para posts y reels)
            if tipo_pub in ("post", "reel"):
                botones_pilar = [
                    [{"text": "🌶 Recetas y maridajes", "callback_data": "pilar:recetas_y_maridajes"}],
                    [{"text": "🌅 Lifestyle",            "callback_data": "pilar:lifestyle_y_comunidad"}],
                    [{"text": "😄 Humor picante",        "callback_data": "pilar:humor_picante"}],
                    [{"text": "📚 Educación",            "callback_data": "pilar:educacion_sobre_salsas"}],
                    [{"text": "🎬 Behind the scenes",    "callback_data": "pilar:behind_the_scenes"}],
                    [{"text": "❌ Cancelar",             "callback_data": "pilar:cancelar"}],
                ]
                _enviar_mensaje("¿Cuál es el pilar de contenido?", reply_markup={"inline_keyboard": botones_pilar})
            else:
                # Story → no necesita pilar ni caption
                file_id    = datos.get("file_id", "")
                extension  = datos.get("extension", ".jpg")
                self._ejecutar_con_pilar(file_id, extension, tipo_pub, destino, "lifestyle_y_comunidad", chat_id)
            return

        # ── Pilar seleccionado ────────────────────────────────────────────
        if partes[0] == "pilar" and len(partes) >= 2:
            pilar = partes[1]

            # ── Cancelar ──────────────────────────────────────────────────
            if pilar == "cancelar":
                _answer_callback(cb_id, "❌ Cancelado")
                self._clear_estado(chat_id)
                _enviar_mensaje("❌ <b>Cancelado.</b>\n\nEl archivo fue descartado. Mándame otro cuando quieras.")
                return

            estado = self._get_estado(chat_id)
            datos  = estado.get("datos", {})
            file_id   = datos.get("file_id", "")
            extension = datos.get("extension", ".jpg")
            tipo_pub  = datos.get("tipo_pub", "post")
            destino   = datos.get("destino", "biblioteca")

            _answer_callback(cb_id, "✍️ Procesando...")
            self._ejecutar_con_pilar(file_id, extension, tipo_pub, destino, pilar, chat_id)
            return

        # ── Aprobar/rechazar publicación inmediata ────────────────────────
        if partes[0] == "pub" and len(partes) >= 3:
            accion, rev_id = partes[1], partes[2]
            estado = self._get_estado(chat_id)

            if estado["paso"] != "esperando_aprobacion" or estado["datos"].get("rev_id") != rev_id:
                _answer_callback(cb_id, "⚠️ Acción no válida")
                return

            if accion == "aprobar":
                _answer_callback(cb_id, "✅ Publicando...")
                datos = estado["datos"]
                self._publicar_aprobado(datos, chat_id)
            else:
                _answer_callback(cb_id, "❌ Descartado")
                _enviar_mensaje(
                    "❌ Descartado.\n\nEscribe qué cambiar en el caption (o <b>saltar</b> para ignorar)."
                )
                self._set_estado(chat_id, "esperando_ajuste", estado["datos"])
            return

        # ── Aprobar guardar en biblioteca (flujo legado / mensajes viejos) ──
        if partes[0] == "guardar" and len(partes) >= 2:
            accion = partes[1]
            _answer_callback(cb_id, "📚 Guardando..." if accion == "si" else "🗑 Descartado")
            estado = self._get_estado(chat_id)
            datos = estado.get("datos", {})
            ruta_str = datos.get("ruta_tmp", "")
            if accion == "si" and ruta_str:
                ruta_tmp = Path(ruta_str)
                tipo_pub = datos.get("tipo_pub", "post")
                pilar = datos.get("pilar", "lifestyle_y_comunidad")
                try:
                    item = agregar_item(ruta_tmp, tipo_pub, pilar)
                    ruta_tmp.unlink(missing_ok=True)
                    conteo = contar_pendientes()
                    _enviar_mensaje(
                        f"📚 <b>Guardado en biblioteca</b>\n"
                        f"Cola: {conteo['post']} posts · {conteo['reel']} reels · {conteo['story']} stories"
                    )
                except Exception as e:
                    logger.error("Error guardando: %s", e)
                    _enviar_mensaje("❌ Error guardando.")
            elif accion != "si":
                if ruta_str:
                    Path(ruta_str).unlink(missing_ok=True)
                _enviar_mensaje("🗑 Descartado.")
            self._clear_estado(chat_id)
            return

        # ── Control de publicaciones del día (/hoy) ──────────────────────
        if partes[0] == "hoy" and len(partes) >= 2:
            import datetime
            from zoneinfo import ZoneInfo
            accion = partes[1]
            fecha_hoy = datetime.datetime.now(ZoneInfo("America/Bogota")).strftime("%Y-%m-%d")
            pausas = self._leer_pausas_hoy()
            if pausas.get("fecha") != fecha_hoy:
                pausas = {"fecha": fecha_hoy, "slots_pausados": [], "pausado_todo": False}

            if accion == "pausar_todo":
                pausas["pausado_todo"] = True
                pausas["slots_pausados"] = []
                self._guardar_pausas_hoy(pausas)
                _answer_callback(cb_id, "🚫 Publicaciones pausadas para hoy")
                _enviar_mensaje("🚫 <b>No se publica nada hoy.</b>\nEscribe /hoy para reactivar cuando quieras.")

            elif accion == "activar_todo":
                pausas["pausado_todo"] = False
                pausas["slots_pausados"] = []
                self._guardar_pausas_hoy(pausas)
                _answer_callback(cb_id, "✅ Publicaciones reactivadas")
                _enviar_mensaje("✅ <b>Publicaciones reactivadas.</b>\nEscribe /hoy para ver el plan.")

            elif accion == "saltar" and len(partes) >= 3:
                h_min = int(partes[2])
                hora_label = "12pm" if h_min < 15 else "7pm"
                if h_min not in pausas["slots_pausados"]:
                    pausas["slots_pausados"].append(h_min)
                self._guardar_pausas_hoy(pausas)
                _answer_callback(cb_id, f"⏭ Slot {hora_label} saltado")
                _enviar_mensaje(f"⏭ Slot de <b>{hora_label}</b> no se publicará hoy.\nEscribe /hoy para ver el plan actualizado.")

            elif accion == "activar" and len(partes) >= 3:
                h_min = int(partes[2])
                hora_label = "12pm" if h_min < 15 else "7pm"
                pausas["slots_pausados"] = [s for s in pausas["slots_pausados"] if s != h_min]
                self._guardar_pausas_hoy(pausas)
                _answer_callback(cb_id, f"✅ Slot {hora_label} reactivado")
                _enviar_mensaje(f"✅ Slot de <b>{hora_label}</b> reactivado.\nEscribe /hoy para ver el plan actualizado.")
            return

        # ── Álbum de fotos del usuario → carrusel ────────────────────────
        if partes[0] == "album" and len(partes) >= 2:
            accion = partes[1]
            estado = self._get_estado(chat_id)
            archivos = estado.get("datos", {}).get("archivos", [])

            if accion == "cancelar":
                _answer_callback(cb_id, "❌ Cancelado")
                self._clear_estado(chat_id)
                _enviar_mensaje("❌ Cancelado.")
                return

            if not archivos:
                _answer_callback(cb_id, "⚠️ Sin archivos")
                self._clear_estado(chat_id)
                return

            _answer_callback(cb_id, "⬇️ Descargando fotos...")
            _enviar_mensaje(f"⬇️ Descargando {len(archivos)} fotos...")

            rutas = []
            for a in archivos:
                ruta = _descargar_archivo(a["file_id"], a["extension"], tipo="post")
                if ruta:
                    rutas.append(ruta)

            if not rutas:
                _enviar_mensaje("❌ Error descargando las fotos.")
                self._clear_estado(chat_id)
                return

            if accion == "biblioteca":
                item = agregar_carrusel(rutas, tipo="post", pilar="lifestyle_y_comunidad")
                _commit_biblioteca(item.id)
                conteo = contar_pendientes()
                _enviar_mensaje(
                    f"📚 <b>Carrusel guardado en biblioteca</b>\n\n"
                    f"{len(rutas)} fotos — Cola posts: {conteo['post']}"
                )
            elif accion == "ahora":
                _enviar_mensaje("✍️ Generando caption con Claude...")
                from agente.claude.cliente_claude import ClienteClaude
                from config import brand_guidelines as brand
                import re as _re
                cliente = ClienteClaude()
                caption_raw = cliente.generar(
                    prompt_sistema="Eres el community manager de Salsas Bestial.",
                    prompt_usuario=(
                        f"Carrusel de {len(rutas)} fotos. Pilar: lifestyle_y_comunidad.\n"
                        f"Caption para Instagram — hook directo, 2 líneas, "
                        f"CTA: Pídela aquí → {brand.LINK_COMPRA_WHATSAPP}, "
                        f"pregunta de engagement al final (elige de: {brand.PREGUNTAS_ENGAGEMENT[:3]}), "
                        f"hashtags: {' '.join(brand.seleccionar_hashtags())}"
                    ),
                    temperatura=0.8, max_tokens=450,
                )
                from agente.claude.cliente_claude import limpiar_caption
                caption = limpiar_caption(_re.sub(r"\*\*(.+?)\*\*", r"\1", caption_raw))
                self._publicar_carrusel_ig(rutas, caption, chat_id)

            self._clear_estado(chat_id)
            return

        # ── Carrusel: publicar ahora o biblioteca ─────────────────────────
        if partes[0] == "carrusel" and len(partes) >= 2:
            accion = partes[1]
            estado = self._get_estado(chat_id)
            datos = estado["datos"]
            rutas = [Path(r) for r in datos.get("rutas_slides", [])]
            caption = datos.get("caption", "")

            if accion == "ahora":
                _answer_callback(cb_id, "🚀 Publicando carrusel...")
                self._publicar_carrusel_ig(rutas, caption, chat_id)
            elif accion == "biblioteca":
                _answer_callback(cb_id, "📚 Guardando...")
                item = agregar_carrusel(rutas, tipo="post", pilar=datos.get("pilar", "educacion_sobre_salsas"))
                conteo = contar_pendientes()
                _enviar_mensaje(
                    f"📚 <b>Carrusel guardado en biblioteca</b>\n"
                    f"{len(rutas)} slides — Cola posts: {conteo['post']}"
                )
            else:
                _answer_callback(cb_id, "🗑 Descartado")
                _enviar_mensaje("🗑 Carrusel descartado.")
            self._clear_estado(chat_id)
            return

        # ── Aprobación de publicación vía /publicar ───────────────────────
        if partes[0] == "pub_aprobar" and len(partes) >= 2:
            rev_id = partes[1]
            item = self._pending_pubs.pop(rev_id, None)
            if not item:
                _answer_callback(cb_id, "⚠️ Expirado o ya procesado")
                return
            _answer_callback(cb_id, "✅ Publicando...")
            _enviar_mensaje(f"⏳ Publicando {item.tipo.upper()}...")
            import threading
            threading.Thread(
                target=self._publicar_en_hilo,
                args=(item,),
                daemon=True,
            ).start()
            return

        if partes[0] == "pub_rechazar" and len(partes) >= 2:
            rev_id = partes[1]
            self._pending_pubs.pop(rev_id, None)
            _answer_callback(cb_id, "⏭ Saltado")
            _enviar_mensaje("⏭ <b>Publicación cancelada.</b>")
            return

    def _ejecutar_con_pilar(self, file_id: str, extension: str, tipo_pub: str, destino: str, pilar: str, chat_id: str):
        """Descarga el archivo y ejecuta el flujo según destino (biblioteca o ahora)."""
        _enviar_mensaje("⬇️ Descargando archivo...")
        ruta_tmp = _descargar_archivo(file_id, extension, tipo=tipo_pub)
        if not ruta_tmp:
            _enviar_mensaje("❌ Error al descargar el archivo. Intenta de nuevo.")
            self._clear_estado(chat_id)
            return

        if destino == "biblioteca":
            # Guardar directo sin pedir confirmación extra — el caption se genera al publicar
            try:
                item = agregar_item(ruta_tmp, tipo_pub, pilar)
                ruta_tmp.unlink(missing_ok=True)
                conteo = contar_pendientes()
                # Commit inmediato a GitHub para que publicar-programado pueda verlo
                _commit_biblioteca(item.nombre_archivo)
                _enviar_mensaje(
                    f"📚 <b>Guardado en biblioteca</b>\n\n"
                    f"Tipo: {tipo_pub.upper()} | Pilar: {pilar.replace('_', ' ').title()}\n\n"
                    f"Cola: {conteo['post']} posts · {conteo['reel']} reels · {conteo['story']} stories\n\n"
                    f"El caption se genera automaticamente cuando se publique."
                )
            except Exception as e:
                logger.error("Error guardando en biblioteca: %s", e, exc_info=True)
                _enviar_mensaje("❌ Error guardando en biblioteca. Intenta de nuevo.")
            self._clear_estado(chat_id)
            return

        else:  # publicar ahora
            _enviar_mensaje("✍️ Generando caption con Claude...")
            caption = _generar_caption(tipo_pub, pilar) if tipo_pub in ("post", "reel") else ""

            rev_id = f"rev_{int(time.time())}"
            self._set_estado(chat_id, "esperando_aprobacion", {
                "ruta_tmp": str(ruta_tmp),
                "tipo_pub": tipo_pub,
                "pilar": pilar,
                "caption": caption,
                "rev_id": rev_id,
                "extension": extension,
            })

            texto_rev = (
                f"🚀 <b>{tipo_pub.upper()} — ¿Publicar ahora?</b>\n\n"
                + (f"{caption[:700]}" if caption else "Story — sin caption")
                + "\n\n<i>¿Publicar en Instagram?</i>"
            )
            botones_rev = {"inline_keyboard": [[
                {"text": "✅ Publicar", "callback_data": f"pub:aprobar:{rev_id}"},
                {"text": "❌ Rechazar", "callback_data": f"pub:rechazar:{rev_id}"},
            ]]}

            if extension in (".jpg", ".jpeg", ".png", ".webp"):
                _enviar_foto(ruta_tmp, caption=texto_rev, reply_markup=botones_rev)
            else:
                _enviar_mensaje(texto_rev, reply_markup=botones_rev)

    def _publicar_aprobado(self, datos: dict, chat_id: str):
        ruta = Path(datos["ruta_tmp"])
        tipo_pub = datos["tipo_pub"]
        caption = datos["caption"]
        extension = datos.get("extension", ".jpg")
        es_video = extension in (".mp4", ".mov", ".avi", ".m4v")

        _enviar_mensaje("📤 Subiendo a Cloudinary y publicando en Instagram...")

        media_id = None
        if tipo_pub == "post" and not es_video:
            media_id = _publicar_ahora_imagen(ruta, caption)
        elif tipo_pub == "story" and not es_video:
            media_id = _publicar_ahora_story_imagen(ruta)
        elif tipo_pub == "reel" and es_video:
            from agente.instagram.publicador import Publicador
            # Usar el publicador existente para reels
            subidor = SubidorCloudinary()
            url = subidor.subir(ruta, resource_type="video")
            if url:
                media_id = self._publicar_reel_ig(url, caption)
        elif tipo_pub == "story" and es_video:
            subidor = SubidorCloudinary()
            url = subidor.subir(ruta, resource_type="video")
            if url:
                media_id = self._publicar_story_video_ig(url)

        ruta.unlink(missing_ok=True)
        self._clear_estado(chat_id)

        if media_id:
            _enviar_mensaje(
                f"{'📸' if tipo_pub == 'post' else '🎬' if tipo_pub == 'reel' else '⭕'} "
                f"<b>{tipo_pub.upper()} publicado en Instagram</b>\n"
                f"<a href='https://www.instagram.com/salsas.bestial/'>Ver en @salsas.bestial →</a>"
            )
        else:
            _enviar_mensaje("❌ Error al publicar. Revisa los logs.")

    def _publicar_reel_ig(self, url_video: str, caption: str) -> Optional[str]:
        r = requests.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
            data={
                "video_url": url_video,
                "media_type": "REELS",
                "caption": caption,
                "share_to_feed": "true",
                "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
            }, timeout=120,
        )
        if r.status_code != 200:
            return None
        creation_id = r.json()["id"]
        for _ in range(18):
            time.sleep(10)
            st = requests.get(
                f"https://graph.facebook.com/v21.0/{creation_id}",
                params={"fields": "status_code", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=30,
            ).json().get("status_code", "")
            if st == "FINISHED":
                break
            if st == "ERROR":
                return None
        r2 = requests.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
            data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
            timeout=60,
        )
        return r2.json().get("id") if r2.status_code == 200 else None

    def _publicar_story_video_ig(self, url_video: str) -> Optional[str]:
        r = requests.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
            data={
                "video_url": url_video,
                "media_type": "STORIES",
                "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
            }, timeout=120,
        )
        if r.status_code != 200:
            return None
        creation_id = r.json()["id"]
        for _ in range(18):
            time.sleep(10)
            st = requests.get(
                f"https://graph.facebook.com/v21.0/{creation_id}",
                params={"fields": "status_code", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=30,
            ).json().get("status_code", "")
            if st in ("FINISHED",):
                break
        r2 = requests.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
            data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
            timeout=60,
        )
        return r2.json().get("id") if r2.status_code == 200 else None

    def _publicar_carrusel_ig(self, rutas: list[Path], caption: str, chat_id: str):
        """Publica un carrusel de imágenes en Instagram."""
        subidor = SubidorCloudinary()
        _enviar_mensaje(f"📤 Subiendo {len(rutas)} slides a Cloudinary...")
        creation_ids = []
        for ruta in rutas:
            url = subidor.subir(ruta)
            if not url:
                _enviar_mensaje(f"❌ Error subiendo slide {ruta.name}")
                return
            r = requests.post(
                f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
                data={"image_url": url, "is_carousel_item": "true", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=60,
            )
            if r.status_code != 200:
                _enviar_mensaje(f"❌ Error creando container slide: {r.json()}")
                return
            creation_ids.append(r.json()["id"])

        r_car = requests.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(creation_ids),
                "caption": caption,
                "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
            }, timeout=60,
        )
        if r_car.status_code != 200:
            _enviar_mensaje(f"❌ Error creando carrusel: {r_car.json()}")
            return

        r_pub = requests.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
            data={"creation_id": r_car.json()["id"], "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
            timeout=60,
        )
        if r_pub.status_code == 200:
            _enviar_mensaje(
                f"📖 <b>Carrusel publicado en Instagram</b>\n"
                f"<a href='https://www.instagram.com/salsas.bestial/'>Ver en @salsas.bestial →</a>"
            )
        else:
            _enviar_mensaje(f"❌ Error publicando carrusel: {r_pub.json()}")

    def _flujo_carrusel(self, tema: str, chat_id: str):
        """Genera carrusel HTML→PNG y pregunta qué hacer con él."""
        _enviar_mensaje(f"🎨 Generando carrusel sobre: <b>{tema}</b>\nEsto toma unos segundos...")
        try:
            from agente.generadores.carrusel_html import generar_carrusel_html
            rutas = generar_carrusel_html(tema=tema, n_slides=3)
        except Exception as e:
            logger.error("Error generando carrusel HTML: %s", e)
            _enviar_mensaje(f"❌ Error generando el carrusel: {e}")
            return

        if not rutas:
            _enviar_mensaje("❌ No se pudo generar el carrusel.")
            return

        # Generar caption para el carrusel
        cliente = ClienteClaude()
        caption_raw = cliente.generar(
            prompt_sistema="Eres el community manager de Salsas Bestial.",
            prompt_usuario=(
                f"Escribe un caption corto para un carrusel educativo sobre: {tema}\n"
                f"- Hook directo en primera línea\n"
                f"- 1-2 líneas de cuerpo\n"
                f"- CTA: Pídela aquí → {brand.LINK_COMPRA_WHATSAPP}\n"
                "- 10 hashtags\n- Máximo 2 emojis"
            ),
            temperatura=0.8,
            max_tokens=400,
        )
        from agente.claude.cliente_claude import limpiar_caption
        caption = limpiar_caption(re.sub(r"\*\*(.+?)\*\*", r"\1", caption_raw))

        # Enviar slides a Telegram para preview
        _enviar_mensaje(f"✅ {len(rutas)} slides generados. Enviando preview...")
        for i, ruta in enumerate(rutas, 1):
            _enviar_foto(ruta, caption=f"Slide {i}/{len(rutas)}")
            time.sleep(0.5)

        self._set_estado(chat_id, "esperando_decision_carrusel", {
            "rutas_slides": [str(r) for r in rutas],
            "caption": caption,
            "pilar": "educacion_sobre_salsas",
            "tema": tema,
        })

        _enviar_mensaje(
            f"Caption generado:\n\n{caption[:600]}\n\n¿Qué hacemos con este carrusel?",
            reply_markup={"inline_keyboard": [[
                {"text": "🚀 Publicar ahora", "callback_data": "carrusel:ahora"},
                {"text": "📚 Guardar en biblioteca", "callback_data": "carrusel:biblioteca"},
                {"text": "🗑 Descartar", "callback_data": "carrusel:descartar"},
            ]]}
        )

    def _mostrar_estado(self):
        from datetime import datetime
        conteo = contar_pendientes()

        EMOJI = {"post": "📸", "reel": "🎬", "story": "⭕", "carrusel": "📖"}
        PILAR_CORTO = {
            "recetas_y_maridajes": "Recetas",
            "lifestyle_y_comunidad": "Lifestyle",
            "humor_picante": "Humor",
            "educacion_sobre_salsas": "Educación",
            "behind_the_scenes": "BTS",
            "promociones_y_lanzamientos": "Promo",
            "testimonios_y_ugc": "Testimonios",
            "como_comprar": "Cómo comprar",
        }

        lineas = ["📚 <b>Biblioteca de contenido</b>\n"]

        total = sum(conteo.values())
        if total == 0:
            lineas.append("Vacía — envíame fotos o videos para cargar material.")
        else:
            for tipo in ["post", "reel", "story", "carrusel"]:
                items = listar_pendientes(tipo)
                if not items:
                    continue
                lineas.append(f"{EMOJI[tipo]} <b>{tipo.upper()} ({len(items)})</b>")
                for i, it in enumerate(items, 1):
                    v = vars(it)
                    pilar = PILAR_CORTO.get(v.get("pilar", ""), v.get("pilar", ""))
                    fecha = datetime.fromtimestamp(v.get("fecha_agregado", 0)).strftime("%d/%m %H:%M")
                    tiene_url = "✅" if v.get("cloudinary_url") else "📁"
                    nombre = v.get("nombre_archivo", "")[-20:]  # últimos 20 chars
                    lineas.append(f"  {i}. {tiene_url} {pilar} — {fecha} — <code>{nombre}</code>")
                lineas.append("")

        lineas.append(f"<b>Total:</b> {conteo['post']} posts · {conteo['reel']} reels · {conteo['story']} stories · {conteo['carrusel']} carruseles")
        _enviar_mensaje("\n".join(lineas))

        # Enviar preview visual de cada item
        time.sleep(0.5)
        for tipo in ["post", "reel", "story", "carrusel"]:
            for it in listar_pendientes(tipo):
                v = vars(it)
                url = v.get("cloudinary_url", "")
                nombre = v.get("nombre_archivo", "sin nombre")
                pilar = PILAR_CORTO.get(v.get("pilar", ""), v.get("pilar", ""))
                caption_prev = f"{EMOJI[tipo]} {tipo.upper()} — {pilar}\n<code>{nombre}</code>"

                # Para carruseles usar la primera URL del campo cloudinary_url
                if v.get("es_carrusel") and url:
                    primera_url = url.split(",")[0].strip()
                    if primera_url.startswith("http"):
                        _enviar_foto_url(primera_url, caption=caption_prev + "\n<i>(primer slide)</i>")
                        time.sleep(0.3)
                        continue

                if not url:
                    continue

                es_video = nombre.lower().endswith((".mp4", ".mov", ".avi", ".m4v"))
                if es_video:
                    r = _enviar_video_url(url, caption=caption_prev)
                else:
                    r = _enviar_foto_url(url, caption=caption_prev)

                if not r.get("ok"):
                    # Fallback: solo texto si falla el envío del media
                    _enviar_mensaje(f"⚠️ No se pudo previsualizar: {caption_prev}")
                time.sleep(0.3)

    def _mostrar_plan_hoy(self):
        """Muestra el plan de publicación para hoy con el material disponible."""
        import datetime
        from zoneinfo import ZoneInfo

        tz_col = ZoneInfo("America/Bogota")
        ahora = datetime.datetime.now(tz_col)
        dia_semana = ahora.weekday()
        DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

        # Mismo horario que publicar_programado en main.py
        HORARIO = {
            (0, 11, 14): "post",  (0, 18, 22): "reel",
            (1, 11, 14): "post",  (1, 18, 22): "reel",
            (2, 11, 14): "post",  (2, 18, 22): "story",
            (3, 11, 14): "reel",  (3, 18, 22): "story",
            (4, 11, 14): "post",  (4, 18, 22): "reel",
            (5, 11, 14): "post",  (5, 18, 22): "story",
            (6, 11, 14): "story", (6, 18, 22): "story",
        }

        slots_hoy = [
            (h_min, h_max, tipo)
            for (dia, h_min, h_max), tipo in HORARIO.items()
            if dia == dia_semana
        ]
        slots_hoy.sort()  # Ordenar por hora

        EMOJI = {"post": "📸", "reel": "🎬", "story": "⭕", "carrusel": "📖"}
        PILAR_CORTO = {
            "recetas_y_maridajes": "Recetas",
            "lifestyle_y_comunidad": "Lifestyle",
            "humor_picante": "Humor",
            "educacion_sobre_salsas": "Educación",
            "behind_the_scenes": "BTS",
            "promociones_y_lanzamientos": "Promo",
        }

        conteo = contar_pendientes()
        lineas = [f"🗓 <b>Plan de hoy — {DIAS[dia_semana]} {ahora.strftime('%d/%m')}</b>\n"]

        for h_min, h_max, tipo_pref in slots_hoy:
            hora_str = f"{h_min}:00–{h_max}:00"
            emoji = EMOJI.get(tipo_pref, "📌")

            # Ver si hay material del tipo preferido
            items = listar_pendientes(tipo_pref)
            if items:
                it = items[0]
                pilar = PILAR_CORTO.get(it.pilar, it.pilar)
                tiene_url = "☁️" if it.cloudinary_url else "📁"
                lineas.append(
                    f"{emoji} <b>{hora_str}</b> — {tipo_pref.upper()}\n"
                    f"   {tiene_url} {pilar} — <code>{it.nombre_archivo[-25:]}</code>\n"
                    f"   Estado: listo para publicar ✅"
                )
            else:
                # Buscar fallback en otros tipos
                fallback = None
                fallback_tipo = None
                for tipo_alt in ["post", "reel", "story"]:
                    if tipo_alt != tipo_pref:
                        alt_items = listar_pendientes(tipo_alt)
                        if alt_items:
                            fallback = alt_items[0]
                            fallback_tipo = tipo_alt
                            break

                if fallback:
                    pilar = PILAR_CORTO.get(fallback.pilar, fallback.pilar)
                    lineas.append(
                        f"{emoji} <b>{hora_str}</b> — {tipo_pref.upper()} (sin material)\n"
                        f"   ↳ Usará {fallback_tipo.upper()}: {pilar} ✅"
                    )
                elif tipo_pref == "post":
                    lineas.append(
                        f"{emoji} <b>{hora_str}</b> — POST\n"
                        f"   ↳ Sin material — generará carrusel automático 🤖"
                    )
                else:
                    lineas.append(
                        f"{emoji} <b>{hora_str}</b> — {tipo_pref.upper()}\n"
                        f"   ⚠️ Sin material — no se publicará nada"
                    )
            lineas.append("")

        # Resumen de biblioteca
        lineas.append(
            f"<b>Biblioteca:</b> {conteo['post']} posts · {conteo['reel']} reels · "
            f"{conteo['story']} stories · {conteo['carrusel']} carruseles"
        )
        lineas.append(f"\n<i>Hora actual: {ahora.strftime('%H:%M')} COL</i>")

        # Leer pausas ya guardadas para este día
        pausas = self._leer_pausas_hoy()
        fecha_hoy = ahora.strftime("%Y-%m-%d")
        pausas_activas = set(pausas.get("slots_pausados", [])) if pausas.get("fecha") == fecha_hoy else set()
        pausado_todo = pausas.get("pausado_todo", False) and pausas.get("fecha") == fecha_hoy

        # Construir botones de control
        botones_slots = []
        for h_min, _, _ in slots_hoy:
            hora_label = f"12pm" if h_min < 15 else "7pm"
            if h_min in pausas_activas or pausado_todo:
                botones_slots.append({"text": f"✅ Activar {hora_label}", "callback_data": f"hoy:activar:{h_min}"})
            else:
                botones_slots.append({"text": f"⏭ Saltar {hora_label}", "callback_data": f"hoy:saltar:{h_min}"})

        teclado = [botones_slots]
        if pausado_todo:
            teclado.append([{"text": "✅ Activar todo hoy", "callback_data": "hoy:activar_todo"}])
        else:
            teclado.append([{"text": "🚫 No publicar nada hoy", "callback_data": "hoy:pausar_todo"}])

        _enviar_mensaje("\n".join(lineas), reply_markup={"inline_keyboard": teclado})

    def _flujo_venta(self):
        """Genera la serie de 3 stories de conversión a venta con Claude.

        Secuencia:
          Story 1 (Enganche)  — Poll / pregunta de curiosidad
          Story 2 (Prueba)    — Reacción / prueba social
          Story 3 (Cierre)    — CTA directo al WhatsApp

        El agente genera los textos y briefs. El usuario los publica
        manualmente o envía las imágenes al bot para publicarlas como stories.
        """
        _enviar_mensaje("🔥 <b>Generando serie de conversión...</b>\n\nClaude está creando los 3 guiones de story.")

        from agente.claude.cliente_claude import ClienteClaude
        import json as _json
        cliente = ClienteClaude()

        prompt = (
            "Eres el community manager de Salsas Bestial (salsa tatemada artesanal colombiana).\n"
            "Genera una serie de 3 stories de Instagram para convertir seguidores en clientes.\n\n"
            "REGLAS:\n"
            "- Tono: cercano, conversacional, como DM de amigo\n"
            "- Story 1: enganche con pregunta o poll (genera curiosidad, NO menciona el producto aún)\n"
            "- Story 2: prueba social / reacción (introduce el producto con emoción auténtica)\n"
            "- Story 3: CTA directo al WhatsApp con urgencia real (no falsa)\n"
            "- Máximo 2 emojis por story\n"
            "- Cada story debe funcionar sola, pero la serie conecta\n\n"
            "Devuelve SOLO este JSON:\n"
            "{\n"
            '  "story_1": {\n'
            '    "tipo": "poll",\n'
            '    "texto_principal": "texto grande en la story",\n'
            '    "opcion_a": "texto opción A del poll",\n'
            '    "opcion_b": "texto opción B del poll",\n'
            '    "descripcion_visual": "cómo debe verse la story (fondo, colores, imagen sugerida)"\n'
            "  },\n"
            '  "story_2": {\n'
            '    "tipo": "reaccion",\n'
            '    "texto_principal": "texto principal de la story",\n'
            '    "texto_secundario": "detalle adicional o null",\n'
            '    "descripcion_visual": "cómo debe verse",\n'
            '    "gancho_siguiente": "texto pequeño al pie: \'mañana te cuento...\' o similar"\n'
            "  },\n"
            '  "story_3": {\n'
            '    "tipo": "cta",\n'
            '    "texto_principal": "texto de cierre potente",\n'
            '    "texto_cta": "texto exacto del botón o sticker link",\n'
            '    "link": "https://wa.me/573005864523",\n'
            '    "descripcion_visual": "cómo debe verse"\n'
            "  }\n"
            "}"
        )

        try:
            datos = cliente.generar_json(
                prompt_sistema="Eres copywriter experto en Instagram Stories con foco en conversión.",
                prompt_usuario=prompt,
                temperatura=0.85,
            )
        except Exception as e:
            _enviar_mensaje(f"❌ Error generando la serie: {e}")
            return

        s1 = datos.get("story_1", {})
        s2 = datos.get("story_2", {})
        s3 = datos.get("story_3", {})

        # Enviar cada story como mensaje separado
        _enviar_mensaje(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🗓 <b>SERIE VENTA — 3 Stories en días consecutivos</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Crea las 3 imágenes/videos con estos briefs y envíamelas en orden.\n"
            "Las programo como stories en días consecutivos. 👇"
        )
        time.sleep(0.5)

        _enviar_mensaje(
            f"<b>STORY 1 — Enganche (DÍA 1)</b>\n\n"
            f"📝 <b>Texto principal:</b>\n{s1.get('texto_principal', '')}\n\n"
            f"🗳 <b>Poll:</b>\n  A → {s1.get('opcion_a', '')}\n  B → {s1.get('opcion_b', '')}\n\n"
            f"🎨 <b>Visual:</b> {s1.get('descripcion_visual', '')}"
        )
        time.sleep(0.4)

        _enviar_mensaje(
            f"<b>STORY 2 — Prueba social (DÍA 2)</b>\n\n"
            f"📝 <b>Texto principal:</b>\n{s2.get('texto_principal', '')}\n\n"
            + (f"💬 <b>Detalle:</b> {s2.get('texto_secundario', '')}\n\n" if s2.get('texto_secundario') else "")
            + f"🪝 <b>Gancho al día 3:</b> {s2.get('gancho_siguiente', '')}\n\n"
            f"🎨 <b>Visual:</b> {s2.get('descripcion_visual', '')}"
        )
        time.sleep(0.4)

        _enviar_mensaje(
            f"<b>STORY 3 — Cierre / Venta (DÍA 3)</b>\n\n"
            f"📝 <b>Texto principal:</b>\n{s3.get('texto_principal', '')}\n\n"
            f"👉 <b>CTA:</b> {s3.get('texto_cta', '')} → {s3.get('link', '')}\n\n"
            f"🎨 <b>Visual:</b> {s3.get('descripcion_visual', '')}"
        )
        time.sleep(0.4)

        _enviar_mensaje(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✅ <b>¿Cómo publicarlas?</b>\n\n"
            "1. Crea las 3 imágenes/videos con los briefs de arriba\n"
            "2. Envíame cada una al chat (una por día, o las 3 juntas para programar)\n"
            "3. Selecciona <b>Story → Biblioteca</b> en cada una\n"
            "4. El agente las publica en días consecutivos automáticamente\n\n"
            "<i>Consejo: Story 1 funciona sin imagen — solo texto + poll sobre fondo rojo bestial.</i>"
        )

    def _flujo_publicar_ahora(self, tipo_forzado: str | None = None):
        """
        /publicar — dispara el flujo de preview+aprobación+publicación desde Telegram.
        Funciona a cualquier hora, independiente del cron de GitHub Actions.
        Maneja el flujo completo internamente sin subprocess.
        """
        tipos_validos = {"reel", "post", "story", "carrusel"}
        tipos_a_probar = [tipo_forzado] if tipo_forzado in tipos_validos else ["reel", "post", "story"]

        item = None
        tipo_encontrado = None
        for t in tipos_a_probar:
            item = siguiente_pendiente(t)
            if item:
                tipo_encontrado = t
                break

        if not item:
            conteo = contar_pendientes()
            _enviar_mensaje(
                "⚠️ <b>Biblioteca vacía</b> — no hay material pendiente.\n\n"
                f"Posts: {conteo['post']} | Reels: {conteo['reel']} | Stories: {conteo['story']}\n\n"
                "Envíame fotos o videos para cargar la biblioteca."
            )
            return

        # Generar caption si no tiene
        if not item.caption and tipo_encontrado in ("post", "reel"):
            _enviar_mensaje("✍️ Generando caption...")
            item.caption = _generar_caption(tipo_encontrado, getattr(item, "pilar", "recetas_y_maridajes") or "recetas_y_maridajes")

        tipo_label = {"post": "📸 POST", "reel": "🎬 REEL", "story": "⭕ STORY"}.get(tipo_encontrado, tipo_encontrado.upper())
        rev_id = f"bot_{int(time.time())}"
        self._pending_pubs[rev_id] = item

        texto_prev = (
            f"🗓 <b>Publicación — {tipo_label}</b>\n"
            f"👆 Toca ✅ Publicar para que salga al aire\n\n"
            + (f"{item.caption[:600]}\n\n" if item.caption else "")
            + "<i>¿Apruebas esta publicación?</i>"
        )
        botones = {"inline_keyboard": [[
            {"text": "✅ Publicar", "callback_data": f"pub_aprobar:{rev_id}"},
            {"text": "⏭ Saltar",   "callback_data": f"pub_rechazar:{rev_id}"},
        ]]}

        cloudinary_url = getattr(item, "cloudinary_url", "") or ""
        nombre = item.nombre_archivo.lower()
        es_video_url = any(nombre.endswith(e) for e in (".mp4", ".mov", ".avi", ".m4v"))

        enviado = False
        if cloudinary_url:
            if es_video_url:
                r = _enviar_video_url(cloudinary_url, caption=texto_prev, reply_markup=botones)
            else:
                r = _enviar_foto_url(cloudinary_url, caption=texto_prev, reply_markup=botones)
            enviado = r.get("ok", False)
        if not enviado:
            _enviar_mensaje(texto_prev, reply_markup=botones)

    def _publicar_en_hilo(self, item) -> None:
        """Publica el item en Instagram en un hilo separado para no bloquear el bot."""
        from agente.instagram.publicar_item import publicar_item
        try:
            media_id = publicar_item(item)
            if media_id == "SIN_MEDIA":
                marcar_descartado(item.id)
                _enviar_mensaje(
                    f"⚠️ <b>{item.tipo.upper()} descartado</b> — no tiene archivo ni URL.\n"
                    "Sube el archivo a Google Drive y vuelve a agregarlo."
                )
                return
            if media_id:
                marcar_publicado(item.id, media_id)
                emoji = {"post": "📸", "reel": "🎬", "story": "⭕"}.get(item.tipo, "✅")
                _enviar_mensaje(
                    f"{emoji} <b>{item.tipo.upper()} publicado en Instagram</b>\n"
                    f"<a href='https://www.instagram.com/salsas.bestial/'>Ver en @salsas.bestial →</a>"
                )
            else:
                _enviar_mensaje(f"❌ Error publicando {item.tipo.upper()}. Revisa los logs.")
        except Exception as e:
            logger.error("Error en _publicar_en_hilo: %s", e, exc_info=True)
            _enviar_mensaje(f"❌ Error inesperado: {e}")

    def _mostrar_ayuda(self):
        _enviar_mensaje(
            "🤖 <b>Comandos disponibles</b>\n\n"
            "📸 <b>Envía una foto</b> → te pregunto si guardar o publicar ahora\n"
            "🎬 <b>Envía un video</b> → te pregunto si es Reel o Story\n"
            "📖 <b>Envía varias fotos juntas</b> → carrusel automático\n\n"
            "/publicar → envía preview del siguiente item y espera tu ✅\n"
            "/publicar reel → fuerza publicar un Reel\n"
            "/publicar post → fuerza publicar un Post\n"
            "/publicar story → fuerza publicar una Story\n"
            "/hoy → plan de publicación de hoy con material disponible\n"
            "/estado → lista completa del material en biblioteca\n"
            "/carrusel &lt;tema&gt; → genera carrusel educativo con IA\n"
            "/venta → genera serie de 3 stories de conversión a venta\n"
            "/ayuda → este mensaje\n\n"
            "<b>Horario automático:</b>\n"
            "Preview llega ~11:30am y ~6:30pm COL (GitHub Actions)\n\n"
            "⚡ <b>Si no llega el preview automático</b> → escribe <code>/publicar</code>"
        )
