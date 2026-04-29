"""
Notificaciones y aprobaciones via Telegram.
El agente envía cada pieza de contenido con botones ✅ Aprobar / ❌ Rechazar.
El usuario responde desde el celular y el agente actualiza el calendario automáticamente.
"""

import logging
import time
from pathlib import Path
from typing import Optional

import requests

from config import settings
from agente.memoria import gestor_memoria as memoria

logger = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


def _enviar_mensaje(texto: str, reply_markup: dict = None) -> dict:
    """Envía un mensaje de texto al chat configurado."""
    data = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "HTML",
    }
    if reply_markup:
        import json
        data["reply_markup"] = json.dumps(reply_markup)

    resp = requests.post(f"{BASE_URL}/sendMessage", data=data, timeout=15)
    return resp.json()


def _enviar_foto(ruta: Path, caption: str = "", reply_markup: dict = None) -> dict:
    """Envía una imagen al chat."""
    data = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "caption": caption[:1024],
        "parse_mode": "HTML",
    }
    if reply_markup:
        import json
        data["reply_markup"] = json.dumps(reply_markup)

    with open(ruta, "rb") as f:
        resp = requests.post(f"{BASE_URL}/sendPhoto", data=data, files={"photo": f}, timeout=30)
    return resp.json()


def _enviar_video(ruta: Path, caption: str = "", reply_markup: dict = None) -> dict:
    """Envía un video al chat."""
    data = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "caption": caption[:1024],
        "parse_mode": "HTML",
    }
    if reply_markup:
        import json
        data["reply_markup"] = json.dumps(reply_markup)

    with open(ruta, "rb") as f:
        resp = requests.post(f"{BASE_URL}/sendVideo", data=data, files={"video": f}, timeout=60)
    return resp.json()


def _botones_aprobacion(entrada_id: str) -> dict:
    """Genera los botones inline de aprobar/rechazar."""
    return {
        "inline_keyboard": [[
            {"text": "✅ Aprobar", "callback_data": f"aprobar:{entrada_id}"},
            {"text": "❌ Rechazar", "callback_data": f"rechazar:{entrada_id}"},
        ]]
    }


def notificar_entrada(entrada) -> bool:
    """
    Envía una pieza del calendario a Telegram para aprobación.
    Incluye la imagen/video si está disponible, el copy completo y los botones.
    """
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.warning("Telegram no configurado — saltando notificación")
        return False

    copy = entrada.contenido_copy
    tipo = entrada.tipo_contenido.upper()
    dia = entrada.dia.capitalize()
    hora = entrada.hora_publicacion

    # Construir el mensaje
    texto = f"📅 <b>{tipo} — {dia} {hora}</b>\n"
    texto += f"🎯 Pilar: {entrada.pilar.replace('_', ' ').title()}\n"
    texto += f"📌 Concepto: {entrada.concepto[:200]}\n\n"

    if copy:
        texto += f"🪝 <b>Hook:</b>\n{copy.hook}\n\n"
        texto += f"📝 <b>Copy:</b>\n{copy.cuerpo[:500]}\n\n"
        texto += f"👉 <b>CTA:</b> {copy.cta}\n\n"
        if copy.hashtags:
            texto += "🏷️ " + " ".join(copy.hashtags[:10])

    botones = _botones_aprobacion(entrada.id)

    try:
        # Intentar enviar con imagen si existe
        imagen_path = None
        if entrada.imagen_compuesta_path:
            p = Path(entrada.imagen_compuesta_path)
            if p.exists():
                imagen_path = p

        video_path = None
        if entrada.video_generado_path:
            p = Path(entrada.video_generado_path)
            if p.exists():
                video_path = p

        if video_path:
            result = _enviar_video(video_path, caption=texto, reply_markup=botones)
        elif imagen_path:
            result = _enviar_foto(imagen_path, caption=texto, reply_markup=botones)
        else:
            # Sin media — enviar solo texto
            texto += f"\n\n<i>⚠️ Material visual pendiente de generación</i>"
            result = _enviar_mensaje(texto, reply_markup=botones)

        if result.get("ok"):
            logger.info("Notificación Telegram enviada: %s %s", tipo, entrada.id)
            return True
        else:
            logger.error("Error Telegram: %s", result)
            return False

    except Exception as e:
        logger.error("Error enviando notificación Telegram: %s", e)
        return False


