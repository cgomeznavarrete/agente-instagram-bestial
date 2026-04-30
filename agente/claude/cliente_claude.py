"""
Wrapper del Anthropic SDK con prompt caching, retry automático y logging seguro.
Todos los módulos generadores usan esta clase como única puerta de entrada a Claude.
"""

import json
import logging
from pathlib import Path

import anthropic
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from config import settings

logger = logging.getLogger(__name__)


def _reparar_json(texto: str) -> str:
    """
    Intenta reparar un JSON truncado cerrando las estructuras abiertas.
    Útil cuando Claude corta la respuesta a mitad del JSON.
    """
    # Contar llaves y corchetes abiertos
    abiertos = []
    en_string = False
    escape = False
    for char in texto:
        if escape:
            escape = False
            continue
        if char == '\\' and en_string:
            escape = True
            continue
        if char == '"' and not escape:
            en_string = not en_string
            continue
        if en_string:
            continue
        if char in ('{', '['):
            abiertos.append(char)
        elif char == '}' and abiertos and abiertos[-1] == '{':
            abiertos.pop()
        elif char == ']' and abiertos and abiertos[-1] == '[':
            abiertos.pop()

    # Cerrar lo que quedó abierto
    cierre = ""
    for apertura in reversed(abiertos):
        cierre += '}' if apertura == '{' else ']'

    # Limpiar la última coma antes de cerrar
    texto_reparado = texto.rstrip().rstrip(',') + cierre
    return texto_reparado


def limpiar_caption(texto: str) -> str:
    """
    Elimina encabezados, etiquetas de sección y prefijos que Claude agrega
    antes del caption real pero que NO deben publicarse en Instagram.

    Ejemplos de líneas que se eliminan:
        # Caption — REEL | Humor Picante 🌶️
        ## Caption
        **Caption:**
        Caption para Instagram:
        ---

    Reglas:
    - Elimina líneas que empiezan con '#' (markdown heading)
    - Elimina líneas que empiezan con '**' y terminan con '**:' (bold label)
    - Elimina líneas que contienen solo '---' o '___' (separadores)
    - Elimina líneas de prefijo como "Caption:", "Caption para Instagram:"
    - Deja el resto intacto — no toca el cuerpo ni los hashtags
    """
    import re as _re

    lineas = texto.splitlines()
    resultado = []
    _PATRON_PREFIJO = _re.compile(
        r"^(#{1,3}\s|"                          # # Heading / ## Heading
        r"\*\*[^*]+\*\*\s*:?\s*$|"             # **Label:** sola en la línea
        r"caption\s*(para\s*instagram)?\s*:?\s*$|"  # Caption: / Caption para Instagram:
        r"[-_]{3,}\s*$)"                         # --- o ___
        , _re.IGNORECASE
    )

    for linea in lineas:
        if _PATRON_PREFIJO.match(linea.strip()):
            continue  # saltar esta línea
        resultado.append(linea)

    # Eliminar líneas vacías al inicio y al final
    return "\n".join(resultado).strip()


class ClienteClaude:
    """
    Centraliza todas las llamadas a Claude.
    - Aplica prompt caching en bloques de brand guidelines (estáticos por semanas)
    - Retry automático: 3 intentos, backoff exponencial (2s → 8s → 32s)
    - Nunca loggea tokens ni contenido sensible
    """

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._model = settings.CLAUDE_MODEL

    @retry(
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=32),
        reraise=True,
    )
    def generar(
        self,
        prompt_sistema: str,
        prompt_usuario: str,
        temperatura: float = 0.8,
        max_tokens: int = settings.CLAUDE_MAX_TOKENS,
        formato_json: bool = False,
    ) -> str:
        """
        Llamada estándar a Claude sin imágenes.
        prompt_sistema: instrucciones de rol + brand guidelines
        prompt_usuario: tarea específica con contexto dinámico
        """
        messages = [{"role": "user", "content": prompt_usuario}]

        kwargs = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperatura,
            "system": prompt_sistema,
            "messages": messages,
        }

        if formato_json:
            kwargs["messages"] = [
                {"role": "user", "content": prompt_usuario + "\n\nResponde ÚNICAMENTE con JSON válido, sin texto adicional."}
            ]

        logger.debug("Claude call: model=%s, temp=%.2f, tokens=%d", self._model, temperatura, max_tokens)
        response = self._client.messages.create(**kwargs)
        texto = response.content[0].text
        logger.debug("Claude response: %d chars, stop_reason=%s", len(texto), response.stop_reason)
        return texto

    @retry(
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=32),
        reraise=True,
    )
    def generar_con_cache(
        self,
        bloque_estatico: str,
        prompt_dinamico: str,
        temperatura: float = 0.8,
        max_tokens: int = settings.CLAUDE_MAX_TOKENS,
    ) -> str:
        """
        Llamada con prompt caching en el bloque de brand guidelines.
        Ahorra costos cuando se llama múltiples veces con el mismo contexto de marca.
        El bloque_estatico (brand guidelines + historial base) se cachea 5 minutos.
        """
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperatura,
            system=[
                {
                    "type": "text",
                    "text": bloque_estatico,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt_dinamico}],
        )
        return response.content[0].text

    @retry(
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=32),
        reraise=True,
    )
    def generar_con_vision(
        self,
        prompt_sistema: str,
        prompt_usuario: str,
        imagenes: list[Path],
        temperatura: float = 0.7,
    ) -> str:
        """Para clasificar imágenes de material con Claude Vision."""
        import base64

        content = []
        for img_path in imagenes[:4]:
            if not img_path.exists():
                continue
            suffix = img_path.suffix.lower()
            media_type_map = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp",
            }
            media_type = media_type_map.get(suffix, "image/jpeg")
            with open(img_path, "rb") as f:
                img_data = base64.standard_b64encode(f.read()).decode("utf-8")
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": img_data},
            })

        content.append({"type": "text", "text": prompt_usuario})

        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            temperature=temperatura,
            system=prompt_sistema,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text

    def generar_json(
        self,
        prompt_sistema: str,
        prompt_usuario: str,
        temperatura: float = 0.7,
        max_tokens: int = settings.CLAUDE_MAX_TOKENS,
    ) -> dict:
        """Genera y parsea JSON automáticamente. Lanza ValueError si no es JSON válido."""
        texto = self.generar(
            prompt_sistema=prompt_sistema,
            prompt_usuario=prompt_usuario,
            temperatura=temperatura,
            max_tokens=max_tokens,
            formato_json=True,
        )
        texto_limpio = texto.strip()
        if texto_limpio.startswith("```"):
            lineas = texto_limpio.split("\n")
            texto_limpio = "\n".join(lineas[1:-1])

        # Intentar parsear directo
        try:
            return json.loads(texto_limpio)
        except json.JSONDecodeError:
            # JSON truncado — intentar reparar cerrando las llaves que faltan
            logger.warning("JSON incompleto recibido de Claude — intentando reparar")
            reparado = _reparar_json(texto_limpio)
            return json.loads(reparado)
