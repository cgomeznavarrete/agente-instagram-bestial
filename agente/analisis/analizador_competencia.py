"""
Análisis mensual de cuentas competidoras con Claude.
Revisa los últimos posts públicos de cuentas objetivo e identifica
qué formatos y temas generan mayor engagement para informar la estrategia.

Uso: python main.py analizar-competencia
     → guarda en datos/insights_competencia.json
     → exporta reporte a material_agente/reportes/competencia_YYYY-MM.md
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import requests

from config import settings
from agente.claude.cliente_claude import ClienteClaude

logger = logging.getLogger(__name__)

COMPETENCIA_JSON = settings.DATOS_DIR / "insights_competencia.json"

# Cuentas a monitorear mensualmente
# Ajusta esta lista según los competidores reales del mercado
CUENTAS_OBJETIVO = [
    # Salsas picantes colombianas
    "aliento_de_dragon",
    "salsaspicantes.co",
    # Street food y comida colombiana con alta interacción
    "empanadas.elmarquez",
    "elmarquezdebogota",
    # Foodbloggers Colombia 10K-100K
    "recetascolombianas",
    "comidacolombia",
    # Hot sauce internacional (referencia de formato)
    "heatonist",
    "trufflehottsauce",
]


class AnalizadorCompetencia:
    """
    Analiza el contenido público de cuentas competidoras usando scraping
    básico de la Graph API pública (sin token — solo datos públicos) o
    manualmente via Claude si el usuario pega los datos.
    """

    def __init__(self):
        self._claude = ClienteClaude()

    def analizar_con_datos_manuales(self, datos_posts: list[dict]) -> dict:
        """
        Analiza una lista de posts de competidores que el usuario pegó manualmente.

        Cada dict en datos_posts debe tener:
        - cuenta: str (username)
        - tipo: str (video/imagen/carrusel)
        - tema: str (descripción corta de qué trata)
        - likes: int
        - comentarios: int
        - fecha: str (YYYY-MM-DD)
        - caption_fragmento: str (primeras líneas del caption)

        Retorna análisis de Claude con patrones identificados.
        """
        if not datos_posts:
            return {"error": "Sin datos de posts para analizar"}

        prompt = (
            f"Analiza estos {len(datos_posts)} posts de cuentas competidoras en el nicho de "
            "salsas picantes / comida colombiana:\n\n"
            + json.dumps(datos_posts, ensure_ascii=False, indent=2)
            + "\n\nIDENTIFICA:\n"
            "1. Qué formatos (video/imagen/carrusel) tienen más engagement y por qué\n"
            "2. Qué temas/conceptos generan más comentarios (no solo likes)\n"
            "3. Qué estructura tienen los hooks de los posts más exitosos\n"
            "4. Qué oportunidades NO están aprovechando (gaps de contenido)\n"
            "5. Qué podría hacer Salsas Bestial diferente y mejor\n\n"
            "Contexto: Salsas Bestial es una salsa tatemada ahumada artesanal colombiana, "
            "196 seguidores actualmente, objetivo llegar a 1,000 en 12 semanas.\n\n"
            "Devuelve SOLO este JSON:\n"
            "{\n"
            '  "resumen_ejecutivo": "3 oraciones con lo más importante",\n'
            '  "formatos_ganadores": ["formato 1 con razón", "formato 2"],\n'
            '  "temas_mas_efectivos": ["tema 1", "tema 2", "tema 3"],\n'
            '  "patron_hooks_exitosos": "descripción del patrón",\n'
            '  "gaps_oportunidad": ["oportunidad 1", "oportunidad 2"],\n'
            '  "acciones_para_bestial": [\n'
            '    {"accion": "qué hacer", "prioridad": "alta|media|baja", "razon": "por qué"}\n'
            "  ],\n"
            '  "cuentas_referencia": ["cuenta que más puede aprender Bestial", "razón"]\n'
            "}"
        )

        try:
            analisis = self._claude.generar_json(
                prompt_sistema=(
                    "Eres estratega de contenido para Instagram con experiencia en marcas de "
                    "comida artesanal latinoamericana. Analizas competencia para encontrar "
                    "ventajas reales, no observaciones genéricas."
                ),
                prompt_usuario=prompt,
                temperatura=0.4,
            )
        except Exception as e:
            logger.error("Error en análisis de competencia: %s", e)
            return {"error": str(e)}

        resultado = {
            "fecha_analisis": datetime.now().isoformat(),
            "mes": datetime.now().strftime("%Y-%m"),
            "posts_analizados": len(datos_posts),
            "cuentas": list({p.get("cuenta", "") for p in datos_posts}),
            "analisis": analisis,
        }

        self._guardar(resultado)
        self._exportar_reporte(resultado)

        return resultado

    def analizar_con_hashtag_api(self, hashtag: str, limit: int = 20) -> list[dict]:
        """
        Obtiene posts recientes de un hashtag via Graph API para analizar
        qué tipo de contenido está funcionando en el nicho.

        Requiere INSTAGRAM_ACCESS_TOKEN con permiso instagram_basic.
        """
        if not settings.INSTAGRAM_ACCESS_TOKEN:
            logger.warning("Sin token de Instagram para buscar hashtag")
            return []

        try:
            # Buscar ID del hashtag
            r1 = requests.get(
                f"https://graph.facebook.com/v21.0/ig_hashtag_search",
                params={
                    "user_id": settings.INSTAGRAM_BUSINESS_ACCOUNT_ID,
                    "q": hashtag.lstrip("#"),
                    "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
                },
                timeout=15,
            )
            hashtag_id = r1.json().get("data", [{}])[0].get("id")
            if not hashtag_id:
                return []

            # Obtener posts recientes del hashtag
            r2 = requests.get(
                f"https://graph.facebook.com/v21.0/{hashtag_id}/recent_media",
                params={
                    "user_id": settings.INSTAGRAM_BUSINESS_ACCOUNT_ID,
                    "fields": "id,media_type,like_count,comments_count,caption,timestamp",
                    "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
                    "limit": limit,
                },
                timeout=15,
            )

            posts = []
            for post in r2.json().get("data", []):
                caption = post.get("caption", "")
                posts.append({
                    "cuenta": f"#{hashtag}",
                    "tipo": post.get("media_type", "IMAGE").lower(),
                    "tema": caption[:100] if caption else "",
                    "likes": post.get("like_count", 0),
                    "comentarios": post.get("comments_count", 0),
                    "fecha": post.get("timestamp", "")[:10],
                    "caption_fragmento": caption[:200] if caption else "",
                })

            logger.info("Obtenidos %d posts del hashtag #%s", len(posts), hashtag)
            return posts

        except Exception as e:
            logger.error("Error obteniendo posts del hashtag #%s: %s", hashtag, e)
            return []

    def cargar_ultimo_analisis(self) -> dict:
        """Carga el análisis más reciente guardado."""
        if not COMPETENCIA_JSON.exists():
            return {}
        try:
            return json.loads(COMPETENCIA_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def resumen_para_calendario(self) -> str:
        """Retorna un resumen breve del análisis de competencia para informar el calendario semanal."""
        datos = self.cargar_ultimo_analisis()
        if not datos or "analisis" not in datos:
            return ""

        analisis = datos["analisis"]
        mes = datos.get("mes", "")
        resumen = analisis.get("resumen_ejecutivo", "")
        acciones = analisis.get("acciones_para_bestial", [])

        if not resumen:
            return ""

        lineas = [
            f"[Análisis competencia {mes}]",
            resumen,
        ]
        alta_prioridad = [a["accion"] for a in acciones if a.get("prioridad") == "alta"]
        if alta_prioridad:
            lineas.append("Acciones alta prioridad: " + "; ".join(alta_prioridad[:2]))

        return " | ".join(lineas)

    def _guardar(self, resultado: dict):
        """Guarda el análisis en JSON (sobreescribe el anterior del mismo mes)."""
        COMPETENCIA_JSON.parent.mkdir(parents=True, exist_ok=True)
        COMPETENCIA_JSON.write_text(
            json.dumps(resultado, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Insights de competencia guardados → %s", COMPETENCIA_JSON.name)

    def _exportar_reporte(self, resultado: dict):
        """Exporta el análisis como Markdown legible."""
        mes = resultado.get("mes", datetime.now().strftime("%Y-%m"))
        analisis = resultado.get("analisis", {})

        lineas = [
            f"# Análisis de Competencia — {mes}\n",
            f"**Posts analizados:** {resultado.get('posts_analizados', 0)}  ",
            f"**Cuentas monitoreadas:** {', '.join(resultado.get('cuentas', []))}\n",
            f"## Resumen ejecutivo\n{analisis.get('resumen_ejecutivo', '')}\n",
            "## Formatos ganadores",
        ]
        for f in analisis.get("formatos_ganadores", []):
            lineas.append(f"- {f}")

        lineas += ["", "## Temas más efectivos"]
        for t in analisis.get("temas_mas_efectivos", []):
            lineas.append(f"- {t}")

        lineas += ["", f"## Patrón de hooks exitosos\n{analisis.get('patron_hooks_exitosos', '')}\n"]

        lineas += ["## Gaps y oportunidades"]
        for g in analisis.get("gaps_oportunidad", []):
            lineas.append(f"- {g}")

        lineas += ["", "## Acciones para Salsas Bestial"]
        for a in analisis.get("acciones_para_bestial", []):
            prioridad = a.get("prioridad", "media").upper()
            lineas.append(f"- **[{prioridad}]** {a.get('accion', '')} — _{a.get('razon', '')}_")

        reporte = "\n".join(lineas)
        ruta = settings.MATERIAL_AGENTE_DIR / "reportes" / f"competencia_{mes}.md"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(reporte, encoding="utf-8")
        logger.info("Reporte de competencia exportado: %s", ruta.name)
