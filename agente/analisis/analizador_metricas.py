"""
Analiza métricas de Instagram con Claude y genera recomendaciones estratégicas.
El reporte se exporta a Obsidian y queda en material_agente/reportes/.
Incluye: reutilización del mejor Reel e identificación de contenido ganador.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from config import settings
from agente.claude.cliente_claude import ClienteClaude
from agente.claude import prompt_builder as pb
from agente.memoria import gestor_memoria as memoria
from agente.obsidian.exportador import exportar_reporte_metricas

logger = logging.getLogger(__name__)

GANADOR_JSON = settings.DATOS_DIR / "reel_ganador.json"


class AnalizadorMetricas:

    def __init__(self):
        self._claude = ClienteClaude()

    def generar_reporte(self) -> str:
        """
        Genera un reporte estratégico semanal con Claude.
        Retorna el texto del reporte en Markdown.
        Además, identifica el mejor Reel y guarda su concepto para reutilización.
        """
        metricas = memoria.cargar_metricas()
        semana = datetime.now().strftime("%Y-W%W")

        if not metricas or not metricas.semanas:
            logger.warning("No hay métricas para analizar")
            return "# Sin métricas disponibles\n\nEjecuta primero `analizar_metricas` para descargar los datos."

        semanas_recientes = metricas.semanas[-4:]
        historial = memoria.cargar_historial()

        prompt = pb.prompt_analisis_metricas(
            metricas={"semana_actual": semana, "semanas": semanas_recientes},
            historial=[p.model_dump() for p in historial.publicaciones[-20:]],
        )
        contexto_marca = pb.construir_contexto_marca()

        reporte = self._claude.generar_con_cache(
            contexto_cache=contexto_marca,
            prompt_usuario=prompt,
            temperatura=settings.TEMPERATURAS_CLAUDE.get("analisis", 0.3),
            max_tokens=2000,
        )

        self._guardar_reporte(reporte, semana)
        exportar_reporte_metricas(reporte, semana)

        # Identificar mejor Reel y guardar para reutilización la semana siguiente
        mejor = self.identificar_mejor_reel()
        if mejor:
            logger.info("Mejor Reel identificado: %s (ER %.2f%%)", mejor.get("media_id"), mejor.get("er", 0))
            variacion = self.generar_variacion_ganador(mejor)
            if variacion:
                self._guardar_ganador(mejor, variacion, semana)

        return reporte

    def identificar_mejor_reel(self) -> dict | None:
        """Retorna el Reel/VIDEO con mayor engagement rate de las últimas 4 semanas.

        Fórmula ER = (likes + comentarios×3 + guardados×5 + compartidos×4) / seguidores × 100
        Los comentarios y guardados tienen mayor peso porque son señales más fuertes.
        """
        metricas = memoria.cargar_metricas()
        if not metricas or not metricas.semanas:
            return None

        seguidores = 196  # fallback
        mejor_reel = None
        mejor_er = 0.0

        for semana in metricas.semanas[-4:]:
            cuenta = semana.get("cuenta", {})
            seg = cuenta.get("seguidores", 0)
            if seg:
                seguidores = seg

            for post in semana.get("posts", []):
                tipo = post.get("tipo", "")
                if tipo not in ("VIDEO", "REELS"):
                    continue

                likes = post.get("likes", 0)
                comentarios = post.get("comentarios", 0)
                guardados = post.get("guardados", 0)
                compartidos = post.get("compartidos", 0)

                er = (likes + comentarios * 3 + guardados * 5 + compartidos * 4) / max(seguidores, 1) * 100

                if er > mejor_er:
                    mejor_er = er
                    mejor_reel = {**post, "er": round(er, 2), "seguidores": seguidores}

        if mejor_reel and mejor_er >= 3.0:  # umbral mínimo para considerar "ganador"
            return mejor_reel
        return None

    def generar_variacion_ganador(self, reel: dict) -> str | None:
        """Claude genera 3 variaciones del concepto del Reel ganador.
        Retorna el concepto elegido como string (el más diferente al original).
        """
        permalink = reel.get("permalink", "")
        er = reel.get("er", 0)
        fecha = reel.get("fecha", "")[:10]
        likes = reel.get("likes", 0)
        comentarios = reel.get("comentarios", 0)
        guardados = reel.get("guardados", 0)

        prompt = (
            f"Un Reel de Salsas Bestial publicado el {fecha} obtuvo estos resultados:\n"
            f"- Engagement Rate: {er}%\n"
            f"- Likes: {likes} | Comentarios: {comentarios} | Guardados: {guardados}\n"
            f"- Link: {permalink}\n\n"
            "Este Reel fue el más exitoso de las últimas semanas. "
            "Genera 3 variaciones del mismo concepto central para la semana siguiente. "
            "Cada variación debe:\n"
            "- Mantener el mismo pilar emocional (lo que resonó con la audiencia)\n"
            "- Tener un ángulo diferente (no repetir el mismo hook)\n"
            "- Ser apropiada para formato Reel 20-30 segundos\n\n"
            "Devuelve SOLO este JSON:\n"
            '{"variaciones": ["concepto 1 en máx 2 oraciones", "concepto 2", "concepto 3"], '
            '"concepto_elegido": "el concepto más diferente al original pero que mantiene la esencia"}'
        )

        try:
            datos = self._claude.generar_json(
                prompt_sistema="Eres estratega de contenido para Instagram. Especialista en Reels virales de food/lifestyle.",
                prompt_usuario=prompt,
                temperatura=0.8,
            )
            return datos.get("concepto_elegido", "")
        except Exception as e:
            logger.error("Error generando variación del Reel ganador: %s", e)
            return None

    def _guardar_ganador(self, reel: dict, variacion: str, semana: str):
        """Guarda el Reel ganador y su variación para que el calendario lo use la semana siguiente."""
        datos = {
            "semana_analizada": semana,
            "semana_usar": self._semana_siguiente(semana),
            "reel_ganador": {
                "media_id": reel.get("media_id"),
                "er": reel.get("er"),
                "likes": reel.get("likes"),
                "comentarios": reel.get("comentarios"),
                "guardados": reel.get("guardados"),
                "fecha": reel.get("fecha", "")[:10],
                "permalink": reel.get("permalink"),
            },
            "variacion_concepto": variacion,
            "usado": False,
        }
        GANADOR_JSON.parent.mkdir(parents=True, exist_ok=True)
        GANADOR_JSON.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Reel ganador guardado → variación para semana %s", datos["semana_usar"])

    def obtener_variacion_pendiente(self) -> str | None:
        """El generador de calendarios llama esto para incluir la variación del Reel ganador."""
        if not GANADOR_JSON.exists():
            return None
        try:
            datos = json.loads(GANADOR_JSON.read_text(encoding="utf-8"))
            if datos.get("usado"):
                return None
            semana_usar = datos.get("semana_usar", "")
            semana_actual = datetime.now().strftime("%Y-W%W")
            if semana_usar and semana_usar != semana_actual:
                return None  # No es la semana correcta aún
            return datos.get("variacion_concepto")
        except Exception:
            return None

    def marcar_variacion_usada(self):
        """Marca la variación del Reel ganador como usada para no repetirla."""
        if not GANADOR_JSON.exists():
            return
        try:
            datos = json.loads(GANADOR_JSON.read_text(encoding="utf-8"))
            datos["usado"] = True
            GANADOR_JSON.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("No se pudo marcar variación como usada: %s", e)

    def _semana_siguiente(self, semana_iso: str) -> str:
        """Retorna la semana ISO siguiente a la dada (formato YYYY-WWW)."""
        try:
            año, w = semana_iso.split("-W")
            num_semana = int(w) + 1
            if num_semana > 52:
                return f"{int(año) + 1}-W01"
            return f"{año}-W{num_semana:02d}"
        except Exception:
            return semana_iso

    def _guardar_reporte(self, reporte: str, semana: str):
        ruta = settings.MATERIAL_AGENTE_DIR / "reportes" / f"reporte_{semana}.md"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(reporte, encoding="utf-8")
        logger.info("Reporte guardado: %s", ruta.name)
