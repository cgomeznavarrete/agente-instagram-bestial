"""
Analiza el rendimiento de hashtags en los posts publicados.
Identifica qué hashtags generaron más alcance y ajusta la selección futura.
Se ejecuta dentro del flujo de análisis semanal.
"""

import json
import logging
from collections import defaultdict
from pathlib import Path

from config import settings
from agente.memoria import gestor_memoria as memoria

logger = logging.getLogger(__name__)

HASHTAGS_JSON = settings.DATOS_DIR / "insights_hashtags.json"


class AnalizadorHashtags:
    """
    Cruza los hashtags usados en cada post con sus métricas de alcance
    para identificar cuáles funcionan mejor.

    Limitación: la Graph API no expone directamente qué hashtags
    impulsaron el alcance. Se infiere correlación: posts con ciertos
    hashtags vs alcance promedio del post.
    """

    def analizar(self) -> dict:
        """
        Analiza los hashtags de los últimos 30 posts cruzados con sus métricas.
        Retorna ranking de hashtags por alcance promedio ponderado.
        """
        metricas = memoria.cargar_metricas()
        if not metricas or not metricas.semanas:
            logger.warning("Sin métricas para analizar hashtags")
            return {}

        # Recolectar posts con sus alcances
        posts_con_metricas = []
        for semana in metricas.semanas[-8:]:  # últimas 8 semanas
            for post in semana.get("posts", []):
                alcance = post.get("alcance", 0)
                guardados = post.get("guardados", 0)
                likes = post.get("likes", 0)
                if alcance > 0 or likes > 0:
                    posts_con_metricas.append({
                        "media_id": post.get("media_id"),
                        "alcance": alcance,
                        "guardados": guardados,
                        "likes": likes,
                        "score": alcance + guardados * 5 + likes * 2,
                    })

        if not posts_con_metricas:
            return {}

        # Cruzar con historial de publicaciones para obtener los hashtags usados
        historial = memoria.cargar_historial()
        media_id_a_hashtags: dict[str, list[str]] = {}

        for pub in historial.publicaciones:
            copy = pub.contenido_copy
            if copy and copy.hashtags and pub.media_id:
                media_id_a_hashtags[pub.media_id] = copy.hashtags

        # Calcular score promedio por hashtag
        hashtag_scores: dict[str, list[float]] = defaultdict(list)
        posts_sin_hashtags = 0

        for post in posts_con_metricas:
            mid = post["media_id"]
            hashtags = media_id_a_hashtags.get(mid, [])
            if not hashtags:
                posts_sin_hashtags += 1
                continue
            score = post["score"]
            for tag in hashtags:
                hashtag_scores[tag].append(score)

        if posts_sin_hashtags:
            logger.info("Posts sin hashtags en historial: %d (sin cruzar)", posts_sin_hashtags)

        # Calcular promedio y apariciones
        resultado = {}
        for tag, scores in hashtag_scores.items():
            resultado[tag] = {
                "apariciones": len(scores),
                "score_promedio": round(sum(scores) / len(scores), 1),
                "score_total": round(sum(scores), 1),
            }

        # Ordenar por score promedio descendente
        ranking = dict(sorted(resultado.items(), key=lambda x: x[1]["score_promedio"], reverse=True))

        # Guardar resultado
        datos_guardar = {
            "fecha_analisis": __import__("datetime").datetime.now().isoformat(),
            "total_posts_analizados": len(posts_con_metricas),
            "total_hashtags_rastreados": len(ranking),
            "ranking": ranking,
            "top_10": list(ranking.keys())[:10],
            "bottom_10": list(ranking.keys())[-10:] if len(ranking) > 10 else [],
        }

        HASHTAGS_JSON.parent.mkdir(parents=True, exist_ok=True)
        HASHTAGS_JSON.write_text(
            json.dumps(datos_guardar, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "Análisis hashtags completado: %d tags, top: %s",
            len(ranking),
            list(ranking.keys())[:3],
        )

        return datos_guardar

    def obtener_top_hashtags(self, n: int = 10) -> list[str]:
        """Retorna los N hashtags con mejor rendimiento histórico."""
        if not HASHTAGS_JSON.exists():
            return []
        try:
            datos = json.loads(HASHTAGS_JSON.read_text(encoding="utf-8"))
            return datos.get("top_10", [])[:n]
        except Exception:
            return []

    def hashtags_a_reducir(self) -> list[str]:
        """Retorna hashtags con bajo rendimiento que conviene rotar hacia afuera."""
        if not HASHTAGS_JSON.exists():
            return []
        try:
            datos = json.loads(HASHTAGS_JSON.read_text(encoding="utf-8"))
            return datos.get("bottom_10", [])
        except Exception:
            return []

    def generar_resumen_legible(self) -> str:
        """Genera un texto legible del análisis para incluir en el reporte semanal."""
        if not HASHTAGS_JSON.exists():
            return "Sin datos de hashtags aún."
        try:
            datos = json.loads(HASHTAGS_JSON.read_text(encoding="utf-8"))
            top = datos.get("top_10", [])[:5]
            total = datos.get("total_hashtags_rastreados", 0)
            posts = datos.get("total_posts_analizados", 0)

            if not top:
                return "Sin suficientes datos para ranking de hashtags."

            lineas = [
                f"## Hashtags — análisis de {posts} posts / {total} tags rastreados\n",
                "**Top 5 por alcance promedio:**",
            ]
            ranking = datos.get("ranking", {})
            for i, tag in enumerate(top, 1):
                info = ranking.get(tag, {})
                lineas.append(
                    f"{i}. {tag} — score prom: {info.get('score_promedio', 0)} "
                    f"({info.get('apariciones', 0)} posts)"
                )

            return "\n".join(lineas)
        except Exception as e:
            return f"Error generando resumen de hashtags: {e}"