def notificar_calendario_completo(calendario) -> int:
    """Envía todas las entradas del calendario para aprobación. Retorna cuántas se enviaron."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.warning("Telegram no configurado")
        return 0

    # Mensaje introductorio
    total = len(calendario.entradas)
    _enviar_mensaje(
        f"🚀 <b>Semana {calendario.semana} lista para revisión</b>\n\n"
        f"📊 {total} piezas generadas\n"
        f"👇 Aprueba o rechaza cada una:\n\n"
        f"<i>Tip: puedes aprobar todas y luego rechazar las que no te gusten</i>"
    )
    time.sleep(1)

    enviadas = 0
    for entrada in calendario.entradas:
        if notificar_entrada(entrada):
            enviadas += 1
        time.sleep(0.5)  # Evitar flood de Telegram

    _enviar_mensaje(
        f"✅ <b>Revisión completa</b>\n"
        f"Aprobaste/rechazaste las {enviadas} piezas.\n\n"
        f"Cuando termines, el agente publicará automáticamente las aprobadas en los horarios del calendario."
    )

    return enviadas


def procesar_aprobaciones() -> dict:
    """
    Lee las respuestas de los botones (callback queries) y actualiza el calendario.
    Retorna: {"aprobados": n, "rechazados": n}
    """
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return {"aprobados": 0, "rechazados": 0}

    resp = requests.get(f"{BASE_URL}/getUpdates", params={"timeout": 0}, timeout=10)
    data = resp.json()

    aprobados = 0
    rechazados = 0
    ultimo_update_id = None

    for update in data.get("result", []):
        ultimo_update_id = update["update_id"]
        callback = update.get("callback_query")
        if not callback:
            continue

        callback_data = callback.get("data", "")
        if ":" not in callback_data:
            continue

        accion, entrada_id = callback_data.split(":", 1)
        nuevo_estado = "aprobado" if accion == "aprobar" else "rechazado"

        if memoria.actualizar_estado_entrada(entrada_id, nuevo_estado):
            if nuevo_estado == "aprobado":
                aprobados += 1
                emoji = "✅"
            else:
                rechazados += 1
                emoji = "❌"

            # Confirmar al usuario
            requests.post(f"{BASE_URL}/answerCallbackQuery", data={
                "callback_query_id": callback["id"],
                "text": f"{emoji} {nuevo_estado.capitalize()}",
            }, timeout=10)

            logger.info("Entrada %s marcada como %s via Telegram", entrada_id, nuevo_estado)

    # Marcar updates como procesados
    if ultimo_update_id:
        requests.get(f"{BASE_URL}/getUpdates", params={"offset": ultimo_update_id + 1}, timeout=10)

    return {"aprobados": aprobados, "rechazados": rechazados}


def enviar_notificacion_publicacion(tipo: str, concepto: str, media_id: str):
    """Notifica cuando una pieza se publica exitosamente en Instagram."""
    _enviar_mensaje(
        f"📸 <b>Publicado en Instagram</b>\n\n"
        f"Tipo: {tipo.upper()}\n"
        f"Concepto: {concepto[:100]}\n"
        f"Media ID: {media_id}\n\n"
        f"<a href='https://www.instagram.com/salsas.bestial/'>Ver en Instagram →</a>"
    )


def enviar_alerta(mensaje: str):
    """Envía una alerta importante (token expirando, error crítico, etc.)."""
    _enviar_mensaje(f"⚠️ <b>ALERTA</b>\n\n{mensaje}")
