"""
Bot de Telegram — interfaz principal del agente.

El usuario envía fotos/videos desde el celular. El bot pregunta:
  [📚 Biblioteca] → guarda para publicación programada
  [🚀 Publicar ahora] → flujo inmediato con aprobación

Comando /carrusel <tema> → genera carrusel HTML→PNG y pregunta dónde enviarlo.
Comando /estado → muestra cuánto material hay en la biblioteca.
"""

import html as _html
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
    mover_al_final,
    EXTENSIONES_IMAGEN, EXTENSIONES_VIDEO, BIBLIOTECA_JSON,
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


def _primera_url(cloudinary_url: str) -> str:
    """Extrae la primera URL válida de cloudinary_url.

    Los carruseles guardan varias URLs separadas por coma.
    Telegram solo acepta una URL por vez — siempre usar solo la primera.
    """
    if not cloudinary_url:
        return ""
    partes = [u.strip() for u in cloudinary_url.split(",") if u.strip().startswith("http")]
    return partes[0] if partes else cloudinary_url.strip()


def _es_video_url(url: str) -> bool:
    """True si la URL apunta a un video (mp4, mov, o contiene /video/)."""
    u = url.lower()
    return "/video/" in u or u.endswith((".mp4", ".mov", ".m4v", ".avi"))


def _enviar_media_url(url: str, caption: str = "") -> dict:
    """Envía foto o video por URL, detectando el tipo automáticamente."""
    url1 = _primera_url(url)
    if not url1:
        return {"ok": False}
    if _es_video_url(url1):
        return _enviar_video_url(url1, caption=caption)
    return _enviar_foto_url(url1, caption=caption)


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


