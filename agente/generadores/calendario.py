"""
Genera el calendario semanal de contenido usando Claude.
Considera métricas previas, material disponible, campañas activas e historial.
"""

import uuid
import logging
from datetime import date, timedelta

from config import settings
from agente.claude.cliente_claude import ClienteClaude
from agente.claude.prompt_builder import construir_contexto_marca, prompt_calendario
from agente.memoria import gestor_memoria as memoria
from agente.memoria.modelos import CalendarioSemanal, EntradaCalendario
from agente.gestores import material as gestor_material
from agente.gestores.rotacion import validar_distribucion_semanal
from agente.analisis.analizador_metricas import AnalizadorMetricas

logger = logging.getLogger(__name__)


def _numero_semana(hoy: date) -> str:
    """Retorna el identificador de semana en formato YYYY-WNN."""
    iso = hoy.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _inicio_semana(hoy: date) -> date:
    """Retorna el lunes de la semana actual."""
    return hoy - timedelta(days=hoy.weekday())


def _resumen_historial(publicaciones: list) -> list[dict]:
    """Convierte publicaciones recientes a formato resumido para el prompt."""
    return [
        {
            "fecha": str(p.fecha_publicacion.date()) if p.fecha_publicacion else "",
            "tipo": p.tipo,
            "pilar": p.pilar,
            "concepto": p.notas or "",
        }
        for p in publicaciones[-12:]
    ]


def _resumen_catalogo(catalogo: dict) -> dict:
    """Resume el catálogo para el prompt (sin rutas completas)."""
    def contar(lista, categoria):
        return len([a for a in lista if a.get("categoria") == categoria])

    usuario = catalogo.get("material_usuario", [])
    return {
        "imagenes_producto": contar(usuario, "producto"),
        "imagenes_lifestyle": contar(usuario, "lifestyle"),
        "imagenes_eventos": contar(usuario, "evento"),
        "videos": len([a for a in usuario if a["tipo"] == "video"]),
        "total": len(usuario),
    }


class GeneradorCalendario:

    def __init__(self):
        self._claude = ClienteClaude()

    def generar(self) -> CalendarioSemanal:
        hoy = date.today()
        lunes = _inicio_semana(hoy)
        domingo = lunes + timedelta(days=6)
        semana = _numero_semana(lunes)

        logger.info("Generando calendario semana %s", semana)

        metricas_raw = memoria.obtener_metricas_semana_anterior()
        historial_raw = memoria.obtener_publicaciones_recientes(semanas=8)
        campanas = memoria.obtener_campanas_activas()
        catalogo = gestor_material.construir_catalogo()

        campanas_data = [
            {"nombre": c.nombre, "descripcion": c.descripcion, "objetivo": c.objetivo}
            for c in campanas
        ]

        # Verificar si hay una variación de Reel ganador pendiente de usar
        analizador = AnalizadorMetricas()
        reel_ganador_concepto = analizador.obtener_variacion_pendiente() or ""
        if reel_ganador_concepto:
            logger.info("Incluyendo variación de Reel ganador en el calendario: %.80s...", reel_ganador_concepto)

        prompt_usuario = prompt_calendario(
            semana=semana,
            metricas_previas=metricas_raw,
            material_disponible=_resumen_catalogo(catalogo),
            campanas_activas=campanas_data,
            historial_resumido=_resumen_historial(historial_raw),
            posts_semana=settings.POSTS_POR_SEMANA,
            reels_semana=settings.REELS_POR_SEMANA,
            stories_semana=settings.STORIES_POR_SEMANA,
            carruseles_semana=settings.CARRUSELES_POR_SEMANA,
            reel_ganador_concepto=reel_ganador_concepto,
        )

        datos = self._claude.generar_json(
            prompt_sistema=construir_contexto_marca(),
            prompt_usuario=prompt_usuario,
            temperatura=settings.TEMPERATURAS_CLAUDE["calendario_semanal"],
        )

        entradas = self._parsear_entradas(datos.get("entradas", []), lunes)

        advertencias = validar_distribucion_semanal(
            [{"dia": e.dia, "pilar": e.pilar} for e in entradas]
        )
        for adv in advertencias:
            logger.warning("Calendario: %s", adv)

        calendario = CalendarioSemanal(
            semana=semana,
            fecha_inicio=lunes,
            fecha_fin=domingo,
            entradas=entradas,
            notas_estrategia=datos.get("notas_estrategia", ""),
        )

        memoria.guardar_calendario(calendario)

        # Marcar variación del Reel ganador como usada (para no repetirla la semana siguiente)
        if reel_ganador_concepto:
            analizador.marcar_variacion_usada()

        # Archivar copia
        archivo_semana = settings.MATERIAL_AGENTE_DIR / "calendarios" / f"calendario_{semana}.json"
        import json
        archivo_semana.parent.mkdir(exist_ok=True)
        with open(archivo_semana, "w", encoding="utf-8") as f:
            json.dump(calendario.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

        logger.info("Calendario %s generado: %d entradas", semana, len(entradas))
        return calendario

    def _parsear_entradas(self, raw: list[dict], lunes: date) -> list[EntradaCalendario]:
        """Convierte la respuesta de Claude en modelos EntradaCalendario."""
        dias_map = {
            "lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2,
            "jueves": 3, "viernes": 4, "sabado": 5, "sábado": 5, "domingo": 6,
        }
        entradas = []
        for item in raw:
            dia = item.get("dia", "lunes").lower()
            offset = dias_map.get(dia, 0)
            fecha_entrada = lunes + timedelta(days=offset)

            # Normalizar pilar: Claude puede devolver Title Case o spaces, Pydantic requiere snake_case
            pilar_raw = item.get("pilar", "lifestyle_y_comunidad")
            pilar = pilar_raw.lower().replace(" ", "_")

            try:
                entrada = EntradaCalendario(
                    id=f"cal-{uuid.uuid4().hex[:6]}",
                    dia=dia,
                    fecha=fecha_entrada,
                    hora_publicacion=item.get("hora_publicacion", "19:00"),
                    tipo_contenido=item.get("tipo_contenido", "post"),
                    pilar=pilar,
                    objetivo=item.get("objetivo", "engagement"),
                    concepto=item.get("concepto", ""),
                    material_sugerido=item.get("material_sugerido", []),
                    estado="pendiente",
                )
                entradas.append(entrada)
            except Exception as e:
                logger.warning("Entrada de calendario omitida por error: %s — %s", item, e)

        return entradas
