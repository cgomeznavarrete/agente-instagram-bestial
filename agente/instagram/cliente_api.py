"""
Wrapper de Instagram Graph API v21.0.
Todos los requests pasan por aquí — nunca llamar requests directamente desde otros módulos.
"""

import logging
import time
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings
from agente.instagram import rate_limiter

logger = logging.getLogger(__name__)

BASE_URL = "https://graph.facebook.com/v21.0"


class ErrorInstagram(Exception):
    """Error de la Instagram Graph API con código y mensaje original."""
    def __init__(self, codigo: int, mensaje: str, subtipo: str = ""):
        self.codigo = codigo
        self.subtipo = subtipo
        super().__init__(f"Instagram API error {codigo}: {mensaje}")


def _es_error_reintentable(exc: Exception) -> bool:
    if isinstance(exc, ErrorInstagram):
        # Errores temporales de Meta: rate limit (4) o servidor (1, 2)
        return exc.codigo in {1, 2, 4, 17, 341}
    return isinstance(exc, (requests.Timeout, requests.ConnectionError))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
    reraise=True,
)
def _get(endpoint: str, params: dict) -> dict:
    rate_limiter.esperar_si_necesario()
    params["access_token"] = settings.INSTAGRAM_ACCESS_TOKEN
    resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
    return _procesar_respuesta(resp)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
    reraise=True,
)
def _post(endpoint: str, data: dict) -> dict:
    rate_limiter.esperar_si_necesario()
    data["access_token"] = settings.INSTAGRAM_ACCESS_TOKEN
    resp = requests.post(f"{BASE_URL}/{endpoint}", data=data, timeout=60)
    return _procesar_respuesta(resp)


def _procesar_respuesta(resp: requests.Response) -> dict:
    try:
        body = resp.json()
    except Exception:
        resp.raise_for_status()
        return {}

    if "error" in body:
        err = body["error"]
        raise ErrorInstagram(
            codigo=err.get("code", 0),
            mensaje=err.get("message", ""),
            subtipo=err.get("error_subcode", ""),
        )

    return body


# ── Métodos públicos ──────────────────────────────────────────────────────────

def crear_contenedor_imagen(image_url: str, caption: str) -> str:
    """Crea un contenedor de imagen para un Post. Retorna creation_id."""
    data = {
        "image_url": image_url,
        "caption": caption,
    }
    resp = _post(f"{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media", data)
    return resp["id"]


def crear_contenedor_video(
    video_url: str,
    caption: str,
    media_type: str,  # "REELS" o "STORIES"
    share_to_feed: bool = True,
) -> str:
    """Crea un contenedor de video para Reels o Stories. Retorna creation_id."""
    data = {
        "video_url": video_url,
        "caption": caption,
        "media_type": media_type,
    }
    if media_type == "REELS":
        data["share_to_feed"] = "true" if share_to_feed else "false"
    resp = _post(f"{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media", data)
    return resp["id"]


def crear_contenedor_carrusel_item(image_url: str) -> str:
    """Crea un contenedor de imagen para un ítem de carrusel. Retorna creation_id."""
    data = {
        "image_url": image_url,
        "is_carousel_item": "true",
    }
    resp = _post(f"{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media", data)
    return resp["id"]


def crear_contenedor_carrusel(item_ids: list[str], caption: str) -> str:
    """Crea el contenedor principal del carrusel con los ítems ya creados."""
    data = {
        "media_type": "CAROUSEL",
        "children": ",".join(item_ids),
        "caption": caption,
    }
    resp = _post(f"{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media", data)
    return resp["id"]


def esperar_video_listo(creation_id: str, max_intentos: int = 20, intervalo: int = 10) -> bool:
    """
    Espera a que el procesamiento de video en Meta termine.
    Los videos (Reels/Stories) tardan hasta 3-5 minutos.
    Retorna True si está listo, False si agotó los intentos.
    """
    for intento in range(max_intentos):
        resp = _get(creation_id, {"fields": "status_code,status"})
        status = resp.get("status_code", "")
        logger.debug("Video %s status: %s (intento %d/%d)", creation_id, status, intento + 1, max_intentos)

        if status == "FINISHED":
            return True
        if status in {"ERROR", "EXPIRED"}:
            logger.error("Video %s en estado %s — no se puede publicar", creation_id, status)
            return False

        time.sleep(intervalo)

    logger.error("Video %s no quedó listo tras %d intentos", creation_id, max_intentos)
    return False


def publicar_contenedor(creation_id: str) -> str:
    """
    Publica un contenedor ya procesado. Retorna el instagram_media_id público.
    Es el segundo paso en el flujo de 2 pasos de la Graph API.
    """
    data = {"creation_id": creation_id}
    resp = _post(f"{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish", data)
    return resp["id"]


def obtener_insights_cuenta() -> dict:
    """Descarga métricas básicas y de engagement de la cuenta."""
    # Campos básicos
    datos_basicos = _get(settings.INSTAGRAM_BUSINESS_ACCOUNT_ID, {
        "fields": "followers_count,media_count,name,username"
    })

    # Reach de los últimos 7 días
    reach_semana = 0
    try:
        r_reach = _get(f"{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/insights", {
            "metric": "reach",
            "period": "week",
        })
        for item in r_reach.get("data", []):
            valores = item.get("values", [])
            if valores:
                reach_semana = valores[-1].get("value", 0)
    except Exception as e:
        logger.warning("No se pudo obtener reach semanal: %s", e)

    # Visitas al perfil y clics al link (requieren metric_type=total_value)
    visitas_perfil = 0
    clicks_link = 0
    try:
        r_total = _get(f"{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/insights", {
            "metric": "profile_views,website_clicks",
            "period": "day",
            "metric_type": "total_value",
        })
        for item in r_total.get("data", []):
            name = item.get("name", "")
            val = item.get("values", {})
            if isinstance(val, dict):
                v = val.get("value", 0)
            elif isinstance(val, list) and val:
                v = val[-1].get("value", 0)
            else:
                v = item.get("total_value", {}).get("value", 0) if isinstance(item.get("total_value"), dict) else 0
            if name == "profile_views":
                visitas_perfil = v
            elif name == "website_clicks":
                clicks_link = v
    except Exception as e:
        logger.warning("No se pudo obtener profile_views/website_clicks: %s", e)

    return {
        **datos_basicos,
        "reach_semana": reach_semana,
        "visitas_perfil": visitas_perfil,
        "clicks_link": clicks_link,
    }


def obtener_insights_media(media_id: str, media_type: str = "IMAGE") -> dict:
    """
    Descarga métricas de una publicación específica.
    La API v21+ usa métricas distintas por tipo de media.
    Soportados para todos los tipos: reach, saved, shares, total_interactions
    """
    metrics = "reach,saved,shares,total_interactions"
    try:
        resp = _get(f"{media_id}/insights", {"metric": metrics, "period": "lifetime"})
        # Respuesta directa: cada item tiene 'value' (no 'values' array)
        result = {}
        for item in resp.get("data", []):
            result[item["name"]] = item.get("value", 0)
        return result
    except ErrorInstagram as e:
        logger.warning("No se pudieron obtener insights de %s: %s", media_id, e)
        return {}


def listar_medios_recientes(limit: int = 25) -> list[dict]:
    """Lista los medios recientes de la cuenta."""
    campos = "id,media_type,timestamp,permalink,like_count,comments_count"
    resp = _get(
        f"{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
        {"fields": campos, "limit": limit},
    )
    return resp.get("data", [])
