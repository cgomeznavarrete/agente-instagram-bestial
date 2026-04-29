"""
Descarga y analiza métricas de Instagram via Graph API.
Se ejecuta semanalmente (domingo noche) para informar la estrategia de la siguiente semana.
"""

import logging
from datetime import datetime

from config import settings
from agente.instagram import cliente_api
from agente.memoria import gestor_memoria as memoria
from agente.memoria.modelos import MetricasInstagram, MetricasPost

logger = logging.getLogger(__name__)


class GestorMetricas:

    def descargar_y_analizar(self):
        """Flujo completo: descarga métricas de cuenta + posts recientes → guarda en JSON."""
        semana = datetime.now().strftime("%Y-W%W")

        # Métricas de la cuenta
        datos_cuenta = self._descargar_cuenta()

        # Métricas de los últimos 25 posts
        posts_metricas = self._descargar_posts_recientes()

        # Cargar o crear registro de métricas
        metricas = memoria.cargar_metricas()
        if not metricas:
            metricas = MetricasInstagram()

        # Construir entrada para esta semana
        entrada_semana = {
            "semana": semana,
            "fecha_descarga": datetime.now().isoformat(),
            "cuenta": datos_cuenta,
            "posts": posts_metricas,
        }

        # Evitar duplicar la misma semana
        semanas_existentes = [s.get("semana") for s in metricas.semanas]
        if semana in semanas_existentes:
            idx = semanas_existentes.index(semana)
            metricas.semanas[idx] = entrada_semana
            logger.info("Métricas de semana %s actualizadas", semana)
        else:
            metricas.semanas.append(entrada_semana)
            logger.info("Métricas de semana %s añadidas (%d semanas en total)", semana, len(metricas.semanas))

        memoria.guardar_metricas(metricas)
        return metricas

    def _descargar_cuenta(self) -> dict:
        try:
            datos = cliente_api.obtener_insights_cuenta()
            return {
                "seguidores": datos.get("followers_count", 0),
                "total_posts": datos.get("media_count", 0),
                "visitas_perfil": datos.get("profile_views", 0),
                "clicks_sitio": datos.get("website_clicks", 0),
            }
        except Exception as e:
            logger.error("Error descargando métricas de cuenta: %s", e)
            return {}

    def _descargar_posts_recientes(self) -> list[dict]:
        try:
            medios = cliente_api.listar_medios_recientes(limit=25)
            posts = []
            for medio in medios:
                media_id = medio["id"]
                insights = cliente_api.obtener_insights_media(media_id)

                datos_insights = {}
                for item in insights.get("data", []):
                    datos_insights[item["name"]] = item.get("values", [{}])[0].get("value", 0)

                posts.append({
                    "media_id": media_id,
                    "tipo": medio.get("media_type", ""),
                    "fecha": medio.get("timestamp", ""),
                    "permalink": medio.get("permalink", ""),
                    "likes": medio.get("like_count", 0),
                    "comentarios": medio.get("comments_count", 0),
                    "impresiones": datos_insights.get("impressions", 0),
                    "alcance": datos_insights.get("reach", 0),
                    "guardados": datos_insights.get("saved", 0),
                    "compartidos": datos_insights.get("shares", 0),
                    "vistas_video": datos_insights.get("video_views", 0),
                })
            logger.info("Descargadas métricas de %d posts", len(posts))
            return posts
        except Exception as e:
            logger.error("Error descargando métricas de posts: %s", e)
            return []

    def calcular_engagement_rate(self, post: dict, seguidores: int) -> float:
        """Engagement rate = (likes + comentarios + guardados + compartidos) / seguidores × 100."""
        if not seguidores:
            return 0.0
        interacciones = post.get("likes", 0) + post.get("comentarios", 0) + post.get("guardados", 0) + post.get("compartidos", 0)
        return round((interacciones / seguidores) * 100, 2)

    def mejores_formatos(self) -> dict:
        """Retorna qué tipo de contenido tiene mejor engagement en las últimas 4 semanas."""
        metricas = memoria.cargar_metricas()
        if not metricas or not metricas.semanas:
            return {}

        por_tipo: dict[str, list[float]] = {}
        semanas_recientes = metricas.semanas[-4:]
        seguidores = 1000  # Fallback si no hay dato

        for semana in semanas_recientes:
            cuenta = semana.get("cuenta", {})
            seguidores = cuenta.get("seguidores", seguidores) or seguidores
            for post in semana.get("posts", []):
                tipo = post.get("tipo", "UNKNOWN")
                er = self.calcular_engagement_rate(post, seguidores)
                por_tipo.setdefault(tipo, []).append(er)

        return {tipo: round(sum(ers) / len(ers), 2) for tipo, ers in por_tipo.items() if ers}
