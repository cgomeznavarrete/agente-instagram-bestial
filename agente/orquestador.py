"""
Orquestador principal del agente.

Flujo semanal:
  1. Lee material de Google Drive (imágenes/videos subidos por el usuario)
  2. Genera el calendario con Claude
  3. Genera copies, hooks, CTAs y hashtags con Claude
  4. Agrega texto de marca sobre las imágenes del usuario
  5. Envía a Telegram para aprobación con imagen adjunta
  6. Publica lo aprobado en Instagram en los horarios del calendario
"""

import logging
from pathlib import Path

from config import settings
from agente.memoria import gestor_memoria as memoria

logger = logging.getLogger(__name__)


class OrquestadorSemanal:
    """Ejecuta el ciclo completo semanal."""

    def ejecutar(self) -> dict:
        from agente.gestores import material as gestor_material
        from agente.generadores.calendario import GeneradorCalendario
        from agente.generadores.copies import GeneradorCopies
        from agente.generadores.ideas import GeneradorIdeas
        from agente.generadores.generador_imagenes import generar_post_desde_material
        from agente.generadores.generador_carrusel import generar_carrusel_educativo
        from agente.media.google_drive import obtener_material
        from agente.obsidian.exportador import exportar_calendario

        resultados: dict = {}

        # ── 1. Leer material del usuario desde Google Drive ──
        logger.info("1/5 Leyendo material de Google Drive...")
        catalogo = gestor_material.construir_catalogo()
        resultados["material"] = catalogo["totales"]

        # Inventario de lo que el usuario subió
        fotos_posts    = obtener_material("posts",    max_archivos=20)
        fotos_stories  = obtener_material("stories",  max_archivos=20)
        videos_reels   = obtener_material("reels",    max_archivos=10)
        logger.info(
            "Material disponible → posts: %d | stories: %d | reels: %d",
            len(fotos_posts), len(fotos_stories), len(videos_reels)
        )

        # ── 2. Generar calendario ──
        logger.info("2/5 Generando calendario semanal con Claude...")
        calendario = GeneradorCalendario().generar()
        resultados["semana"] = calendario.semana
        resultados["entradas"] = len(calendario.entradas)

        # ── 3. Generar copies para cada entrada ──
        logger.info("3/5 Generando copies con Claude...")
        gen_copies = GeneradorCopies()
        for entrada in calendario.entradas:
            copy = gen_copies.generar(entrada)
            entrada.contenido_copy = copy
            entrada.estado = "generado"
        memoria.guardar_calendario(calendario)

        # ── 4. Asignar material del usuario + agregar texto de marca ──
        logger.info("4/5 Procesando imágenes del usuario...")
        imagenes_procesadas = 0
        sin_material = 0

        # Iteradores de material por tipo
        import itertools
        iter_posts   = iter(fotos_posts)
        iter_stories = iter(fotos_stories)
        iter_reels   = iter(videos_reels)

        # Pilares que generan carrusel educativo automático (sin foto del usuario)
        _PILARES_CARRUSEL_AUTO = {
            "educacion_sobre_salsas",
            "retos_y_pruebas_de_picante",
            "humor_picante",
        }

        for entrada in calendario.entradas:
            if not entrada.contenido_copy:
                continue

            copy = entrada.contenido_copy
            hook = copy.hook or ""
            cta  = copy.cta  or ""
            es_video = entrada.tipo_contenido in ("reel", "story_video")

            # ── Camino B: carrusel educativo automático ───────────────────────
            if (entrada.tipo_contenido == "carrusel"
                    and entrada.pilar in _PILARES_CARRUSEL_AUTO):
                slides = generar_carrusel_educativo(
                    tema=entrada.concepto,
                    n_slides=5,
                    pilar=entrada.pilar,
                    sufijo=f"_{entrada.id}",
                )
                if slides:
                    entrada.imagenes_carrusel_paths = [str(r) for r in slides]
                    imagenes_procesadas += 1
                    logger.info("Carrusel educativo generado: %d slides para %s",
                                len(slides), entrada.id)
                else:
                    sin_material += 1
                continue

            # ── Reel ──────────────────────────────────────────────────────────
            elif entrada.tipo_contenido == "reel":
                from agente.generadores.video_automatico import generar_reel
                from agente.generadores.imagen_compuesta import generar_escenas_para_video
                from config import imagen_params as params

                video_usuario = next(iter_reels, None)
                ext_video = {".mp4", ".mov", ".avi", ".m4v"}

                if video_usuario and video_usuario.suffix.lower() in ext_video:
                    # Prioridad 1: video real del usuario → publicar directo
                    entrada.video_generado_path = str(video_usuario)
                    imagenes_procesadas += 1
                    logger.info("Reel: video del usuario asignado: %s", video_usuario.name)
                else:
                    # Prioridad 2: fotos del usuario de Posts/ → slideshow
                    fotos_reel = [str(p) for p in fotos_posts[:6]
                                  if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]

                    # Prioridad 3 (fallback): generar escenas IA del producto
                    if not fotos_reel:
                        logger.info("Sin fotos de usuario — generando escenas IA para reel: %s", entrada.id)
                        escenas = generar_escenas_para_video(
                            pilar=entrada.pilar,
                            concepto=entrada.concepto,
                            n=4,
                            formato="story",  # 9:16 para reel
                            sufijo=f"_{entrada.id}",
                        )
                        fotos_reel = [str(p) for p in escenas]

                    if fotos_reel:
                        mood = params.MUSICA_POR_TIPO_CONTENIDO.get(
                            f"reel_{entrada.pilar.split('_')[0]}", "upbeat_latino"
                        )
                        dur = len(fotos_reel) * params.DURACION_IMAGEN_REEL_SEG
                        ruta_mp4 = generar_reel(
                            imagenes=fotos_reel,
                            mood_musica=mood,
                            sufijo=f"_{entrada.id}",
                        )
                        if ruta_mp4:
                            entrada.video_generado_path = str(ruta_mp4)
                            imagenes_procesadas += 1
                            logger.info("Reel slideshow generado: %s", ruta_mp4.name)
                        else:
                            sin_material += 1
                    else:
                        sin_material += 1
                        logger.warning("Sin material para reel: %s", entrada.id)

            # ── Story ─────────────────────────────────────────────────────────
            elif entrada.tipo_contenido in ("story", "story_video"):
                from agente.generadores.imagen_compuesta import (
                    generar_foto_kontext, _foto_referencia_completa
                )
                ext_video = {".mp4", ".mov", ".avi", ".m4v"}
                foto_usuario = next(iter_stories, None) or next(iter_posts, None)

                if foto_usuario and foto_usuario.suffix.lower() in ext_video:
                    # Video del usuario → directo
                    entrada.video_generado_path = str(foto_usuario)
                    imagenes_procesadas += 1
                elif foto_usuario:
                    # Imagen del usuario → story estática
                    entrada.imagen_compuesta_path = str(foto_usuario)
                    imagenes_procesadas += 1
                else:
                    # Sin material del usuario → generar 1 imagen IA
                    logger.info("Sin foto de usuario — generando imagen IA para story: %s", entrada.id)
                    foto_ia = generar_foto_kontext(
                        pilar=entrada.pilar,
                        concepto=entrada.concepto,
                        formato="story",
                        sufijo=f"_{entrada.id}",
                    )
                    if not foto_ia:
                        foto_ia = _foto_referencia_completa()
                    if foto_ia:
                        entrada.imagen_compuesta_path = str(foto_ia)
                        imagenes_procesadas += 1
                    else:
                        sin_material += 1

            # ── Post / Carrusel con fotos del usuario ─────────────────────────
            else:
                from agente.generadores.imagen_compuesta import (
                    generar_foto_kontext, _foto_referencia_completa
                )
                foto = next(iter_posts, None)
                if foto:
                    entrada.imagen_compuesta_path = str(foto)
                    imagenes_procesadas += 1
                else:
                    # Sin foto del usuario → generar imagen IA del producto
                    logger.info("Sin foto de usuario — generando imagen IA para post: %s", entrada.id)
                    foto_ia = generar_foto_kontext(
                        pilar=entrada.pilar,
                        concepto=entrada.concepto,
                        formato="post",
                        sufijo=f"_{entrada.id}",
                    )
                    if not foto_ia:
                        foto_ia = _foto_referencia_completa()
                    if foto_ia:
                        entrada.imagen_compuesta_path = str(foto_ia)
                        imagenes_procesadas += 1
                    else:
                        sin_material += 1
                        logger.info("Sin material para: %s %s — solo copy a Telegram",
                                    entrada.tipo_contenido, entrada.id)

        memoria.guardar_calendario(calendario)
        resultados["con_imagen"] = imagenes_procesadas
        resultados["sin_imagen"] = sin_material

        # ── 5. Exportar a Obsidian + banco de ideas ──
        logger.info("5/5 Exportando a Obsidian...")
        rutas = exportar_calendario(calendario)
        GeneradorIdeas().generar_banco()
        resultados["notas_obsidian"] = len(rutas)

        # ── 6. Enviar todo a Telegram para aprobación ──
        from agente.telegram.notificador import notificar_calendario_completo
        logger.info("Enviando a Telegram...")
        enviadas = notificar_calendario_completo(calendario)
        resultados["telegram_enviadas"] = enviadas

        logger.info(
            "Semana %s: %d entradas | %d con imagen | %d sin imagen | %d a Telegram",
            calendario.semana, len(calendario.entradas),
            imagenes_procesadas, sin_material, enviadas,
        )
        return resultados