def _publicar_ahora_imagen(ruta: Path, caption: str, pilar: str = "") -> Optional[str]:
    """
    Convierte la imagen a Reel MP4 con música y publica en Instagram.
    La Instagram Graph API no permite música en posts estáticos — la única
    forma de tener audio es publicar como video (Reel).
    Si la conversión falla, publica como imagen estática (sin música).
    """
    from agente.instagram.publicar_item import _imagen_a_reel_cloudinary, _publicar_video_como_reel

    # Intentar convertir a Reel con música
    url_video = _imagen_a_reel_cloudinary(ruta, pilar)
    if url_video:
        logger.info("Imagen convertida a Reel con musica: %s", ruta.name)
        return _publicar_video_como_reel(url_video, caption)

    # Fallback: imagen estática sin música
    logger.warning("Fallback: publicando imagen estática sin música")
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
    """Story de imagen → convierte a video con música antes de publicar."""
    from agente.generadores.video_automatico import imagen_a_video_story
    from config.imagen_params import MOOD_POR_PILAR
    import random, cloudinary, cloudinary.uploader
    cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL)

    # Convertir a video con música
    try:
        mood = random.choice(["chill_food", "upbeat_latino"])
        ruta_video = imagen_a_video_story(ruta, mood_musica=mood, duracion=15)
        if ruta_video and ruta_video.exists():
            url_video = cloudinary.uploader.upload(
                str(ruta_video), folder="salsas_bestial", resource_type="video"
            )["secure_url"]
            r = requests.post(
                f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
                data={"video_url": url_video, "media_type": "STORIES", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=120,
            )
            if r.status_code == 200:
                creation_id = r.json()["id"]
                r2 = requests.post(
                    f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
                    data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                    timeout=60,
                )
                return r2.json().get("id") if r2.status_code == 200 else None
    except Exception as e:
        logger.warning("No se pudo convertir story imagen a video: %s — publicando imagen estática", e)

    # Fallback: imagen estática sin música
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
        self._aprobaciones_path = Path("datos/aprobaciones_hoy.json")
        self._pending_pubs_path = Path("datos/pending_pubs.json")
        self._pending_pubs: dict = self._cargar_pending_pubs()

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

    def _leer_aprobaciones_hoy(self) -> dict:
        """Lee {fecha, aprobados: {slot_key: item_id}}"""
        try:
            if self._aprobaciones_path.exists():
                return json.loads(self._aprobaciones_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _guardar_aprobaciones_hoy(self, aprobaciones: dict):
        self._aprobaciones_path.parent.mkdir(parents=True, exist_ok=True)
        self._aprobaciones_path.write_text(json.dumps(aprobaciones, ensure_ascii=False, indent=2), encoding="utf-8")
        _commit_json_github(str(self._aprobaciones_path), "datos/aprobaciones_hoy.json", "chore: aprobaciones del dia actualizadas")

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

    def _cargar_pending_pubs(self) -> dict:
        """Carga el mapa rev_id → item_id desde disco."""
        try:
            if self._pending_pubs_path.exists():
                data = json.loads(self._pending_pubs_path.read_text(encoding="utf-8"))
                # Restore full item objects from biblioteca using listar_pendientes
                items_por_id = {}
                for tipo in ("post", "reel", "story", "carrusel"):
                    for it in listar_pendientes(tipo):
                        items_por_id[it.id] = it
                result = {}
                for rev_id, item_id in data.items():
                    if item_id in items_por_id:
                        result[rev_id] = items_por_id[item_id]
                if result:
                    logger.info("Restaurados %d pending_pubs desde disco", len(result))
                return result
        except Exception as e:
            logger.warning("No se pudo cargar pending_pubs: %s", e)
        return {}

    def _guardar_pending_pubs(self):
        """Persiste el mapa rev_id → item_id a disco."""
        try:
            self._pending_pubs_path.parent.mkdir(parents=True, exist_ok=True)
            data = {rev_id: item.id for rev_id, item in self._pending_pubs.items()}
            self._pending_pubs_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("No se pudo guardar pending_pubs: %s", e)

    def _guardar_razon_salto(self, rev_id: str, razon: str):
        """Persiste razones de salto a datos/razones_salto.json."""
        import datetime
        ruta = Path("datos/razones_salto.json")
        try:
            datos = []
            if ruta.exists():
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            datos.append({
                "ts": datetime.datetime.now().isoformat(),
                "rev_id": rev_id,
                "razon": razon,
            })
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("No se pudo guardar razón de salto: %s", e)

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
        # Evitar spam: solo notificar al usuario si el bot no se notificó en las
        # últimas 4 horas (cada run de GitHub Actions dura ~5h, así que 1 notif/día).
        _ultimo_inicio_path = Path("datos/bot_ultimo_inicio.json")
        _ahora_ts = time.time()
        _debe_notificar = True
        try:
            if _ultimo_inicio_path.exists():
                _ts_prev = json.loads(_ultimo_inicio_path.read_text(encoding="utf-8")).get("ts", 0)
                if _ahora_ts - _ts_prev < 4 * 3600:  # < 4h → silencio
                    _debe_notificar = False
        except Exception:
            pass
        if _debe_notificar:
            _ultimo_inicio_path.parent.mkdir(parents=True, exist_ok=True)
            _ultimo_inicio_path.write_text(json.dumps({"ts": _ahora_ts}), encoding="utf-8")
            conteo_inic = contar_pendientes()
            _enviar_mensaje(
                "🤖 <b>Agente Salsas Bestial activo</b>\n\n"
                f"📚 Biblioteca: {conteo_inic['post']} posts · {conteo_inic['reel']} reels · {conteo_inic['story']} stories\n\n"
                "Mándame una foto o video para agregar a la biblioteca.\n\n"
                "Comandos:\n"
                "/publicar — siguiente pendiente con botones ✅\n"
                "/hoy — plan de publicación de hoy\n"
                "/biblioteca — ver y gestionar todo el material\n"
                "/ayuda — ver todos los comandos"
            )

        while True:
            updates = _get_updates(self.offset, timeout=20)
            for update in updates:
                self.offset = update["update_id"] + 1
                # Ignorar mensajes con más de 10 min de antigüedad (evita re-procesar al reiniciar)
                # 10 min cubre el gap de reinicio de GitHub Actions (~3-4 min de setup)
                msg = update.get("message") or {}
                msg_date = msg.get("date", 0)
                if msg_date and time.time() - msg_date > 600:
                    logger.info("Saltando mensaje antiguo (>10min): update_id=%s", update["update_id"])
                    continue
                logger.info("Update recibido: id=%s tipos=%s", update["update_id"], list(update.keys()))
                try:
                    self._procesar_update(update)
                except Exception as e:
                    logger.error("Error procesando update %s: %s", update["update_id"], e, exc_info=True)
                    try:
                        _enviar_mensaje(
                            f"⚠️ Error interno: <code>{_html.escape(str(e))}</code>\n\n"
                            "Escribe /publicar para reintentar."
                        )
                    except Exception:
                        pass

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

        if texto.startswith("/biblioteca"):
            self._mostrar_biblioteca()
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

        if texto.startswith("/comandos"):
            self._mostrar_comandos()
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
            file_size_mb = round(video.get("file_size", 0) / (1024 * 1024), 1)
            logger.info("Video recibido (%.1fMB), procesando...", file_size_mb)
            if video.get("file_size", 0) > 20 * 1024 * 1024:
                _enviar_mensaje(
                    f"⚠️ <b>Video demasiado grande</b> ({file_size_mb}MB)\n\n"
                    "Telegram Bot API tiene un límite de <b>20MB</b>.\n\n"
                    "Opciones:\n"
                    "• Comprime el video antes de enviarlo\n"
                    "• Recórtalo en clips más cortos\n"
                    "• Usa una app como <b>Video Compress</b> para reducir el tamaño"
                )
                return
            file_id = video["file_id"]
            self._recibir_media(file_id, ".mp4", "video", chat_id, media_group_id)
            return

        # ── Video note (video circular de Telegram) ───────────────────────
        video_note = msg.get("video_note")
        if video_note:
            logger.info("Video note (circular) recibido, procesando...")
            if video_note.get("file_size", 0) > 20 * 1024 * 1024:
                _enviar_mensaje("⚠️ Video demasiado grande (>20MB). Recórtalo y envíalo de nuevo.")
                return
            self._recibir_media(video_note["file_id"], ".mp4", "video", chat_id, None)
            return

        # ── Documento recibido (foto enviada como archivo) ────────────────
        if documento:
            mime = documento.get("mime_type", "")
            logger.info("Documento recibido, mime_type=%s", mime)
            if mime.startswith("image/"):
                ext = ".jpg" if "jpeg" in mime else ".png" if "png" in mime else ".jpg"
                self._recibir_media(documento["file_id"], ext, "imagen", chat_id, media_group_id)
            elif mime.startswith("video/"):
                file_size = documento.get("file_size", 0)
                if file_size > 20 * 1024 * 1024:
                    _enviar_mensaje(
                        f"⚠️ <b>Video demasiado grande</b> ({round(file_size/(1024*1024),1)}MB)\n\n"
                        "Telegram limita archivos a 20MB. Comprime el video antes de enviarlo."
                    )
                    return
                self._recibir_media(documento["file_id"], ".mp4", "video", chat_id, media_group_id)
            else:
                _enviar_mensaje(
                    f"Recibí un archivo ({mime}), pero solo proceso imágenes y videos.\n"
                    "Envíame una foto directamente desde la galería."
                )
            return

        # ── Contexto: estado conversacional ──────────────────────────────
        estado = self._get_estado(chat_id)

        # ── Estado inesperado: esperando_razon_salto (legado — ya no se usa) ──
        # pub_rechazar ahora muestra botones inline directamente. Si por alguna
        # razón el estado quedó en este valor (sesión antigua), limpiar y continuar.
        if estado["paso"] == "esperando_razon_salto":
            self._clear_estado(chat_id)
            _enviar_mensaje("⏭ Sesión anterior limpiada. Escribe /publicar para continuar.")
            return

        # ── Caption rechazado — reescribir ────────────────────────────────
        if estado["paso"] == "esperando_ajuste" and texto:
            if texto.lower().strip() in ("saltar", "skip", "omitir", "no", "/siguiente"):
                self._clear_estado(chat_id)
                _enviar_mensaje("⏭ Ok, saltado. Envíame más material cuando quieras.")
                return
            datos = estado.get("datos", {})
            tipo_pub = datos.get("tipo_pub", "post")
            pilar = datos.get("pilar", "recetas_y_maridajes")
            caption_anterior = datos.get("caption", "")
            _enviar_mensaje("✍️ Reescribiendo el caption con tu corrección...")
            try:
                cliente = ClienteClaude()
                from agente.claude.cliente_claude import limpiar_caption
                caption_raw = cliente.generar(
                    prompt_sistema=(
                        "Eres el community manager de Salsas Bestial, marca colombiana de salsas picantes. "
                        "Reescribe el caption según el feedback del usuario. "
                        "Tono: cercano, real, apasionado. Sin frases publicitarias genéricas."
                    ),
                    prompt_usuario=(
                        f"Caption anterior:\n{caption_anterior}\n\n"
                        f"Feedback del usuario: {texto}\n\n"
                        f"Tipo: {tipo_pub.upper()}. Pilar: {pilar}.\n"
                        "Reescribe el caption completo incorporando el feedback. "
                        f"Mantén el CTA exacto: Pídela aquí → {brand.LINK_COMPRA_WHATSAPP}"
                    ),
                    temperatura=0.85,
                    max_tokens=600,
                )
                caption_nuevo = limpiar_caption(re.sub(r"\*\*(.+?)\*\*", r"\1", caption_raw))
                rev_id = f"rev_{int(time.time())}"
                datos_nuevos = {**datos, "caption": caption_nuevo, "rev_id": rev_id}
                self._set_estado(chat_id, "esperando_aprobacion", datos_nuevos)
                ruta = datos.get("ruta_tmp", "")
                texto_rev = (
                    f"✍️ <b>Caption reescrito</b>\n\n{caption_nuevo[:700]}\n\n"
                    "<i>¿Publicar en Instagram?</i>"
                )
                botones_rev = {"inline_keyboard": [[
                    {"text": "✅ Publicar",  "callback_data": f"pub:aprobar:{rev_id}"},
                    {"text": "❌ Rechazar", "callback_data": f"pub:rechazar:{rev_id}"},
                ]]}
                ext = datos.get("extension", ".jpg")
                if ruta and Path(ruta).exists() and ext in (".jpg", ".jpeg", ".png", ".webp"):
                    _enviar_foto(Path(ruta), caption=texto_rev, reply_markup=botones_rev)
                else:
                    _enviar_mensaje(texto_rev, reply_markup=botones_rev)
            except Exception as e:
                logger.error("Error reescribiendo caption: %s", e)
                _enviar_mensaje("❌ Error reescribiendo el caption. Intenta de nuevo.")
            return

        # ── Corrección de caption de biblioteca (/publicar flow) ──────────
        if estado["paso"] == "esperando_correccion_biblioteca" and texto:
            rev_id = estado["datos"].get("rev_id", "")
            item = self._pending_pubs.get(rev_id)
            if not item:
                _enviar_mensaje("⚠️ El item ya no está disponible. Escribe /publicar para ver el siguiente.")
                self._clear_estado(chat_id)
                return
            texto_lower = texto.lower().strip()
            # Detectar intención "ya lo publiqué"
            ya_publicado_frases = ("ya lo publiqué", "ya publiqué", "ya fue publicado",
                                   "ya estaba publicado", "ya lo publique", "ya publique")
            if any(f in texto_lower for f in ya_publicado_frases):
                self._pending_pubs.pop(rev_id, None)
                self._guardar_pending_pubs()
                marcar_publicado(item.id, "manual")
                try:
                    _commit_biblioteca()
                except Exception:
                    pass
                self._clear_estado(chat_id)
                _enviar_mensaje(
                    f"✅ <b>Marcado como publicado.</b>\n"
                    f"<code>{_html.escape(item.nombre_archivo)}</code>\n\n"
                    "Escribe /publicar para ver el siguiente."
                )
                return
            # Tratar como instrucción de corrección de caption
            _enviar_mensaje("✍️ Aplicando tu corrección con Claude...")
            try:
                cliente = ClienteClaude()
                from agente.claude.cliente_claude import limpiar_caption
                caption_anterior = item.caption or ""
                caption_raw = cliente.generar(
                    prompt_sistema=(
                        "Eres el community manager de Salsas Bestial, marca colombiana de salsas picantes artesanales. "
                        "Reescribe el caption según la instrucción del usuario. "
                        "Tono: cercano, real, apasionado por el picante. Sin frases publicitarias genéricas."
                    ),
                    prompt_usuario=(
                        f"Caption actual:\n{caption_anterior}\n\n"
                        f"Instrucción: {texto}\n\n"
                        f"Tipo: {item.tipo.upper()}. Pilar: {item.pilar}.\n"
                        "Aplica la instrucción y devuelve SOLO el caption reescrito completo. "
                        f"CTA obligatorio al final: Pídela aquí → {brand.LINK_COMPRA_WHATSAPP}"
                    ),
                    temperatura=0.85,
                    max_tokens=600,
                )
                caption_nuevo = limpiar_caption(re.sub(r"\*\*(.+?)\*\*", r"\1", caption_raw))
                # Actualizar caption en el item y en pending_pubs
                item.caption = caption_nuevo
                self._pending_pubs[rev_id] = item
                self._guardar_pending_pubs()
                # Enviar nuevo preview
                self._enviar_preview_biblioteca(item, rev_id, nota="✏️ Caption corregido")
                self._clear_estado(chat_id)
            except Exception as e:
                logger.error("Error corrigiendo caption biblioteca: %s", e, exc_info=True)
                _enviar_mensaje(f"❌ Error aplicando la corrección: {_html.escape(str(e))}\nIntenta de nuevo.")
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
                # Solo llegó una — tratar como media individual
                a = archivos[0]
                tipo_media_album = "video" if a["extension"] in (".mp4", ".mov", ".m4v", ".avi") else "imagen"
                emoji_album = "🎬" if tipo_media_album == "video" else "📸"
                label_album = "video" if tipo_media_album == "video" else "imagen"
                estado[chat_id] = {
                    "paso": "recibido",
                    "datos": {"file_id": a["file_id"], "extension": a["extension"], "tipo_media": tipo_media_album},
                    "ts": ahora,
                }
                _enviar_mensaje(
                    f"{emoji_album} <b>{label_album.title()} recibido</b>\n\n¿Qué hago con este {label_album}?",
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

        # ── Atajos de /comandos ───────────────────────────────────────────
        if partes[0] == "cmd" and len(partes) >= 2:
            accion = partes[1]
            _answer_callback(cb_id)
            if accion == "hoy":
                self._mostrar_plan_hoy()
            elif accion == "publicar":
                self._flujo_publicar_ahora(None)
            elif accion == "estado":
                self._mostrar_estado()
            return

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
                        {"text": "📸 Post",  "callback_data": "tipo:post"},
                        {"text": "🎬 Reel",  "callback_data": "tipo:reel"},
                        {"text": "⭕ Story", "callback_data": "tipo:story"},
                    ],
                    [{"text": "❌ Cancelar", "callback_data": "tipo:cancelar"}],
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
                import threading
                threading.Thread(
                    target=self._publicar_aprobado,
                    args=(datos, chat_id),
                    daemon=True,
                ).start()
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

        # ── Biblioteca: marcar publicado / descartar ──────────────────────
        if partes[0] == "bib" and len(partes) >= 3:
            accion, item_id = partes[1], partes[2]
            if accion == "publicado":
                marcar_publicado(item_id)
                _commit_json_github(
                    str(BIBLIOTECA_JSON), "datos/biblioteca.json",
                    f"chore: {item_id} marcado como publicado desde Telegram",
                )
                _answer_callback(cb_id, "✅ Marcado como publicado")
                _enviar_mensaje(f"✅ <b>Publicado</b> — eliminado de la biblioteca.\n<code>{item_id}</code>")
            elif accion == "descartar":
                marcar_descartado(item_id)
                _commit_json_github(
                    str(BIBLIOTECA_JSON), "datos/biblioteca.json",
                    f"chore: {item_id} descartado desde Telegram",
                )
                _answer_callback(cb_id, "🗑 Descartado")
                _enviar_mensaje(f"🗑 <b>Descartado</b> — eliminado de la biblioteca.\n<code>{item_id}</code>")
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

            elif accion == "noop":
                _answer_callback(cb_id, "✅ Ya está aprobado")

            elif accion == "aprobar" and len(partes) >= 4:
                # hoy:aprobar:<slot_key>:<item_id>
                slot_key_apr = partes[2]
                item_id_apr = partes[3]
                hora_label_apr = "12pm" if int(slot_key_apr) < 15 else "7pm"
                aprobaciones_data = self._leer_aprobaciones_hoy()
                if aprobaciones_data.get("fecha") != fecha_hoy:
                    aprobaciones_data = {"fecha": fecha_hoy, "aprobados": {}}
                aprobaciones_data["aprobados"][slot_key_apr] = item_id_apr
                self._guardar_aprobaciones_hoy(aprobaciones_data)
                _answer_callback(cb_id, f"✅ Aprobado para {hora_label_apr}")
                _enviar_mensaje(
                    f"✅ <b>Aprobado para {hora_label_apr}</b>\n\n"
                    f"El material se publicará automáticamente a las {hora_label_apr}.\n"
                    f"Si querés cambiarlo, escribe /hoy."
                )

            elif accion == "ya_publique" and len(partes) >= 5:
                # hoy:ya_publique:<item_id>:<slot_key>:<tipo>
                item_id_pub = partes[2]
                slot_key_pub = partes[3]
                tipo_slot = partes[4]
                hora_label_pub = "12pm" if int(slot_key_pub) < 15 else "7pm"
                # Marcar como publicado
                marcar_publicado(item_id_pub)
                _commit_json_github(
                    str(BIBLIOTECA_JSON), "datos/biblioteca.json",
                    f"chore: {item_id_pub} marcado publicado desde /hoy",
                )
                _answer_callback(cb_id, f"✅ Marcado como publicado")
                # Buscar el siguiente ítem que tomará su lugar
                siguiente = siguiente_pendiente(tipo_slot)
                if not siguiente:
                    for t in ["reel", "post", "story"]:
                        siguiente = siguiente_pendiente(t)
                        if siguiente:
                            break
                if siguiente:
                    EMOJI_T = {"post": "📸", "reel": "🎬", "story": "⭕", "carrusel": "📖"}
                    tipo_sig = "carrusel" if siguiente.es_carrusel else siguiente.tipo
                    primera = str(siguiente.caption).split("\n")[0].strip()[:120] if siguiente.caption else ""
                    _enviar_mensaje(
                        f"✅ <b>Publicado</b> — slot {hora_label_pub} actualizado.\n\n"
                        f"{EMOJI_T.get(tipo_sig,'📌')} Siguiente: <b>{tipo_sig.upper()}</b>\n"
                        f"🪝 <i>{_html.escape(primera)}</i>\n\n"
                        f"Escribe /hoy para ver el plan actualizado."
                    )
                    # Enviar preview del nuevo ítem
                    if siguiente.cloudinary_url or siguiente.ruta_local:
                        caption_sig = f"{EMOJI_T.get(tipo_sig,'📌')} Nuevo material para {hora_label_pub}"
                        if siguiente.ruta_local and Path(siguiente.ruta_local).exists():
                            ruta_l = Path(siguiente.ruta_local)
                            if ruta_l.suffix.lower() in (".mp4", ".mov", ".m4v"):
                                _enviar_video(ruta_l, caption=caption_sig)
                            else:
                                _enviar_foto(ruta_l, caption=caption_sig)
                        elif siguiente.cloudinary_url:
                            _enviar_media_url(siguiente.cloudinary_url, caption=caption_sig)
                else:
                    _enviar_mensaje(
                        f"✅ <b>Publicado</b> — biblioteca vacía para este tipo.\n"
                        f"Envíame más material para seguir publicando."
                    )

            elif accion in ("saltar", "pausar_slot") and len(partes) >= 3:
                h_min = int(partes[2])
                hora_label = "12pm" if h_min < 15 else "7pm"
                if h_min not in pausas["slots_pausados"]:
                    pausas["slots_pausados"].append(h_min)
                self._guardar_pausas_hoy(pausas)
                _answer_callback(cb_id, f"⏭ Slot {hora_label} saltado")
                _enviar_mensaje(f"⏭ Slot de <b>{hora_label}</b> no se publicará hoy.\nEscribe /hoy para ver el plan actualizado.")

            elif accion in ("activar", "activar_slot") and len(partes) >= 3:
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
                # Carruseles NO se publican automáticamente — el usuario los publica
                # manualmente en Instagram para poder agregarle música desde la app.
                _enviar_mensaje("✍️ Generando caption con Claude...")
                from agente.claude.cliente_claude import ClienteClaude, limpiar_caption
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
                caption = limpiar_caption(_re.sub(r"\*\*(.+?)\*\*", r"\1", caption_raw))
                _enviar_mensaje(
                    f"📋 <b>Caption listo — publícalo manualmente:</b>\n\n"
                    f"{caption}\n\n"
                    f"📌 <i>Las fotos ya las tenés en Telegram. "
                    f"Publicá el carrusel desde Instagram y agregale música desde la app.</i>"
                )

            self._clear_estado(chat_id)
            return

        # ── Callbacks del workflow publicar_programado (prog_si / prog_no) ──
        # IMPORTANTE: estos callbacks los escucha el workflow, NO el bot.
        # El bot los recibe solo si gana la race condition de getUpdates.
        # En ese caso: responder con texto neutral y NO procesar lógica del bot.
        if partes[0] in ("prog_si", "prog_no") and len(partes) >= 2:
            # El workflow ya no usará pub_aprobar/pub_rechazar para evitar conflictos.
            # Si el bot llega aquí primero, responder sin hacer nada más.
            _answer_callback(cb_id, "⏳ Procesando...")
            logger.info("Bot recibió callback del workflow (%s) — ignorando lógica del bot", data)
            return

        # ── Carrusel: publicar ahora o biblioteca ─────────────────────────
        if partes[0] == "carrusel" and len(partes) >= 2:
            accion = partes[1]
            estado = self._get_estado(chat_id)
            datos = estado["datos"]
            rutas = [Path(r) for r in datos.get("rutas_slides", [])]
            caption = datos.get("caption", "")

            if accion == "ahora":
                # Carruseles NO se publican automáticamente — el usuario los publica
                # manualmente desde Instagram para poder agregarle música desde la app.
                _answer_callback(cb_id, "📋 Caption listo")
                _enviar_mensaje(
                    f"📋 <b>Caption para el carrusel — publicalo manualmente:</b>\n\n"
                    f"{caption}\n\n"
                    f"📌 <i>Abrí Instagram → Nueva publicación → seleccioná los slides "
                    f"→ Siguiente → agregá música → pegá este caption → Compartir.</i>"
                )
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
            self._guardar_pending_pubs()
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
            _answer_callback(cb_id, "⏭ ¿Qué hacemos?")
            _enviar_mensaje(
                "⏭ <b>Saltado — ¿qué quieres hacer?</b>",
                reply_markup={"inline_keyboard": [
                    [{"text": "✍️ Corregir caption",  "callback_data": f"pub_corregir:{rev_id}"}],
                    [{"text": "✅ Ya lo publiqué",     "callback_data": f"pub_publicado:{rev_id}"}],
                    [{"text": "⏭ Pasar al siguiente", "callback_data": f"pub_skip:{rev_id}"}],
                ]},
            )
            return

        if partes[0] == "pub_corregir" and len(partes) >= 2:
            rev_id = partes[1]
            item = self._pending_pubs.get(rev_id)
            if not item:
                _answer_callback(cb_id, "⚠️ Expirado")
                _enviar_mensaje("⚠️ Este item ya no está disponible. Escribe /publicar para ver el siguiente.")
                return
            _answer_callback(cb_id, "✍️ Escribe la corrección")
            self._set_estado(chat_id, "esperando_correccion_biblioteca", {"rev_id": rev_id})
            pilar_label = _html.escape((item.pilar or "").replace("_", " ").title())
            _enviar_mensaje(
                f"✍️ <b>Corregir {item.tipo.upper()} — {pilar_label}</b>\n\n"
                "Escribe qué cambiar. Ejemplos:\n"
                "• <i>El texto es muy largo, acortalo</i>\n"
                "• <i>Tono muy comercial, hazlo más personal</i>\n"
                "• <i>Cambia el hook por algo más impactante</i>\n"
                "• <i>Ya lo publiqué</i> — para marcarlo como publicado\n\n"
                "Claude aplica tu instrucción y te manda el nuevo preview al instante."
            )
            return

        if partes[0] == "pub_publicado" and len(partes) >= 2:
            rev_id = partes[1]
            item = self._pending_pubs.pop(rev_id, None)
            self._guardar_pending_pubs()
            _answer_callback(cb_id, "✅ Marcado como publicado")
            self._clear_estado(chat_id)
            if item:
                try:
                    marcar_publicado(item.id, "manual")
                    _commit_biblioteca()
                except Exception as e:
                    logger.warning("Error marcando publicado: %s", e)
                _enviar_mensaje(
                    f"✅ <b>Marcado como publicado.</b>\n"
                    f"<code>{_html.escape(item.nombre_archivo)}</code>\n\n"
                    "Escribe /publicar para ver el siguiente."
                )
            else:
                _enviar_mensaje("✅ Marcado como publicado.\n\nEscribe /publicar para ver el siguiente.")
            return

        if partes[0] == "pub_skip" and len(partes) >= 2:
            rev_id = partes[1]
            item = self._pending_pubs.pop(rev_id, None)
            self._guardar_pending_pubs()
            _answer_callback(cb_id, "⏭ Saltado")
            self._clear_estado(chat_id)
            if item:
                try:
                    mover_al_final(item.id)
                    _commit_biblioteca()
                except Exception as e:
                    logger.warning("Error moviendo al final: %s", e)
                conteo = contar_pendientes()
                _enviar_mensaje(
                    f"⏭ <b>Saltado</b> — movido al final de la cola.\n"
                    f"Cola: {conteo['reel']} reels · {conteo['post']} posts · {conteo['story']} stories\n\n"
                    "Escribe /publicar para ver el siguiente."
                )
            else:
                _enviar_mensaje("⏭ Saltado.\n\nEscribe /publicar para ver el siguiente.")
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
            elif extension in (".mp4", ".mov", ".m4v", ".avi"):
                _enviar_video(ruta_tmp, caption=texto_rev, reply_markup=botones_rev)
            else:
                _enviar_mensaje(texto_rev, reply_markup=botones_rev)

    def _publicar_aprobado(self, datos: dict, chat_id: str):
        ruta = Path(datos["ruta_tmp"])
        tipo_pub = datos["tipo_pub"]
        caption = datos["caption"]
        extension = datos.get("extension", ".jpg")
        pilar = datos.get("pilar", "")
        es_video = extension in (".mp4", ".mov", ".avi", ".m4v")

        _enviar_mensaje("📤 Subiendo a Cloudinary y publicando en Instagram...")

        media_id = None
        try:
            if (tipo_pub in ("post", "reel")) and not es_video:
                # Imagen → siempre convierte a Reel MP4 con música (post y reel dan igual resultado)
                media_id = _publicar_ahora_imagen(ruta, caption, pilar)
            elif tipo_pub == "story" and not es_video:
                media_id = _publicar_ahora_story_imagen(ruta)
            elif tipo_pub in ("post", "reel") and es_video:
                # Video → publicar como Reel directamente
                subidor = SubidorCloudinary()
                url = subidor.subir(ruta, resource_type="video")
                if url:
                    media_id = self._publicar_reel_ig(url, caption)
                else:
                    logger.error("No se pudo subir video a Cloudinary")
            elif tipo_pub == "story" and es_video:
                subidor = SubidorCloudinary()
                url = subidor.subir(ruta, resource_type="video")
                if url:
                    media_id = self._publicar_story_video_ig(url)
                else:
                    logger.error("No se pudo subir story video a Cloudinary")
            else:
                logger.error(
                    "Combinación no manejada: tipo_pub=%s es_video=%s extension=%s",
                    tipo_pub, es_video, extension,
                )
        except Exception as e:
            logger.error("Error en _publicar_aprobado: %s", e, exc_info=True)
            _enviar_mensaje(f"❌ Error inesperado al publicar: {_html.escape(str(e))}")
            ruta.unlink(missing_ok=True)
            self._clear_estado(chat_id)
            return

        ruta.unlink(missing_ok=True)
        self._clear_estado(chat_id)

        if media_id:
            emoji = "🎬" if (tipo_pub in ("post", "reel") and not es_video) else (
                "🎬" if tipo_pub == "reel" else "⭕" if tipo_pub == "story" else "📸"
            )
            _enviar_mensaje(
                f"{emoji} <b>Publicado en Instagram como REEL</b>\n"
                f"<a href='https://www.instagram.com/salsas.bestial/'>Ver en @salsas.bestial →</a>"
            )
        else:
            _enviar_mensaje(
                "❌ <b>Error al publicar.</b> Posibles causas:\n"
                "• El video tardó demasiado en procesarse en Instagram\n"
                "• Error de conexión con Cloudinary o Instagram\n"
                "Revisa los logs del bot para el detalle exacto."
            )

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
            logger.error("Error container reel: %s", r.text)
            return None
        creation_id = r.json()["id"]
        procesado = False
        for _ in range(18):
            time.sleep(10)
            st = requests.get(
                f"https://graph.facebook.com/v21.0/{creation_id}",
                params={"fields": "status_code", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=30,
            ).json().get("status_code", "")
            if st == "FINISHED":
                procesado = True
                break
            if st == "ERROR":
                logger.error("Error procesando reel en Instagram")
                return None
        if not procesado:
            logger.error("Timeout esperando reel FINISHED tras 180s — abortando")
            return None
        r2 = requests.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
            data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
            timeout=60,
        )
        if r2.status_code != 200:
            logger.error("Error media_publish reel: %s", r2.text)
            return None
        return r2.json().get("id")

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
            logger.error("Error container story video: %s", r.text)
            return None
        creation_id = r.json()["id"]
        procesado = False
        for _ in range(24):
            time.sleep(10)
            st = requests.get(
                f"https://graph.facebook.com/v21.0/{creation_id}",
                params={"fields": "status_code", "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
                timeout=30,
            ).json().get("status_code", "")
            if st == "FINISHED":
                procesado = True
                break
            if st == "ERROR":
                logger.error("Error procesando story video en Instagram")
                return None
        if not procesado:
            logger.error("Timeout esperando story video FINISHED tras 240s — abortando")
            return None
        r2 = requests.post(
            f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
            data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
            timeout=60,
        )
        if r2.status_code != 200:
            logger.error("Error media_publish story video: %s", r2.text)
            return None
        return r2.json().get("id")

    def _publicar_carrusel_ig(self, rutas: list[Path], caption: str, chat_id: str, pilar: str = ""):
        """
        Convierte los slides de imágenes a un Reel MP4 con música y publica en Instagram.
        Los slides son imágenes estáticas — la API no permite música en carruseles estáticos.
        Si la conversión falla, publica como carrusel estático (sin música).
        """
        from agente.instagram.publicar_item import _carrusel_slides_a_reel_cloudinary, _publicar_video_como_reel

        _enviar_mensaje(f"🎵 Convirtiendo {len(rutas)} slides a Reel con música...")

        url_video = _carrusel_slides_a_reel_cloudinary(rutas, pilar)
        if url_video:
            media_id = _publicar_video_como_reel(url_video, caption)
            if media_id:
                _enviar_mensaje(
                    f"📖 <b>Carrusel publicado como Reel con música</b>\n"
                    f"<a href='https://www.instagram.com/salsas.bestial/'>Ver en @salsas.bestial →</a>"
                )
                return
            _enviar_mensaje("⚠️ Reel generado pero fallo al publicar — intentando carrusel estático...")

        # Fallback: carrusel estático de imágenes (sin música)
        _enviar_mensaje(f"📤 Publicando como carrusel estático ({len(rutas)} slides)...")
        subidor = SubidorCloudinary()
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
            f"✅ <b>Carrusel listo — publicalo manualmente en Instagram</b>\n\n"
            f"Los slides ya los tenés arriba en Telegram. "
            f"Descargalos y publicalos desde la app para poder agregarle música.\n\n"
            f"<b>Caption:</b>\n{caption[:600]}",
            reply_markup={"inline_keyboard": [[
                {"text": "📚 Guardar en biblioteca", "callback_data": "carrusel:biblioteca"},
                {"text": "🗑 Descartar", "callback_data": "carrusel:descartar"},
            ]]}
        )

    def _mostrar_biblioteca(self):
        """
        /biblioteca — muestra cada ítem pendiente con preview y botones:
          ✅ Ya publiqué  → marcar_publicado → desaparece de la biblioteca
          🗑 Descartar    → marcar_descartado → desaparece de la biblioteca
        """
        try:
            self._mostrar_biblioteca_impl()
        except Exception as e:
            logger.error("Error en _mostrar_biblioteca: %s", e, exc_info=True)
            _enviar_mensaje(f"⚠️ Error mostrando biblioteca: <code>{_html.escape(str(e))}</code>")

    def _mostrar_biblioteca_impl(self):
        from datetime import datetime

        EMOJI = {"post": "📸", "reel": "🎬", "story": "⭕", "carrusel": "📖"}
        PILAR_CORTO = {
            "recetas_y_maridajes": "Recetas",
            "lifestyle_y_comunidad": "Lifestyle",
            "humor_picante": "Humor 🌶",
            "educacion_sobre_salsas": "Educación",
            "behind_the_scenes": "BTS",
            "promociones_y_lanzamientos": "Promo",
            "testimonios_y_ugc": "Testimonios",
            "como_comprar": "Cómo comprar",
        }

        todos = []
        for tipo in ["reel", "post", "story"]:
            todos.extend(listar_pendientes(tipo))
        # Carruseles están guardados como tipo=post con es_carrusel=True — ya incluidos
        # Ordenar por fecha agregado (más reciente primero)
        todos.sort(key=lambda i: i.fecha_agregado, reverse=True)

        if not todos:
            _enviar_mensaje("📚 <b>Biblioteca vacía</b>\n\nNo hay material pendiente. Envíame fotos o videos.")
            return

        conteo = contar_pendientes()
        _enviar_mensaje(
            f"📚 <b>Biblioteca — {len(todos)} ítems pendientes</b>\n"
            f"📸 {conteo['post']} posts · 🎬 {conteo['reel']} reels · ⭕ {conteo['story']} stories · 📖 {conteo['carrusel']} carruseles\n\n"
            f"<i>Presiona ✅ si ya lo publicaste manualmente o 🗑 para descartarlo.</i>"
        )
        time.sleep(0.3)

        for it in todos:
            tipo_disp = "carrusel" if it.es_carrusel else it.tipo
            emoji = EMOJI.get(tipo_disp, "📌")
            pilar = PILAR_CORTO.get(it.pilar or "", (it.pilar or "").replace("_", " ").title())
            fecha = datetime.fromtimestamp(it.fecha_agregado).strftime("%d/%m %H:%M")

            # Caption del ítem
            primera = ""
            if it.caption:
                primera = str(it.caption).split("\n")[0].strip()[:120]
            caption_item = (
                f"{emoji} <b>{tipo_disp.upper()}</b>  •  {_html.escape(pilar)}\n"
                f"📅 {fecha}\n"
            )
            if primera:
                caption_item += f"🪝 <i>{_html.escape(primera)}</i>"

            # Botones
            teclado = {"inline_keyboard": [[
                {"text": "✅ Ya lo publiqué", "callback_data": f"bib:publicado:{it.id}"},
                {"text": "🗑 Descartar",      "callback_data": f"bib:descartar:{it.id}"},
            ]]}

            # Enviar media + botones
            enviado = False
            if it.ruta_local:
                ruta_l = Path(it.ruta_local)
                if ruta_l.exists() and ruta_l.is_file():
                    if ruta_l.suffix.lower() in (".mp4", ".mov", ".m4v"):
                        r = _enviar_video(ruta_l, caption=caption_item, reply_markup=teclado)
                    else:
                        r = _enviar_foto(ruta_l, caption=caption_item, reply_markup=teclado)
                    enviado = r.get("ok", False) if isinstance(r, dict) else bool(r)

            if not enviado and it.cloudinary_url:
                url1 = _primera_url(it.cloudinary_url)
                if url1:
                    if _es_video_url(url1):
                        r = _enviar_video_url(url1, caption=caption_item, reply_markup=teclado)
                    else:
                        r = _enviar_foto_url(url1, caption=caption_item, reply_markup=teclado)
                    enviado = r.get("ok", False) if isinstance(r, dict) else bool(r)

            if not enviado:
                # Sin media — solo texto con botones
                _enviar_mensaje(caption_item, reply_markup=teclado)

            time.sleep(0.4)

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
        """
        Muestra el plan completo de hoy: entradas del calendario + biblioteca.
        Para cada entrada muestra: hora, tipo, hook del copy, concepto y estado del material.
        """
        try:
            self._mostrar_plan_hoy_impl()
        except Exception as e:
            logger.error("Error en _mostrar_plan_hoy: %s", e, exc_info=True)
            _enviar_mensaje(f"⚠️ Error mostrando el plan de hoy: <code>{_html.escape(str(e))}</code>")

    def _mostrar_plan_hoy_impl(self):
        """Implementación real de /hoy — muestra solo los slots programados para hoy."""
        import datetime
        try:
            from zoneinfo import ZoneInfo
            tz_col = ZoneInfo("America/Bogota")
            ahora = datetime.datetime.now(tz_col)
        except Exception:
            ahora = datetime.datetime.utcnow() - datetime.timedelta(hours=5)

        dia_semana = ahora.weekday()
        DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

        def esc(t):
            return _html.escape(str(t)) if t else ""

        EMOJI = {"post": "📸", "reel": "🎬", "story": "⭕", "carrusel": "📖"}
        PILAR_EMOJI = {
            "humor_picante": "😄",
            "retos_y_pruebas_de_picante": "🔥",
            "recetas_y_maridajes": "🍽",
            "lifestyle_y_comunidad": "✨",
            "educacion_sobre_salsas": "📚",
            "behind_the_scenes": "🎥",
            "promociones_y_lanzamientos": "🚀",
            "como_comprar": "🛒",
            "testimonios_y_ugc": "⭐",
            "beneficios_del_producto": "💪",
        }

        # Mismo HORARIO que main.py publicar_programado
        HORARIO = {
            (0, 10, 16): "post",    (0, 17, 23): "reel",
            (1, 10, 16): "post",    (1, 17, 23): "reel",
            (2, 10, 16): "post",    (2, 17, 23): "story",
            (3, 10, 16): "reel",    (3, 17, 23): "story",
            (4, 10, 16): "post",    (4, 17, 23): "reel",
            (5, 10, 16): "post",    (5, 17, 23): "story",
            (6, 10, 16): "story",   (6, 17, 23): "story",
        }
        HORA_LABEL = {10: "12:00pm", 17: "7:00pm"}

        # Leer pausas y aprobaciones del día
        pausas = self._leer_pausas_hoy()
        aprobaciones = self._leer_aprobaciones_hoy()
        fecha_hoy_str = ahora.strftime("%Y-%m-%d")
        pausado_todo = pausas.get("pausado_todo", False) and pausas.get("fecha") == fecha_hoy_str
        slots_pausados = set(pausas.get("slots_pausados", [])) if pausas.get("fecha") == fecha_hoy_str else set()
        # aprobados: dict slot_key → item_id (solo si es de hoy)
        aprobados = aprobaciones.get("aprobados", {}) if aprobaciones.get("fecha") == fecha_hoy_str else {}

        # Slots de hoy: mediodía (h_min=10) y noche (h_min=17)
        slots_hoy = []
        for (dia, h_min, h_max), tipo in HORARIO.items():
            if dia == dia_semana:
                slots_hoy.append((h_min, h_max, tipo))
        slots_hoy.sort(key=lambda x: x[0])

        lineas = [f"🗓 <b>{DIAS[dia_semana]} {ahora.strftime('%d/%m')} — Plan del día</b>\n"]

        if pausado_todo:
            lineas.append("🚫 <b>Publicaciones pausadas para hoy</b>\n")

        teclado = []
        items_con_media = []  # (item, label_slot) — para enviar preview después

        for h_min, h_max, tipo in slots_hoy:
            hora_label = HORA_LABEL.get(h_min, f"{h_min}:00")
            emoji = EMOJI.get(tipo, "📌")
            slot_key = str(h_min)
            ya_paso = ahora.hour >= h_max

            # Buscar el ítem que se publicará en este slot
            tipos_buscar = [tipo]
            if tipo == "carrusel":
                tipos_buscar.append("post")
            # fallback: si no hay del tipo preferido, buscar cualquier pendiente
            item_slot = None
            for t in tipos_buscar:
                item_slot = siguiente_pendiente(t)
                if item_slot:
                    break
            if not item_slot:
                for t in ["reel", "post", "story"]:
                    if t not in tipos_buscar:
                        item_slot = siguiente_pendiente(t)
                        if item_slot:
                            break

            # ¿Está aprobado este slot?
            item_aprobado_id = aprobados.get(slot_key)
            slot_aprobado = bool(item_aprobado_id) and item_slot and item_aprobado_id == item_slot.id

            # Estado del slot
            if ya_paso:
                estado_str = "✔️ <i>Slot pasado</i>"
            elif pausado_todo or slot_key in slots_pausados:
                estado_str = "⏸ <i>Pausado</i>"
            elif slot_aprobado:
                estado_str = "✅ <b>Aprobado — se publica automáticamente</b>"
            else:
                estado_str = "🟡 <i>Pendiente aprobación</i>"

            if item_slot:
                tiene_media = "☁️ Cloudinary" if item_slot.cloudinary_url else ("📁 Local" if item_slot.ruta_local else "⚠️ Sin media")
                pilar_raw = (item_slot.pilar or "").replace("_", " ").title()
                pilar_e = PILAR_EMOJI.get(item_slot.pilar or "", "🌶") + " " + esc(pilar_raw)
                primera_linea = ""
                if item_slot.caption:
                    primera_linea = str(item_slot.caption).split("\n")[0].strip()[:120]

                lineas.append(
                    f"\n{emoji} <b>{hora_label} — {tipo.upper()}</b>  {estado_str}\n"
                    f"   {pilar_e}  •  {tiene_media}"
                )
                if primera_linea:
                    lineas.append(f"   🪝 <i>{esc(primera_linea)}</i>")

                if not ya_paso:
                    items_con_media.append((item_slot, f"{hora_label} — {tipo.upper()}"))
            else:
                lineas.append(
                    f"\n{emoji} <b>{hora_label} — {tipo.upper()}</b>  {estado_str}\n"
                    f"   ⚠️ <i>Sin material en biblioteca — envía algo al bot</i>"
                )

            # Botones por slot (solo slots futuros no pausados)
            if not ya_paso and not pausado_todo and slot_key not in slots_pausados:
                # Fila 1: Aprobar / Ya aprobado
                if item_slot:
                    if slot_aprobado:
                        teclado.append([{"text": f"✅ Aprobado {hora_label} ✓", "callback_data": f"hoy:noop"}])
                    else:
                        teclado.append([{"text": f"📅 Aprobar para {hora_label}", "callback_data": f"hoy:aprobar:{slot_key}:{item_slot.id}"}])
                # Fila 2: Ya publiqué / Saltar
                fila2 = []
                if item_slot:
                    fila2.append({"text": f"✅ Ya publiqué", "callback_data": f"hoy:ya_publique:{item_slot.id}:{slot_key}:{tipo}"})
                fila2.append({"text": f"⏭ Saltar", "callback_data": f"hoy:pausar_slot:{slot_key}"})
                teclado.append(fila2)
            elif not ya_paso and not pausado_todo and slot_key in slots_pausados:
                teclado.append([{"text": f"🔄 Reactivar {hora_label}", "callback_data": f"hoy:activar_slot:{slot_key}"}])

        lineas.append(f"\n<i>Hora actual: {ahora.strftime('%H:%M')} COL</i>")

        # Botón pausar/activar todo
        if not pausado_todo:
            teclado.append([{"text": "🚫 No publicar nada hoy", "callback_data": "hoy:pausar_todo"}])
        else:
            teclado.append([{"text": "✅ Reactivar todo hoy", "callback_data": "hoy:activar_todo"}])

        resp = _enviar_mensaje("\n".join(lineas), reply_markup={"inline_keyboard": teclado})
        if not resp.get("ok"):
            texto_plain = re.sub(r"<[^>]+>", "", "\n".join(lineas))
            _enviar_mensaje(texto_plain, reply_markup={"inline_keyboard": teclado})

        # ── Enviar preview del material de cada slot ──────────────────────────
        for item_slot, label_slot in items_con_media:
            try:
                caption_prev = (
                    f"{EMOJI.get(item_slot.tipo,'📌')} <b>{esc(label_slot)}</b>\n"
                )
                primera = ""
                if item_slot.caption:
                    primera = str(item_slot.caption).split("\n")[0].strip()[:200]
                if primera:
                    caption_prev += f"🪝 {esc(primera)}"

                enviado = False
                if item_slot.ruta_local:
                    ruta_l = Path(item_slot.ruta_local)
                    if ruta_l.exists():
                        if ruta_l.suffix.lower() in (".mp4", ".mov", ".m4v"):
                            _enviar_video(ruta_l, caption=caption_prev)
                        else:
                            _enviar_foto(ruta_l, caption=caption_prev)
                        enviado = True
                if not enviado and item_slot.cloudinary_url:
                    _enviar_media_url(item_slot.cloudinary_url, caption=caption_prev)
                time.sleep(0.4)
            except Exception as err:
                logger.warning("Error enviando preview slot %s: %s", label_slot, err)

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

    def _enviar_preview_biblioteca(self, item, rev_id: str, nota: str = ""):
        """
        Envía preview de un item de biblioteca con botones de acción completos.
        Separa la imagen/video del texto para evitar la limitación de 1024 chars
        en captions de Telegram y evitar truncación de HTML.
        """
        pilar_label = _html.escape((item.pilar or "").replace("_", " ").title())
        tipo_label = {
            "post": "📸 POST", "reel": "🎬 REEL",
            "story": "⭕ STORY", "carrusel": "📖 CARRUSEL",
        }.get(item.tipo, item.tipo.upper())

        # 1. Enviar foto/video como preview visual (caption corto, sin botones)
        cloudinary_url = getattr(item, "cloudinary_url", "") or ""
        ruta_local = getattr(item, "ruta_local", "") or ""
        nombre = item.nombre_archivo.lower()
        es_video_item = any(nombre.endswith(e) for e in (".mp4", ".mov", ".avi", ".m4v"))
        caption_corto = f"{tipo_label} — {pilar_label}"
        if nota:
            caption_corto += f"\n{_html.escape(nota)}"

        enviado_media = False
        # Intentar desde archivo local primero (más confiable en GitHub Actions)
        if ruta_local:
            try:
                ruta_p = Path(ruta_local)
                if ruta_p.exists():
                    if es_video_item:
                        r = _enviar_video(ruta_p, caption=caption_corto)
                    else:
                        r = _enviar_foto(ruta_p, caption=caption_corto)
                    enviado_media = r.get("ok", False)
            except Exception as e:
                logger.warning("Error enviando media local: %s", e)
        # Fallback: Cloudinary URL (usa _primera_url para manejar carruseles multi-URL)
        if not enviado_media and cloudinary_url:
            try:
                r = _enviar_media_url(cloudinary_url, caption=caption_corto)
                enviado_media = r.get("ok", False)
            except Exception as e:
                logger.warning("Error enviando media por URL: %s", e)

        # 2. Enviar texto completo con caption y botones (sin límite de 1024)
        botones = {"inline_keyboard": [
            [
                {"text": "✅ Publicar",        "callback_data": f"pub_aprobar:{rev_id}"},
                {"text": "✍️ Corregir",        "callback_data": f"pub_corregir:{rev_id}"},
                {"text": "⏭ Saltar",           "callback_data": f"pub_skip:{rev_id}"},
            ],
            [{"text": "✅ Ya lo publiqué",     "callback_data": f"pub_publicado:{rev_id}"}],
        ]}
        try:
            caption_preview = _html.escape(item.caption[:900]) if item.caption else "<i>Sin caption — se generará al publicar</i>"
            texto = (
                f"🗓 <b>{tipo_label}</b> — 🌶 {pilar_label}\n"
                + (f"📝 <i>{_html.escape(nota)}</i>\n" if nota else "")
                + f"👆 Toca ✅ para publicar ahora\n\n"
                + caption_preview
                + "\n\n<i>¿Qué hacemos con este contenido?</i>"
            )
            _enviar_mensaje(texto, reply_markup=botones)
        except Exception as e:
            logger.error("Error enviando preview con botones: %s", e)
            # Fallback sin HTML por si el caption tiene caracteres problemáticos
            _enviar_mensaje("Contenido listo. ¿Qué hacemos?", reply_markup=botones)

    def _flujo_publicar_ahora(self, tipo_forzado: str | None = None):
        """
        /publicar — dispara el flujo de preview+aprobación+publicación desde Telegram.
        Funciona a cualquier hora, independiente del cron de GitHub Actions.
        """
        try:
            self._flujo_publicar_ahora_impl(tipo_forzado)
        except Exception as e:
            logger.error("Error en _flujo_publicar_ahora: %s", e, exc_info=True)
            _enviar_mensaje(
                f"❌ <b>Error al ejecutar /publicar</b>\n\n"
                f"<code>{_html.escape(str(e))}</code>\n\n"
                "Reintenta con /publicar"
            )

    def _flujo_publicar_ahora_impl(self, tipo_forzado: str | None = None):
        """
        Implementación interna de /publicar.

        Orden de prioridad para elegir el tipo:
          1. Tipo explícito del usuario (/publicar reel)
          2. Tipo que corresponde al calendario de hoy
          3. Orden por defecto: reel → post → story
        """
        tipos_validos = {"reel", "post", "story", "carrusel"}

        if not tipo_forzado:
            # Detectar el tipo que corresponde hoy según el calendario semanal
            try:
                import datetime
                from agente.memoria.gestor_memoria import cargar_calendario
                try:
                    from zoneinfo import ZoneInfo
                    hoy = datetime.datetime.now(ZoneInfo("America/Bogota")).date()
                except Exception:
                    hoy = datetime.date.today()
                cal = cargar_calendario()
                if cal:
                    entradas_pendientes = [
                        e for e in cal.entradas
                        if e.estado not in ("publicado", "rechazado")
                        and str(getattr(e, "fecha", "")) == str(hoy)
                    ]
                    entradas_pendientes.sort(key=lambda e: e.hora_publicacion or "00:00")
                    for e in entradas_pendientes:
                        tipo_cal = getattr(e, "tipo_contenido", "") or ""
                        if tipo_cal in tipos_validos:
                            tipo_forzado = tipo_cal
                            break
            except Exception as err:
                logger.warning("No se pudo leer el calendario para detectar tipo: %s", err)

        # Construir lista de tipos con fallback completo.
        # "carrusel" en el calendario → buscar también en "post" (los carruseles se
        # almacenan en biblioteca con tipo="post" y es_carrusel=True).
        _FALLBACK = ["reel", "post", "story"]
        if tipo_forzado in tipos_validos:
            tipos_a_probar = [tipo_forzado]
            if tipo_forzado == "carrusel":
                tipos_a_probar.append("post")   # sinónimo de carrusel en biblioteca
            # Agregar fallback para no mostrar "vacía" si el tipo forzado no tiene items
            for t in _FALLBACK:
                if t not in tipos_a_probar:
                    tipos_a_probar.append(t)
        else:
            tipos_a_probar = _FALLBACK

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
            _enviar_mensaje("✍️ Generando caption con Claude...")
            try:
                item.caption = _generar_caption(
                    tipo_encontrado,
                    getattr(item, "pilar", "recetas_y_maridajes") or "recetas_y_maridajes",
                )
            except Exception as e:
                logger.error("Error generando caption: %s", e)
                _enviar_mensaje(
                    f"⚠️ No se pudo generar el caption: <code>{_html.escape(str(e))}</code>\n"
                    "Publicando sin caption — podrás corregirlo después."
                )
                item.caption = ""

        rev_id = f"bot_{int(time.time())}"
        self._pending_pubs[rev_id] = item
        self._guardar_pending_pubs()
        self._enviar_preview_biblioteca(item, rev_id)

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

    def _mostrar_comandos(self):
        """Muestra todos los comandos disponibles con botones para ejecutarlos."""
        from agente.gestores.biblioteca import contar_pendientes
        conteo = contar_pendientes()
        total = sum(conteo.values())

        _enviar_mensaje(
            "🤖 <b>Comandos disponibles</b>\n\n"

            "━━━━━━━━━━━━━━━━\n"
            "📅 <b>/hoy</b>\n"
            "Plan de hoy: qué se publica, a qué hora y con qué material.\n\n"

            "🚀 <b>/publicar</b>\n"
            "Muestra el siguiente item pendiente con botones para publicar, corregir o saltar.\n"
            f"   Cola actual: {conteo['reel']} reels · {conteo['post']} posts · {conteo['story']} stories\n\n"

            "📚 <b>/estado</b>\n"
            f"Lista completa de los {total} items en biblioteca con preview visual.\n\n"

            "🎨 <b>/carrusel &lt;tema&gt;</b>\n"
            "Claude genera un carrusel educativo con datos curiosos sobre el tema.\n"
            "   <i>Ej: /carrusel historia del chile habanero</i>\n\n"

            "💰 <b>/venta</b>\n"
            "Genera 3 stories de conversión: enganche → prueba social → CTA de compra.\n\n"

            "━━━━━━━━━━━━━━━━\n"
            "📸 <b>Enviar foto</b> → el bot pregunta si guardar o publicar ahora\n"
            "🎬 <b>Enviar video</b> → el bot pregunta el tipo (Reel / Story)\n"
            "📖 <b>Varias fotos juntas</b> → opción de publicar como carrusel",

            reply_markup={"inline_keyboard": [
                [{"text": "📅 Ver plan de hoy",          "callback_data": "cmd:hoy"}],
                [{"text": "🚀 Ver siguiente pendiente",   "callback_data": "cmd:publicar"}],
                [{"text": "📚 Ver biblioteca completa",   "callback_data": "cmd:estado"}],
            ]},
        )

    def _mostrar_ayuda(self):
        _enviar_mensaje(
            "🤖 <b>Agente Salsas Bestial — Comandos</b>\n\n"

            "━━ 📥 ENVIAR MATERIAL ━━\n"
            "📸 <b>Foto</b> → te pregunto si guardar en biblioteca o publicar ahora\n"
            "🎬 <b>Video</b> → te pregunto si es Reel o Story\n"
            "📖 <b>Varias fotos juntas</b> → te ofrezco publicar como carrusel\n\n"

            "━━ 🚀 PUBLICAR ━━\n"
            "<code>/publicar</code> — preview del siguiente pendiente + botón ✅ para publicar\n"
            "<code>/publicar reel</code> — fuerza tipo Reel\n"
            "<code>/publicar post</code> — fuerza tipo Post\n"
            "<code>/publicar story</code> — fuerza tipo Story\n"
            "<code>/publicar carrusel</code> — fuerza tipo Carrusel\n\n"

            "━━ 📊 ESTADO Y PLAN ━━\n"
            "<code>/hoy</code> — plan de publicación de hoy: qué hay en la biblioteca, a qué hora sale, botones para pausar/activar slots\n"
            "<code>/estado</code> — lista completa del material en biblioteca con preview visual\n\n"

            "━━ 🎨 GENERAR CONTENIDO ━━\n"
            "<code>/carrusel &lt;tema&gt;</code> — Claude genera carrusel educativo + preview de slides\n"
            "   <i>Ejemplo: /carrusel beneficios del picante</i>\n"
            "<code>/venta</code> — Claude genera serie de 3 stories de conversión (enganche → prueba → CTA)\n\n"

            "━━ ⏭ DURANTE UNA APROBACIÓN ━━\n"
            "Al tocar <b>⏭ Saltar</b> → opciones: Corregir caption / Ya lo publiqué / Pasar al siguiente\n"
            "Al corregir: escribe la instrucción (ej: 'acortalo', 'tono más casual') → Claude lo reescribe\n"
            "Al rechazar un caption → escribe qué cambiar y Claude lo reescribe\n"
            "Escribe <code>saltar</code> para descartar sin cambiar\n\n"

            "━━ ⏰ HORARIO AUTOMÁTICO ━━\n"
            "Preview llega ~11:30am y ~6:30pm COL (GitHub Actions)\n"
            "Ventanas de publicación: <b>10am–4pm</b> y <b>5pm–11pm</b> COL\n\n"

            "⚡ <b>¿No llegó el preview automático?</b>\n"
            "Escribe <code>/publicar</code> — funciona a cualquier hora"
        )
