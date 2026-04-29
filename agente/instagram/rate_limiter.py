"""
Control de rate limits para Instagram Graph API.
Meta permite 200 llamadas/hora por token. Límites seguros del agente: ver config/settings.py.
"""

import time
import logging
from collections import deque
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Ventana deslizante de 1 hora para contar llamadas a la API
_VENTANA_SEGUNDOS = 3600
_MAX_LLAMADAS_HORA = 180  # Dejamos 20 de margen sobre el límite de 200

_historial_llamadas: deque = deque()


def _limpiar_antiguas():
    """Elimina del historial las llamadas fuera de la ventana de 1 hora."""
    corte = time.monotonic() - _VENTANA_SEGUNDOS
    while _historial_llamadas and _historial_llamadas[0] < corte:
        _historial_llamadas.popleft()


def registrar_llamada():
    """Registra una llamada a la API. Llama esto justo antes de cada request."""
    _limpiar_antiguas()
    _historial_llamadas.append(time.monotonic())


def llamadas_en_ventana() -> int:
    _limpiar_antiguas()
    return len(_historial_llamadas)


def esperar_si_necesario():
    """
    Bloquea si se está cerca del límite horario.
    Se debe llamar antes de cada request a la API.
    """
    _limpiar_antiguas()
    if len(_historial_llamadas) >= _MAX_LLAMADAS_HORA:
        # Esperar hasta que la llamada más antigua salga de la ventana
        espera = _VENTANA_SEGUNDOS - (time.monotonic() - _historial_llamadas[0]) + 1
        if espera > 0:
            logger.warning(
                "Rate limit alcanzado (%d llamadas). Esperando %.0fs.",
                len(_historial_llamadas), espera,
            )
            time.sleep(espera)
        _limpiar_antiguas()
    registrar_llamada()