class OrquestadorPublicacion:
    """Publica las entradas aprobadas según el calendario."""

    def ejecutar(self) -> dict:
        from agente.instagram.publicador import Publicador
        from agente.instagram.token_refresh import verificar_y_alertar
        from agente.telegram.notificador import procesar_aprobaciones

        # Procesar aprobaciones/rechazos de Telegram
        aprobaciones = procesar_aprobaciones()
        logger.info(
            "Telegram: %d aprobados, %d rechazados",
            aprobaciones["aprobados"], aprobaciones["rechazados"]
        )

        if not verificar_y_alertar():
            logger.error("Token de Instagram inválido o expirado — publicación abortada")
            return {"publicados": 0, "errores": 1, "token_invalido": True}

        entradas = memoria.obtener_entradas_para_publicar_ahora()
        if not entradas:
            logger.info("No hay entradas aprobadas para publicar ahora")
            return {"publicados": 0, "errores": 0}

        pub = Publicador()
        publicados = 0
        errores = 0

        for entrada in entradas:
            resultado = pub.publicar(entrada)
            if resultado.exito:
                entrada.estado = "publicado"
                publicados += 1
                logger.info(
                    "✓ Publicado: %s %s — media_id=%s",
                    entrada.tipo_contenido, entrada.id, resultado.instagram_media_id
                )
            else:
                entrada.estado = "error_publicacion"
                errores += 1
                logger.error(
                    "✗ Error: %s %s — %s",
                    entrada.tipo_contenido, entrada.id, resultado.error
                )

        calendario = memoria.cargar_calendario()
        if calendario:
            memoria.guardar_calendario(calendario)

        return {"publicados": publicados, "errores": errores}


class OrquestadorMetricas:
    """Descarga métricas y genera reporte estratégico."""

    def ejecutar(self) -> str:
        from agente.instagram.metricas import GestorMetricas
        from agente.analisis.analizador_metricas import AnalizadorMetricas

        logger.info("Descargando métricas de Instagram...")
        GestorMetricas().descargar_y_analizar()

        logger.info("Generando reporte estratégico con Claude...")
        reporte = AnalizadorMetricas().generar_reporte()
        return reporte
