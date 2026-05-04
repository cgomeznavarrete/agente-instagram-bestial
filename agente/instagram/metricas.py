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
        from datetime import timedelta
        hoy = datetime.now().date()
        # Calcular inicio de semana ISO (lunes) y fin (domingo)
        lunes = hoy - timedelta(days=hoy.weekday())
        domingo = lunes + timedelta(days=6)
        semana = datetime.now().strftime("%Y-W%W")

        datos_cuenta = self._descargar_cuenta()
        posts_metricas = self._descargar_posts_recientes()

        metricas = memoria.cargar_metricas()
        if not metricas:
            metricas = MetricasInstagram()

        from agente.memoria.modelos import MetricasSemana
        nueva_semana = MetricasSemana(
            semana=semana,
            fecha_inicio=lunes,
            fecha_fin=domingo,
            metricas_cuenta=datos_cuenta,
            mejores_posts=[
                p["media_id"] for p in sorted(
                    posts_metricas, key=lambda x: x.get("likes", 0) + x.get("comentarios", 0) * 3, reverse=True
                )[:3]
            ],
            peores_posts=[
                p["media_id"] for p in sorted(
                    posts_metricas, key=lambda x: x.get("likes", 0) + x.get("comentarios", 0) * 3
                )[:3]
            ],
            engagement_promedio=round(
                sum(p.get("likes", 0) + p.get("comentarios", 0) for p in posts_metricas) / max(len(posts_metricas), 1), 2
            ) if posts_metricas else 0.0,
            nuevos_seguidores=0,  # Requires separate follower_count call
        )
        # Attach raw posts for analysis (stored as extra in metricas_cuenta dict)
        nueva_semana.metricas_cuenta["posts_raw"] = posts_metricas

        semanas_existentes = [s.semana for s in metricas.semanas]
        if semana in semanas_existentes:
            idx = semanas_existentes.index(semana)
            metricas.semanas[idx] = nueva_semana
            logger.info("Métricas de semana %s actualizadas", semana)
        else:
            metricas.semanas.append(nueva_semana)
            logger.info("Métricas de semana %s añadidas (%d semanas total)", semana, len(metricas.semanas))

        memoria.guardar_metricas(metricas)
        return metricas

    def _descargar_cuenta(self) -> dict:
        try:
            datos = cliente_api.obtener_insights_cuenta()
            return {
                "seguidores": datos.get("followers_count", 0),
                "total_posts": datos.get("media_count", 0),
                "visitas_perfil": datos.get("visitas_perfil", 0),
                "clicks_link": datos.get("clicks_link", 0),
                "reach_semana": datos.get("reach_semana", 0),
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
                media_type = medio.get("media_type", "IMAGE")
                insights = cliente_api.obtener_insights_media(media_id, media_type)

                posts.append({
                    "media_id": media_id,
                    "tipo": media_type,
                    "fecha": medio.get("timestamp", ""),
                    "permalink": medio.get("permalink", ""),
                    "likes": medio.get("like_count", 0),
                    "comentarios": medio.get("comments_count", 0),
                    "alcance": insights.get("reach", 0),
                    "guardados": insights.get("saved", 0),
                    "compartidos": insights.get("shares", 0),
                    "total_interacciones": insights.get("total_interactions", 0),
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
            s_dict = semana.model_dump(mode="json") if hasattr(semana, "model_dump") else semana
            cuenta = s_dict.get("metricas_cuenta", s_dict.get("cuenta", {}))
            seguidores = cuenta.get("seguidores", seguidores) or seguidores
            for post in cuenta.get("posts_raw", s_dict.get("posts", [])):
                tipo = post.get("tipo", "UNKNOWN")
                er = self.calcular_engagement_rate(post, seguidores)
                por_tipo.setdefault(tipo, []).append(er)

        return {tipo: round(sum(ers) / len(ers), 2) for tipo, ers in por_tipo.items() if ers}
