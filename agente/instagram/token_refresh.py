"""
Verifica y renueva el token de Instagram de larga duración.
Los tokens de usuario expiran en 60 días. Este módulo alerta 7 días antes.
"""

import logging
from datetime import datetime, timedelta

import requests

from config import settings

logger = logging.getLogger(__name__)

# Instagram Graph API — verificar token
DEBUG_TOKEN_URL = "https://graph.facebook.com/debug_token"
REFRESH_TOKEN_URL = "https://graph.instagram.com/refresh_access_token"


def verificar_token() -> dict:
    """
    Consulta la fecha de expiración del token actual.
    Retorna dict con: valido, expira_en_dias, expira_timestamp.
    """
    if not settings.INSTAGRAM_ACCESS_TOKEN or not settings.FACEBOOK_APP_ID or not settings.FACEBOOK_APP_SECRET:
        return {"valido": False, "expira_en_dias": 0, "mensaje": "Credenciales faltantes"}

    try:
        resp = requests.get(
            DEBUG_TOKEN_URL,
            params={
                "input_token": settings.INSTAGRAM_ACCESS_TOKEN,
                "access_token": f"{settings.FACEBOOK_APP_ID}|{settings.FACEBOOK_APP_SECRET}",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})

        valido = data.get("is_valid", False)
        expira_ts = data.get("expires_at", 0)

        if not valido:
            return {"valido": False, "expira_en_dias": 0, "mensaje": "Token inválido o revocado"}

        if expira_ts == 0:
            # Token sin expiración (tokens de sistema de aplicación)
            return {"valido": True, "expira_en_dias": 999, "mensaje": "Token sin expiración"}

        expira = datetime.fromtimestamp(expira_ts)
        dias_restantes = (expira - datetime.now()).days

        return {
            "valido": True,
            "expira_en_dias": dias_restantes,
            "expira_fecha": expira.strftime("%Y-%m-%d"),
            "mensaje": f"Token válido por {dias_restantes} días más",
        }

    except Exception as e:
        logger.error("Error verificando token: %s", e)
        return {"valido": False, "expira_en_dias": 0, "mensaje": str(e)}


def renovar_token() -> str | None:
    """
    Intenta renovar el token de larga duración.
    Retorna el nuevo token o None si falla.
    Los Long-Lived Tokens se pueden renovar si aún son válidos.
    """
    try:
        resp = requests.get(
            REFRESH_TOKEN_URL,
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.FACEBOOK_APP_ID,
                "client_secret": settings.FACEBOOK_APP_SECRET,
                "fb_exchange_token": settings.INSTAGRAM_ACCESS_TOKEN,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        nuevo_token = data.get("access_token")
        if nuevo_token:
            logger.info("Token renovado exitosamente. Expira en ~60 días.")
            return nuevo_token
        return None
    except Exception as e:
        logger.error("Error renovando token: %s", e)
        return None


def verificar_y_alertar() -> bool:
    """
    Verifica el token y retorna False (bloqueando la publicación) si está expirado.
    Genera alertas cuando quedan ≤ 7 días.
    """
    estado = verificar_token()

    if not estado["valido"]:
        logger.error("TOKEN INSTAGRAM INVÁLIDO: %s. Publicación bloqueada.", estado["mensaje"])
        return False

    dias = estado.get("expira_en_dias", 999)

    if dias <= 0:
        logger.error("TOKEN INSTAGRAM EXPIRADO. Renovar en Meta for Developers.")
        return False

    if dias <= 7:
        logger.warning(
            "⚠️  TOKEN INSTAGRAM expira en %d días (%s). Renovar URGENTE en Meta for Developers.",
            dias, estado.get("expira_fecha", ""),
        )

    elif dias <= 14:
        logger.info("Token Instagram válido. Expira en %d días.", dias)

    return True
