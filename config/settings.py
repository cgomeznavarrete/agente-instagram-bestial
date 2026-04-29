"""
Configuración centralizada del agente. Carga variables desde .env o GitHub Secrets.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

# ── Rutas del proyecto ────────────────────────────────────────────────────────
MATERIAL_USUARIO_DIR = BASE_DIR / "material_usuario"
MATERIAL_AGENTE_DIR = BASE_DIR / "material_agente"
DATOS_DIR = BASE_DIR / "datos"
REFERENCIA_PRODUCTO_DIR = BASE_DIR / "referencia_producto"
MUSICA_DIR = BASE_DIR / "musica"
LOGS_DIR = BASE_DIR / "logs"
PROMPTS_DIR = BASE_DIR / "config" / "prompts"

OBSIDIAN_VAULT_PATH = Path(
    os.getenv("OBSIDIAN_VAULT_PATH",
              str(BASE_DIR.parent / "Obsidian-Instagram-Bestial"))
)

# ── Credenciales ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID", "")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "")
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "")
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")
REMOVEBG_API_KEY = os.getenv("REMOVEBG_API_KEY", "")
FALAI_API_KEY = os.getenv("FALAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Modelo IA ─────────────────────────────────────────────────────────────────
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_MAX_TOKENS = 8192

# ── Volumen de contenido semanal ──────────────────────────────────────────────
POSTS_POR_SEMANA = int(os.getenv("POSTS_POR_SEMANA", "3"))
REELS_POR_SEMANA = int(os.getenv("REELS_POR_SEMANA", "2"))
STORIES_POR_SEMANA = int(os.getenv("STORIES_POR_SEMANA", "5"))
CARRUSELES_POR_SEMANA = int(os.getenv("CARRUSELES_POR_SEMANA", "1"))

# ── Límites seguros Meta (cumplimiento de políticas) ─────────────────────────
LIMITES_META = {
    "max_posts_por_dia": 4,
    "max_stories_por_dia": 7,
    "min_intervalo_entre_posts_min": 90,
    "max_reels_por_semana": 3,
    "max_posts_feed_por_semana": 4,
    "max_api_calls_por_hora": 200,
}

# ── Temperaturas de Claude por tipo de contenido ─────────────────────────────
TEMPERATURAS_CLAUDE = {
    "calendario_semanal": 0.7,
    "copy_post": 0.85,
    "copy_reel": 0.90,
    "copy_story": 0.80,
    "copy_carrusel": 0.80,
    "brief_capcut": 0.65,
    "analisis_metricas": 0.30,
    "ideas_contenido": 0.95,
}

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ── Instagram Graph API ───────────────────────────────────────────────────────
INSTAGRAM_API_BASE_URL = "https://graph.facebook.com/v21.0"

# ── Nota de cumplimiento Meta (se inyecta en logs y documentación) ────────────
META_COMPLIANCE_NOTA = (
    "Este agente usa exclusivamente la Instagram Graph API oficial de Meta. "
    "No se realizan auto-likes, auto-follows, auto-comments ni DMs masivos. "
    "Cumple con los Términos de Servicio de Instagram y Meta Platform Policy."
)


def verificar_credenciales() -> dict:
    """Verifica qué credenciales están configuradas. No revela valores."""
    return {
        "anthropic": bool(ANTHROPIC_API_KEY),
        "instagram": bool(INSTAGRAM_ACCESS_TOKEN),
        "instagram_account_id": bool(INSTAGRAM_BUSINESS_ACCOUNT_ID),
        "cloudinary": bool(CLOUDINARY_URL),
        "imgbb": bool(IMGBB_API_KEY),
        "removebg": bool(REMOVEBG_API_KEY),
        "falai": bool(FALAI_API_KEY),
    }
