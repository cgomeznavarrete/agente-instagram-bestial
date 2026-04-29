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
    contar_pendientes, marcar_publicado, marcar_descartado,
    EXTENSIONES_IMAGEN, EXTENSIONES_VIDEO,
)
from agente.telegram.notificador import _enviar_mensaje, _enviar_foto, _enviar_video, BASE_URL
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


def _descargar_archivo(file_id: str, extension: str, tipo: str = "media") -> Optional[Path]:
    """Descarga un archivo de Telegram con nombre limpio (sin UUIDs)."""
    try:
        r = requests.get(f"{BASE_URL}/getFile", params={"file_id": file_id}, timeout=15)
        file_path = r.json()["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}"
        contenido = requests.get(url, timeout=60).content
        # Nombre limpio: salsas_bestial_post_20260428_143022.jpg
        from datetime import datetime
        nombre = f"salsas_bestial_{tipo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{extension}"
        ruta = Path(tempfile.gettempdir()) / nombre
        ruta.write_bytes(contenido)
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
            f"- CTA final exacto: Pídela aquí → {brand.LINK_COMPRA_WHATSAPP}\n"
            "- 15 hashtags mezcla español/inglés\n"
            "- Máximo 3 emojis"
        ),
        temperatura=0.85,
        max_tokens=600,
    )
    return re.sub(r"\*\*(.+?)\*\*", r"\1", caption_raw).replace("---", "").strip()


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
        # Estado por chat: guarda contexto entre mensajes
        self.estado: dict = {}  # chat_id → {"paso": str, "datos": dict}

    def _set_estado(self, chat_id: str, paso: str, datos: dict = None):
        self.estado[chat_id] = {"paso": paso, "datos": datos or {}}

    def _get_estado(self, chat_id: str) -> dict:
        return self.estado.get(chat_id, {"paso": "idle", "datos": {}})

    def _clear_estado(self, chat_id: str):
        self.estado.pop(chat_id, None)

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

    def _procesar_update(self, update: dict):
        if "callback_query" in update:
            self._manejar_callback(update["callback_query"])
        elif "message" in update:
            self._manejar_mensaje(update["message"])

    def _manejar_mensaje(self, msg: dict):
        chat_id = str(msg.get("chat", {}).get("id", ""))
        logger.info("Mensaje de chat_id=%s | config=%s | match=%s | keys=%s",
                    chat_id, settings.TELEGRAM_CHAT_ID,
                    chat_id == str(settings.TELEGRAM_CHAT_ID),
                    [k for k in msg if k != "photo"])
        if chat_id != str(settings.TELEGRAM_CHAT_ID):
            logger.warning("Ignorando mensaje de chat_id=%s (no autorizado)", chat_id)
            return  # Solo responder al chat autorizado

        texto = msg.get("text", "").strip()
        foto = msg.get("photo")
        video = msg.get("video")
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

        if texto.startswith("/ayuda") or texto.startswith("/start"):
            self._mostrar_ayuda()
            return

        # ── Foto recibida ─────────────────────────────────────────────────
        if foto:
            file_id = foto[-1]["file_id"]  # La de mayor resolución
            self._recibir_media(file_id, ".jpg", "imagen", chat_id, media_group_id)
            return

        # ── Video recibido ────────────────────────────────────────────────
        if video:
            file_id = video["file_id"]
            self._recibir_media(file_id, ".mp4", "video", chat_id, media_group_id)
            return

        # ── Contexto: esperando pilar ─────────────────────────────────────
        estado = self._get_estado(chat_id)
        if estado["paso"] == "esperando_pilar_texto" and texto:
            pilar = estado["datos"].get("pilar", "lifestyle_y_comunidad")
            self._continuar_flujo_con_pilar(chat_id, pilar)

    def _recibir_media(self, file_id: str, extension: str, tipo_media: str, chat_id: str, media_group_id: str = None):
        """Recibe un archivo y pregunta qué hacer con él."""
        # Guardar temporalmente para luego
        self._set_estado(chat_id, "recibido", {
            "file_id": file_id,
            "extension": extension,
            "tipo_media": tipo_media,
            "media_group_id": media_group_id,
        })

        emoji = "📸" if tipo_media == "imagen" else "🎬"
        tipo_sugerido = "post o story" if tipo_media == "imagen" else "reel o story"

        _enviar_mensaje(
            f"{emoji} <b>Archivo recibido</b>\n\n¿Qué hago con este {tipo_media}?",
            reply_markup={"inline_keyboard": [[
                {"text": "📚 Guardar en biblioteca", "callback_data": f"accion:biblioteca:{file_id}:{extension}:{tipo_media}"},
                {"text": "🚀 Publicar ahora", "callback_data": f"accion:ahora:{file_id}:{extension}:{tipo_media}"},
            ]]}
        )

    def _manejar_callback(self, cb: dict):
        chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
        data = cb.get("data", "")
        cb_id = cb["id"]

        if not data:
            return

        partes = data.split(":")

        # ── Acción principal: biblioteca o ahora ──────────────────────────
        if partes[0] == "accion" and len(partes) >= 5:
            _, destino, file_id, extension, tipo_media = partes[:5]
            _answer_callback(cb_id, "📥 Recibido")

            # Preguntar tipo de contenido
            es_video = tipo_media == "video"
            if es_video:
                botones = [[
                    {"text": "🎬 Reel", "callback_data": f"tipo:reel:{file_id}:{extension}:{destino}"},
                    {"text": "⭕ Story", "callback_data": f"tipo:story:{file_id}:{extension}:{destino}"},
                ]]
            else:
                botones = [[
                    {"text": "📸 Post", "callback_data": f"tipo:post:{file_id}:{extension}:{destino}"},
                    {"text": "⭕ Story", "callback_data": f"tipo:story:{file_id}:{extension}:{destino}"},
                ]]

            _enviar_mensaje(
                f"¿Qué tipo de publicación es?",
                reply_markup={"inline_keyboard": botones}
            )
            return

        # ── Tipo seleccionado ─────────────────────────────────────────────
        if partes[0] == "tipo" and len(partes) >= 5:
            _, tipo_pub, file_id, extension, destino = partes[:5]
            _answer_callback(cb_id, f"{'📚' if destino == 'biblioteca' else '🚀'} {tipo_pub.upper()}")

            # Preguntar pilar (solo para posts y reels)
            if tipo_pub in ("post", "reel"):
                botones_pilar = [
                    [{"text": "🌶 Recetas y maridajes", "callback_data": f"pilar:recetas_y_maridajes:{file_id}:{extension}:{tipo_pub}:{destino}"}],
                    [{"text": "🌅 Lifestyle", "callback_data": f"pilar:lifestyle_y_comunidad:{file_id}:{extension}:{tipo_pub}:{destino}"}],
                    [{"text": "😄 Humor picante", "callback_data": f"pilar:humor_picante:{file_id}:{extension}:{tipo_pub}:{destino}"}],
                    [{"text": "📚 Educación", "callback_data": f"pilar:educacion_sobre_salsas:{file_id}:{extension}:{tipo_pub}:{destino}"}],
                    [{"text": "🎬 Behind the scenes", "callback_data": f"pilar:behind_the_scenes:{file_id}:{extension}:{tipo_pub}:{destino}"}],
                ]
                _enviar_mensaje("¿Cuál es el pilar de contenido?", reply_markup={"inline_keyboard": botones_pilar})
            else:
                # Story → no necesita pilar ni caption
                self._ejecutar_con_pilar(file_id, extension, tipo_pub, destino, "lifestyle_y_comunidad", chat_id)
            return

        # ── Pilar seleccionado ────────────────────────────────────────────
        if partes[0] == "pilar" and len(partes) >= 6:
            _, pilar, file_id, extension, tipo_pub, destino = partes[:6]
            _answer_callback(cb_id, "✍️ Generando caption...")
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

        # ── Aprobar guardar en biblioteca ─────────────────────────────────
        if partes[0] == "guardar" and len(partes) >= 2:
            accion = partes[1]
            estado = self._get_estado(chat_id)
            datos = estado["datos"]

            if accion == "si":
                _answer_callback(cb_id, "📚 Guardando...")
                ruta_tmp = Path(datos["ruta_tmp"])
                tipo_pub = datos["tipo_pub"]
                pilar = datos.get("pilar", "lifestyle_y_comunidad")
                item = agregar_item(ruta_tmp, tipo_pub, pilar)
                ruta_tmp.unlink(missing_ok=True)
                conteo = contar_pendientes()
                _enviar_mensaje(
                    f"📚 <b>Guardado en biblioteca</b>\n\n"
                    f"Tipo: {tipo_pub.upper()} | Pilar: {pilar.replace('_', ' ').title()}\n\n"
                    f"Cola actual:\n"
                    f"  Posts: {conteo['post']} | Reels: {conteo['reel']} | Stories: {conteo['story']}"
                )
            else:
                _answer_callback(cb_id, "🗑 Descartado")
                ruta_tmp = datos.get("ruta_tmp")
                if ruta_tmp:
                    Path(ruta_tmp).unlink(missing_ok=True)
                _enviar_mensaje("🗑 Archivo descartado.")

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

    def _ejecutar_con_pilar(self, file_id: str, extension: str, tipo_pub: str, destino: str, pilar: str, chat_id: str):
        """Descarga el archivo y ejecuta el flujo según destino (biblioteca o ahora)."""
        _enviar_mensaje("⬇️ Descargando archivo...")
        ruta_tmp = _descargar_archivo(file_id, extension, tipo=tipo_pub)
        if not ruta_tmp:
            _enviar_mensaje("❌ Error al descargar el archivo. Intenta de nuevo.")
            return

        if destino == "biblioteca":
            # Mostrar preview y confirmar guardado
            caption_preview = ""
            if tipo_pub in ("post", "reel"):
                _enviar_mensaje("✍️ Generando caption con Claude...")
                caption_preview = _generar_caption(tipo_pub, pilar)

            texto_confirm = (
                f"📚 <b>¿Guardar en biblioteca?</b>\n\n"
                f"Tipo: {tipo_pub.upper()} | Pilar: {pilar.replace('_', ' ').title()}\n\n"
                + (f"Caption preview:\n{caption_preview[:400]}" if caption_preview else "Story — sin caption")
            )
            self._set_estado(chat_id, "esperando_confirmacion_biblioteca", {
                "ruta_tmp": str(ruta_tmp),
                "tipo_pub": tipo_pub,
                "pilar": pilar,
                "caption": caption_preview,
            })

            if extension in (".jpg", ".jpeg", ".png", ".webp"):
                _enviar_foto(ruta_tmp, caption=texto_confirm, reply_markup={"inline_keyboard": [[
                    {"text": "✅ Guardar", "callback_data": "guardar:si"},
                    {"text": "🗑 Descartar", "callback_data": "guardar:no"},
                ]]})
            else:
                _enviar_mensaje(texto_confirm, reply_markup={"inline_keyboard": [[
                    {"text": "✅ Guardar", "callback_data": "guardar:si"},
                    {"text": "🗑 Descartar", "callback_data": "guardar:no"},
                ]]})

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
        caption = re.sub(r"\*\*(.+?)\*\*", r"\1", caption_raw).strip()

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
        conteo = contar_pendientes()
        _enviar_mensaje(
            "📊 <b>Biblioteca de contenido</b>\n\n"
            f"📸 Posts: {conteo['post']} pendientes\n"
            f"🎬 Reels: {conteo['reel']} pendientes\n"
            f"⭕ Stories: {conteo['story']} pendientes\n"
            f"📖 Carruseles: {conteo['carrusel']} pendientes\n\n"
            "<b>Horario de publicación:</b>\n"
            "Lun/Mié/Vie → Story 9am + Post 12pm\n"
            "Mar/Jue → Reel 7pm"
        )

    def _mostrar_ayuda(self):
        _enviar_mensaje(
            "🤖 <b>Comandos disponibles</b>\n\n"
            "📸 <b>Envía una foto</b> → te pregunto si guardar o publicar ahora\n"
            "🎬 <b>Envía un video</b> → te pregunto si es Reel o Story\n"
            "📖 <b>Envía varias fotos juntas</b> → carrusel automático\n\n"
            "/carrusel <tema> → genera carrusel educativo con IA\n"
            "/estado → ver cuánto material hay en biblioteca\n"
            "/ayuda → este mensaje\n\n"
            "<b>Horario automático:</b>\n"
            "Lun/Mié/Vie: Story 9am + Post 12pm\n"
            "Mar/Jue: Reel 7pm"
        )
