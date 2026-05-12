"""
Agente Instagram — Salsas Bestial
CLI principal. Todos los comandos del agente se ejecutan desde aquí.
"""

import logging
import sys
from pathlib import Path

# Forzar UTF-8 en Windows para compatibilidad con caracteres especiales
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

from config import settings
from agente.memoria import gestor_memoria as memoria
from agente.claude.cliente_claude import limpiar_caption

console = Console()

# ── Logging ───────────────────────────────────────────────────────────────────
settings.LOGS_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(settings.LOGS_DIR / "agente.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ── Grupo principal ───────────────────────────────────────────────────────────

@click.group()
def cli():
    """Agente de contenido Instagram para Salsas Bestial."""
    pass


# ── Comandos ──────────────────────────────────────────────────────────────────

@cli.command()
def inicializar():
    """Inicializa el proyecto: crea carpetas y archivos JSON vacíos."""
    console.print(Panel("[bold green]Inicializando Agente Salsas Bestial[/bold green]"))

    # Crear directorios si no existen
    for directorio in [
        settings.MATERIAL_USUARIO_DIR / "fotos/productos",
        settings.MATERIAL_USUARIO_DIR / "fotos/lifestyle",
        settings.MATERIAL_USUARIO_DIR / "fotos/eventos",
        settings.MATERIAL_USUARIO_DIR / "videos/productos",
        settings.MATERIAL_USUARIO_DIR / "videos/lifestyle",
        settings.MATERIAL_AGENTE_DIR / "briefs_capcut",
        settings.MATERIAL_AGENTE_DIR / "videos_generados",
        settings.MATERIAL_AGENTE_DIR / "imagenes_compuestas",
        settings.MATERIAL_AGENTE_DIR / "copies",
        settings.MATERIAL_AGENTE_DIR / "calendarios",
        settings.MATERIAL_AGENTE_DIR / "reportes",
        settings.REFERENCIA_PRODUCTO_DIR,
        settings.REFERENCIA_PRODUCTO_DIR / "recortados",
        settings.MUSICA_DIR,
        settings.DATOS_DIR,
        settings.LOGS_DIR,
        settings.OBSIDIAN_VAULT_PATH / "Semanas",
    ]:
        directorio.mkdir(parents=True, exist_ok=True)

    memoria.inicializar_archivos()
    console.print("[green]✓[/green] Archivos JSON inicializados en datos/")

    credenciales = settings.verificar_credenciales()
    tabla = Table(title="Estado de credenciales")
    tabla.add_column("Servicio")
    tabla.add_column("Estado")
    for servicio, configurado in credenciales.items():
        estado = "[green]✓ Configurado[/green]" if configurado else "[red]✗ Falta en .env[/red]"
        tabla.add_row(servicio, estado)
    console.print(tabla)

    if not (settings.BASE_DIR / ".env").exists():
        console.print("\n[yellow]⚠ No se encontró .env[/yellow]")
        console.print("Copia .env.example → .env y completa las credenciales.")


@cli.command()
def generar_calendario():
    """Genera el calendario semanal de contenido con Claude."""
    from agente.generadores.calendario import GeneradorCalendario

    console.print(Panel("[bold blue]Generando calendario semanal[/bold blue]"))
    generador = GeneradorCalendario()
    calendario = generador.generar()

    console.print(f"[green]✓[/green] Calendario generado: semana {calendario.semana}")
    console.print(f"  {len(calendario.entradas)} entradas | {calendario.estado}")

    tabla = Table(title=f"Calendario semana {calendario.semana}")
    tabla.add_column("Día")
    tabla.add_column("Hora")
    tabla.add_column("Tipo")
    tabla.add_column("Pilar")
    tabla.add_column("Concepto")
    for e in calendario.entradas:
        tabla.add_row(
            e.dia.capitalize(),
            e.hora_publicacion,
            e.tipo_contenido,
            e.pilar.replace("_", " ")[:25],
            e.concepto[:45] + ("..." if len(e.concepto) > 45 else ""),
        )
    console.print(tabla)


@cli.command()
def generar_copies():
    """Genera copies para todas las entradas del calendario actual."""
    from agente.generadores.copies import GeneradorCopies

    calendario = memoria.cargar_calendario()
    if not calendario:
        console.print("[red]No hay calendario activo. Ejecuta primero: generar_calendario[/red]")
        return

    generador = GeneradorCopies()
    pendientes = [e for e in calendario.entradas if e.copy is None and e.estado == "pendiente"]
    console.print(f"Generando copies para {len(pendientes)} entradas...")

    for i, entrada in enumerate(pendientes, 1):
        console.print(f"  [{i}/{len(pendientes)}] {entrada.tipo_contenido} — {entrada.concepto[:50]}...")
        copy = generador.generar(entrada)
        entrada.copy = copy
        entrada.estado = "generado"

    memoria.guardar_calendario(calendario)
    console.print(f"[green]✓[/green] Copies generados y guardados en calendario")


@cli.command()
@click.option("--id", "entrada_id", help="ID de una entrada específica")
def generar_briefs(entrada_id):
    """Genera briefs de CapCut para los Reels y Stories de video."""
    from agente.generadores.brief_capcut import GeneradorBriefCapCut

    calendario = memoria.cargar_calendario()
    if not calendario:
        console.print("[red]No hay calendario activo.[/red]")
        return

    tipos_video = {"reel", "story_video"}
    entradas = calendario.entradas

    if entrada_id:
        entradas = [e for e in entradas if e.id == entrada_id]
    else:
        entradas = [e for e in entradas if e.tipo_contenido in tipos_video and not e.brief_capcut_path]

    generador = GeneradorBriefCapCut()
    for entrada in entradas:
        console.print(f"  Brief: {entrada.tipo_contenido} — {entrada.concepto[:50]}...")
        ruta = generador.generar_y_guardar(entrada)
        entrada.brief_capcut_path = str(ruta)

    memoria.guardar_calendario(calendario)
    console.print(f"[green]✓[/green] {len(entradas)} briefs guardados en material_agente/briefs_capcut/")


@cli.command()
def ejecutar_semana():
    """Flujo completo: calendario → copies → imágenes → videos → Telegram para aprobar."""
    console.print(Panel("[bold magenta]Ejecutando flujo semanal completo — Salsas Bestial[/bold magenta]"))
    from agente.orquestador import OrquestadorSemanal
    resultados = OrquestadorSemanal().ejecutar()

    tabla = Table(title="Resultado")
    tabla.add_column("Componente")
    tabla.add_column("Resultado", justify="right")
    for k, v in resultados.items():
        tabla.add_row(k.replace("_", " ").capitalize(), str(v))
    console.print(tabla)
    console.print(Panel(
        "[bold green]Semana generada.[/bold green]\n\n"
        "Revisa y aprueba el contenido en Telegram desde tu celular.\n"
        "Toca ✅ en cada pieza que quieras publicar.\n\n"
        "Luego ejecuta:\n[bold]python main.py publicar_pendientes[/bold]",
        title="Listo",
    ))


@cli.command()
def publicar_pendientes():
    """Publica las entradas aprobadas según el calendario."""
    from agente.instagram.publicador import Publicador

    entradas = memoria.obtener_entradas_para_publicar_ahora()
    if not entradas:
        console.print("[yellow]No hay entradas aprobadas para publicar en este momento.[/yellow]")
        return

    pub = Publicador()
    for entrada in entradas:
        console.print(f"Publicando: {entrada.tipo_contenido} — {entrada.concepto[:50]}...")
        resultado = pub.publicar(entrada)
        if resultado.exito:
            console.print(f"  [green]✓[/green] Publicado: media_id={resultado.instagram_media_id}")
            # Marcar como publicado para que no se vuelva a intentar en el próximo ciclo
            memoria.actualizar_estado_entrada(entrada.id, "publicado")
        else:
            console.print(f"  [red]✗[/red] Error: {resultado.error}")


@cli.command()
def analizar_metricas():
    """Descarga métricas, identifica Reel ganador y analiza hashtags."""
    from agente.orquestador import OrquestadorMetricas
    from agente.analisis.analizador_hashtags import AnalizadorHashtags

    console.print(Panel("[bold cyan]Analizando métricas de Instagram[/bold cyan]"))
    reporte = OrquestadorMetricas().ejecutar()
    console.print("[green]✓[/green] Métricas y Reel ganador actualizados")

    # Análisis de hashtags — correlaciona hashtags usados con alcance
    console.print("[cyan]Analizando rendimiento de hashtags...[/cyan]")
    try:
        datos_ht = AnalizadorHashtags().analizar()
        top = datos_ht.get("top_10", [])[:5]
        if top:
            console.print(f"[green]✓[/green] Top hashtags: {', '.join(top)}")
        else:
            console.print("[yellow]⚠[/yellow] Sin suficientes datos para ranking de hashtags aún")
    except Exception as e:
        console.print(f"[yellow]⚠[/yellow] Hashtags: {e}")

    console.print("[green]✓[/green] Reporte completo generado en material_agente/reportes/")


@cli.command(name="analizar-competencia")
@click.option("--hashtag", default="salsapicante", help="Hashtag para buscar posts de nicho via Graph API")
@click.option("--manual", is_flag=True, default=False, help="Modo manual: pegar datos en stdin como JSON")
def analizar_competencia(hashtag: str, manual: bool):
    """Analiza competidores e identifica oportunidades de contenido (corre 1 vez/mes)."""
    from agente.analisis.analizador_competencia import AnalizadorCompetencia

    console.print(Panel("[bold cyan]Análisis de competencia[/bold cyan]"))
    analizador = AnalizadorCompetencia()

    if manual:
        console.print(
            "Pega un JSON con los posts de competidores y presiona Enter dos veces.\n"
            "Formato: lista de objetos con: cuenta, tipo, tema, likes, comentarios, fecha, caption_fragmento"
        )
        lines = []
        try:
            while True:
                line = input()
                if line == "":
                    break
                lines.append(line)
        except EOFError:
            pass
        import json as _json
        datos = _json.loads("\n".join(lines))
        resultado = analizador.analizar_con_datos_manuales(datos)
    else:
        console.print(f"[cyan]Buscando posts del hashtag #{hashtag} via Graph API...[/cyan]")
        posts = analizador.analizar_con_hashtag_api(hashtag, limit=20)
        if not posts:
            console.print("[yellow]Sin posts del API. Usa --manual para pegar datos.[/yellow]")
            return
        console.print(f"[green]{len(posts)} posts obtenidos. Analizando con Claude...[/green]")
        resultado = analizador.analizar_con_datos_manuales(posts)

    analisis = resultado.get("analisis", {})
    if analisis:
        console.print(f"\n[bold]Resumen:[/bold] {analisis.get('resumen_ejecutivo', '')}")
        acciones = analisis.get("acciones_para_bestial", [])
        for a in acciones:
            prioridad = a.get("prioridad", "media").upper()
            color = "red" if prioridad == "ALTA" else "yellow"
            console.print(f"  [{color}][{prioridad}][/{color}] {a.get('accion', '')}")
        console.print("\n[green]✓[/green] Reporte guardado en material_agente/reportes/")


@cli.command()
@click.option("--tipo", default="post", type=click.Choice(["post", "story", "card_rojo", "card_crema", "card_negro"]),
              help="Tipo de template a generar")
@click.option("--hook", default="Esta salsa arruinó todas las demás para siempre",
              help="Texto principal (hook)")
@click.option("--cta", default="Enlace en bio. Sin excusas.", help="Llamada a la acción")
@click.option("--telegram", is_flag=True, default=False, help="Enviar resultado a Telegram")
def generar_imagen(tipo, hook, cta, telegram):
    """Genera una imagen de muestra con el nuevo sistema de templates."""
    from agente.generadores.generador_imagenes import (
        generar_post_organico, generar_post_card,
        generar_story_organica, generar_story_card,
    )

    console.print(Panel(f"[bold blue]Generando imagen — template: {tipo}[/bold blue]"))

    ruta = None
    if tipo == "post":
        ruta = generar_post_organico(hook, cta)
    elif tipo == "story":
        ruta = generar_story_organica(hook, cta)
    elif tipo == "card_rojo":
        ruta = generar_post_card(hook, cta=cta, esquema_color="rojo")
    elif tipo == "card_crema":
        ruta = generar_post_card(hook, cta=cta, esquema_color="crema")
    elif tipo == "card_negro":
        ruta = generar_post_card(hook, cta=cta, esquema_color="negro")

    if ruta:
        console.print(f"[green]✓[/green] Imagen guardada: {ruta}")
        if telegram:
            from agente.telegram.notificador import _enviar_foto
            result = _enviar_foto(ruta, caption=f"<b>{hook}</b>\n\n{cta}")
            if result.get("ok"):
                console.print("[green]✓[/green] Enviada a Telegram")
            else:
                console.print(f"[red]Error Telegram:[/red] {result}")
    else:
        console.print("[red]Error al generar imagen[/red]")


@cli.command()
def generar_semana_completa():
    """Flujo completo moderno: calendario → copies → imágenes → videos → Telegram."""
    console.print(Panel("[bold magenta]Ejecutando flujo semanal completo v2[/bold magenta]"))
    from agente.orquestador import OrquestadorSemanal
    resultados = OrquestadorSemanal().ejecutar()

    tabla = Table(title="Resultado de la semana")
    tabla.add_column("Componente")
    tabla.add_column("Resultado", justify="right")
    for k, v in resultados.items():
        tabla.add_row(k.replace("_", " ").capitalize(), str(v))
    console.print(tabla)


@cli.command()
@click.argument("ruta_foto")
@click.option("--formato", default="post", type=click.Choice(["post", "story", "portrait"]))
@click.option("--ia/--sin-ia", default=True, help="Usar Fal.ai para mejora profunda")
@click.option("--intensidad", default=0.30, type=float, help="Intensidad IA (0.2-0.5)")
@click.option("--hook", default="", help="Texto principal a agregar encima")
@click.option("--cta", default="", help="CTA a agregar")
@click.option("--telegram", is_flag=True, default=False)
def mejorar_foto(ruta_foto, formato, ia, intensidad, hook, cta, telegram):
    """Mejora una foto del celular y la convierte en contenido profesional."""
    from agente.generadores.mejorador_foto import mejorar_foto as _mejorar
    from agente.generadores.generador_imagenes import generar_post_desde_material

    ruta = Path(ruta_foto)
    if not ruta.exists():
        console.print(f"[red]Archivo no encontrado: {ruta}[/red]")
        return

    console.print(Panel(f"[bold blue]Mejorando foto: {ruta.name}[/bold blue]"))
    console.print(f"  Formato: {formato} | IA: {'Sí' if ia else 'No'} | Intensidad: {intensidad}")

    with console.status("Aplicando corrección de color y luz..."):
        foto_mejorada = _mejorar(ruta, formato=formato, usar_ia=False)

    if ia and settings.FALAI_API_KEY:
        with console.status("Mejorando con IA (Fal.ai)... puede tardar 20-40 segundos"):
            foto_mejorada = _mejorar(ruta, formato=formato, usar_ia=True, intensidad_ia=intensidad)

    if not foto_mejorada:
        console.print("[red]Error al mejorar la foto[/red]")
        return

    console.print(f"[green]✓[/green] Foto mejorada: {foto_mejorada}")

    # Si se pide agregar texto
    resultado_final = foto_mejorada
    if hook:
        resultado_final = generar_post_desde_material(
            foto_mejorada, hook, cta, tipo_contenido=formato
        )
        if resultado_final:
            console.print(f"[green]✓[/green] Con texto: {resultado_final}")

    if telegram and resultado_final:
        from agente.telegram.notificador import _enviar_foto
        caption = f"<b>{hook}</b>\n\n{cta}" if hook else "Foto mejorada"
        result = _enviar_foto(resultado_final, caption=caption)
        if result.get("ok"):
            console.print("[green]✓[/green] Enviada a Telegram")


@cli.command()
@click.option("--pilar", default="lifestyle_y_comunidad",
              help="Pilar de contenido para generar las escenas IA")
@click.option("--mood", default="upbeat_latino",
              type=click.Choice(["upbeat_latino", "chill_food", "energetico", "humor"]),
              help="Mood de la música")
@click.option("--fuente", default="auto",
              type=click.Choice(["auto", "usuario", "ia"]),
              help="auto=usuario primero, ia=forzar generación IA, usuario=solo Drive")
@click.option("--telegram", is_flag=True, default=False, help="Enviar video a Telegram")
def generar_reel(pilar, mood, fuente, telegram):
    """Genera un Reel MP4 slideshow.

    Fuentes de material (en orden):
      auto    → fotos de Drive Posts/ primero, si no hay genera escenas IA
      usuario → solo fotos que subiste a Google Drive Posts/
      ia      → genera 4 escenas del producto con IA (FLUX Kontext)
    """
    from agente.generadores.video_automatico import generar_reel as _generar_reel
    from agente.generadores.imagen_compuesta import generar_escenas_para_video, _foto_referencia_completa
    from agente.media.google_drive import listar_material_local
    from config import settings, imagen_params as params

    console.print(Panel(
        f"[bold blue]Generando Reel slideshow[/bold blue]\n"
        f"Pilar: [cyan]{pilar}[/cyan] | Música: [cyan]{mood}[/cyan] | Fuente: [cyan]{fuente}[/cyan]"
    ))

    fotos: list = []

    if fuente in ("auto", "usuario"):
        fotos_drive = listar_material_local("Posts")
        fotos_drive = [p for p in fotos_drive
                       if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
        if fotos_drive:
            fotos = [str(p) for p in fotos_drive[:6]]
            console.print(f"  [green]✓[/green] {len(fotos)} foto(s) del usuario (Google Drive Posts/)")

    if not fotos and fuente in ("auto", "ia"):
        console.print("  Generando 4 escenas del producto con IA (FLUX Kontext)...")
        with console.status("Llamando a Fal.ai flux-pro/kontext..."):
            escenas = generar_escenas_para_video(
                pilar=pilar,
                n=4,
                formato="story",
            )
        if escenas:
            fotos = [str(p) for p in escenas]
            console.print(f"  [green]✓[/green] {len(fotos)} escenas generadas con IA")
        else:
            # Último fallback: foto de referencia del producto
            ref = _foto_referencia_completa()
            if ref:
                fotos = [str(ref)]
                console.print(f"  [yellow]⚠[/yellow] Usando foto de referencia como fallback")

    if not fotos:
        console.print("[red]Sin material disponible. Sube fotos a Drive Posts/ o configura FALAI_API_KEY.[/red]")
        return

    with console.status(f"Generando video con {len(fotos)} frame(s)... (30-90s)"):
        ruta_mp4 = _generar_reel(imagenes=fotos, mood_musica=mood)

    if ruta_mp4:
        tam_mb = ruta_mp4.stat().st_size / 1_048_576
        console.print(f"[green]✓[/green] Reel: {ruta_mp4.name}")
        console.print(f"  {tam_mb:.1f} MB | {len(fotos) * params.DURACION_IMAGEN_REEL_SEG:.0f}s aprox")

        if telegram:
            from agente.telegram.notificador import _enviar_video
            with console.status("Enviando a Telegram..."):
                result = _enviar_video(ruta_mp4, caption="Reel generado — revisar y aprobar")
            console.print("[green]✓ Telegram[/green]" if result.get("ok") else f"[red]Error Telegram: {result}[/red]")
    else:
        console.print("[red]Error al generar el reel[/red]")


@cli.command()
@click.option("--tema", default="curiosidades del picante",
              help="Tema del carrusel (ej: 'beneficios del chile', 'historia de la salsa')")
@click.option("--slides", default=5, type=int, help="Número de slides de contenido (1-8)")
@click.option("--telegram", is_flag=True, default=False, help="Enviar slides a Telegram para revisión")
def generar_carrusel(tema, slides, telegram):
    """Genera un carrusel educativo automático con Pillow + Claude (Camino B)."""
    from agente.generadores.generador_carrusel import generar_carrusel_educativo

    slides = max(1, min(8, slides))
    console.print(Panel(
        f"[bold blue]Generando carrusel educativo[/bold blue]\n"
        f"Tema: [cyan]{tema}[/cyan] | Slides de contenido: {slides}"
    ))

    with console.status(f"Claude generando {slides} datos + renderizando slides HTML→PNG..."):
        try:
            from agente.generadores.carrusel_html import generar_carrusel_html
            rutas = generar_carrusel_html(tema=tema, n_slides=slides)
        except Exception:
            # Fallback al generador Pillow si Playwright falla
            rutas = generar_carrusel_educativo(tema=tema, n_slides=slides)

    if not rutas:
        console.print("[red]Error al generar el carrusel[/red]")
        return

    console.print(f"[green]✓[/green] {len(rutas)} slides generados:")
    for ruta in rutas:
        console.print(f"  {ruta.name}")

    if telegram:
        from agente.telegram.notificador import _enviar_foto
        console.print("\nEnviando slides a Telegram...")
        for i, ruta in enumerate(rutas, 1):
            caption = f"Slide {i}/{len(rutas)} — {tema}"
            result = _enviar_foto(ruta, caption=caption)
            if result.get("ok"):
                console.print(f"  [green]✓[/green] Slide {i} enviado")
            else:
                console.print(f"  [red]✗[/red] Error slide {i}: {result}")


@cli.command()
@click.argument("imagen", type=click.Path(exists=True))
@click.option("--pilar", default="recetas_y_maridajes", help="Pilar de contenido para orientar el copy")
@click.option("--esperar", default=30, help="Minutos máximos esperando tu aprobación en Telegram")
def publicar_imagen(imagen, pilar, esperar):
    """
    Flujo completo: imagen tuya → caption Claude → aprobación Telegram → Instagram.

    IMAGEN: ruta a la foto que quieres publicar (JPG/PNG).

    El agente genera el caption, te lo envía a Telegram con la imagen
    para que lo revises. Si apruebas, publica en Instagram. Si rechazas, descarta.
    """
    import time, re, json
    import cloudinary
    import cloudinary.uploader
    import requests as req
    from agente.claude.cliente_claude import ClienteClaude
    from agente.telegram.notificador import _enviar_foto, _enviar_mensaje, BASE_URL

    imagen_path = Path(imagen)
    console.print(Panel(
        f"[bold blue]Publicar imagen — flujo con aprobación Telegram[/bold blue]\n"
        f"Imagen: [cyan]{imagen_path.name}[/cyan] | Pilar: [cyan]{pilar}[/cyan]"
    ))

    # ── 1. Generar caption con Claude ────────────────────────────────────────
    console.print("\n[bold]1/4[/bold] Generando caption con Claude...")
    cliente = ClienteClaude()

    PILARES_CONTEXTO = {
        "recetas_y_maridajes": "la foto muestra comida con salsa artesanal picante",
        "lifestyle_y_comunidad": "la foto muestra un momento de vida real con la salsa",
        "humor_picante": "la foto tiene humor relacionado con el picante",
        "behind_the_scenes": "la foto muestra el proceso artesanal de la salsa",
        "educacion_sobre_salsas": "la foto muestra ingredientes o el producto",
        "promociones_y_lanzamientos": "la foto muestra el producto para promoción",
        "testimonios_y_ugc": "la foto muestra a alguien disfrutando la salsa",
    }
    contexto_foto = PILARES_CONTEXTO.get(pilar, "la foto muestra el producto o comida con salsa picante")

    from config import brand_guidelines as brand

    caption_raw = cliente.generar(
        prompt_sistema=(
            "Eres el community manager de Salsas Bestial, marca colombiana de salsas artesanales picantes. "
            "Tu trabajo NO es vender el producto directamente — es hacer que la persona se identifique "
            "con la experiencia, el sabor y el estilo de vida. "
            "El copy debe hacer que quien lo lea piense: esto es exactamente lo que yo siento. "
            "Nunca menciones el nombre del producto de forma publicitaria. "
            "Tono: cercano, real, apasionado, directo."
        ),
        prompt_usuario=(
            f"Descripción de la foto: {contexto_foto}.\n\n"
            "Escribe un caption para Instagram donde:\n"
            "- Primera línea: una verdad o sensación con la que los amantes del picante se identifiquen al instante (sin emoji al inicio)\n"
            "- Cuerpo (2-3 líneas): habla de la EXPERIENCIA — el olor, el sabor, ese momento único\n"
            "- Quien lea debe sentir que NECESITA vivir eso\n"
            f"- Al final pon exactamente esta línea de CTA: Pídela aquí → {brand.LINK_COMPRA_WHATSAPP}\n"
            "- 15 hashtags relevantes mezcla español/inglés\n"
            "- Máximo 3 emojis, bien ubicados\n"
            "- Sin frases de venta directa ni mencionar la marca en el copy principal"
        ),
        temperatura=0.85,
        max_tokens=600,
    )
    caption = limpiar_caption(re.sub(r"\*\*(.+?)\*\*", r"\1", caption_raw))
    console.print("[green]✓[/green] Caption generado.")

    # ── 2. Enviar a Telegram para aprobación ─────────────────────────────────
    console.print("\n[bold]2/4[/bold] Enviando a Telegram para tu aprobación...")

    revision_id = f"rev_{int(time.time())}"
    botones = {
        "inline_keyboard": [[
            {"text": "✅ Aprobar y publicar", "callback_data": f"pub_aprobar:{revision_id}"},
            {"text": "❌ Rechazar", "callback_data": f"pub_rechazar:{revision_id}"},
        ]]
    }

    caption_preview = caption[:900] + "\n\n<i>Responde con los botones para aprobar o rechazar.</i>"
    result = _enviar_foto(imagen_path, caption=caption_preview, reply_markup=botones)

    if not result.get("ok"):
        console.print(f"[red]Error enviando a Telegram: {result}[/red]")
        return

    console.print(f"[green]✓[/green] Enviado a Telegram. Esperando tu respuesta (máx {esperar} min)...")
    console.print("[yellow]Revisa Telegram y aprueba o rechaza.[/yellow]")

    # ── 3. Esperar respuesta ─────────────────────────────────────────────────
    console.print("\n[bold]3/4[/bold] Esperando aprobación...")
    ultimo_offset = None
    decision = None
    deadline = time.time() + esperar * 60

    while time.time() < deadline:
        params = {"timeout": 20, "allowed_updates": ["callback_query"]}
        if ultimo_offset:
            params["offset"] = ultimo_offset

        resp = req.get(f"{BASE_URL}/getUpdates", params=params, timeout=35)
        updates = resp.json().get("result", [])

        for update in updates:
            ultimo_offset = update["update_id"] + 1
            cb = update.get("callback_query")
            if not cb:
                continue
            data = cb.get("data", "")
            if revision_id not in data:
                continue

            accion = data.split(":")[0]
            decision = "aprobar" if accion == "pub_aprobar" else "rechazar"

            # Confirmar al usuario en Telegram
            req.post(f"{BASE_URL}/answerCallbackQuery", data={
                "callback_query_id": cb["id"],
                "text": "✅ Publicando en Instagram..." if decision == "aprobar" else "❌ Descartado",
            }, timeout=10)
            break

        if decision:
            break

    if not decision:
        console.print(f"[yellow]Tiempo agotado ({esperar} min) sin respuesta. El contenido no se publicó.[/yellow]")
        _enviar_mensaje("⏰ Tiempo agotado — el contenido no fue aprobado a tiempo y no se publicó.")
        return

    if decision == "rechazar":
        console.print("[yellow]Rechazado. Pidiendo instrucciones de ajuste...[/yellow]")

        # Pedir al usuario qué cambiar
        msg_instruccion = _enviar_mensaje(
            "❌ <b>Rechazado.</b>\n\n"
            "Escríbeme qué quieres cambiar del caption.\n"
            "Ejemplos: <i>\"más corto\"</i>, <i>\"más directo\"</i>, <i>\"sin preguntas\"</i>, <i>\"tono más gracioso\"</i>\n\n"
            "Tienes 10 minutos para responder."
        )

        # Esperar respuesta de texto del usuario
        instruccion_ajuste = None
        deadline_ajuste = time.time() + 10 * 60
        ultimo_msg_id = msg_instruccion.get("result", {}).get("message_id", 0)

        while time.time() < deadline_ajuste:
            resp_txt = req.get(f"{BASE_URL}/getUpdates", params={
                "timeout": 20, "allowed_updates": ["message"],
                "offset": ultimo_offset or 0
            }, timeout=35)
            for update in resp_txt.json().get("result", []):
                ultimo_offset = update["update_id"] + 1
                msg = update.get("message", {})
                texto_usuario = msg.get("text", "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if texto_usuario and chat_id == str(settings.TELEGRAM_CHAT_ID):
                    instruccion_ajuste = texto_usuario
                    break
            if instruccion_ajuste:
                break

        if not instruccion_ajuste:
            console.print("[yellow]Sin instrucciones. Contenido descartado.[/yellow]")
            _enviar_mensaje("⏰ Sin respuesta. Contenido descartado.")
            return

        console.print(f"[cyan]Instrucción recibida: {instruccion_ajuste}[/cyan]")
        _enviar_mensaje(f"✍️ Ajustando caption: <i>{instruccion_ajuste}</i>...")

        # Reescribir con la instrucción
        caption2_raw = cliente.generar(
            prompt_sistema=(
                "Eres el community manager de Salsas Bestial. "
                "Reescribe el caption siguiendo exactamente la instrucción del usuario. "
                "Mantén el objetivo: la persona debe identificarse con la experiencia."
            ),
            prompt_usuario=(
                f"Caption anterior:\n{caption}\n\n"
                f"Instrucción del usuario: {instruccion_ajuste}\n\n"
                "Reescribe el caption aplicando esa instrucción. Mantén:\n"
                f"- CTA al final: Pídela aquí → {brand.LINK_COMPRA_WHATSAPP}\n"
                "- 15 hashtags\n"
                "- Máximo 3 emojis"
            ),
            temperatura=0.85,
            max_tokens=600,
        )
        caption2 = re.sub(r"\*\*(.+?)\*\*", r"\1", caption2_raw).replace("---", "").strip()

        revision_id2 = f"rev_{int(time.time())}_v2"
        botones2 = {
            "inline_keyboard": [[
                {"text": "✅ Aprobar y publicar", "callback_data": f"pub_aprobar:{revision_id2}"},
                {"text": "❌ Rechazar definitivo", "callback_data": f"pub_rechazar:{revision_id2}"},
            ]]
        }
        _enviar_foto(imagen_path, caption=caption2[:900] + "\n\n<i>Caption ajustado — aprueba o rechaza.</i>", reply_markup=botones2)
        console.print("[cyan]Caption ajustado enviado a Telegram.[/cyan]")

        # Esperar segunda respuesta
        decision2 = None
        deadline2 = time.time() + esperar * 60
        while time.time() < deadline2:
            params2 = {"timeout": 20, "allowed_updates": ["callback_query"], "offset": ultimo_offset or 0}
            resp2 = req.get(f"{BASE_URL}/getUpdates", params=params2, timeout=35)
            for update in resp2.json().get("result", []):
                ultimo_offset = update["update_id"] + 1
                cb2 = update.get("callback_query")
                if not cb2:
                    continue
                if revision_id2 not in cb2.get("data", ""):
                    continue
                accion2 = cb2["data"].split(":")[0]
                decision2 = "aprobar" if accion2 == "pub_aprobar" else "rechazar"
                req.post(f"{BASE_URL}/answerCallbackQuery", data={
                    "callback_query_id": cb2["id"],
                    "text": "✅ Publicando..." if decision2 == "aprobar" else "❌ Descartado",
                }, timeout=10)
                break
            if decision2:
                break

        if decision2 != "aprobar":
            console.print("[yellow]Segunda opción rechazada. No se publicó nada.[/yellow]")
            _enviar_mensaje("❌ Contenido descartado definitivamente.")
            return

        caption = caption2

    # ── 4. Publicar en Instagram ─────────────────────────────────────────────
    console.print("\n[bold]4/4[/bold] Publicando en Instagram...")

    # Subir a Cloudinary
    cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL)
    upload_result = cloudinary.uploader.upload(
        str(imagen_path),
        folder="salsas_bestial",
        resource_type="image"
    )
    url_imagen = upload_result["secure_url"]

    # Crear container
    r2 = req.post(
        f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",
        data={"image_url": url_imagen, "caption": caption, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
        timeout=60
    )
    if r2.status_code != 200:
        console.print(f"[red]Error creando container: {r2.json()}[/red]")
        _enviar_mensaje(f"❌ Error publicando en Instagram:\n{r2.json().get('error', {}).get('message', '')}")
        return

    creation_id = r2.json()["id"]

    # Publicar
    r3 = req.post(
        f"https://graph.facebook.com/v21.0/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
        timeout=60
    )
    if r3.status_code == 200:
        media_id = r3.json()["id"]
        console.print(f"\n[green bold]✓ Publicado en Instagram[/green bold] — media_id: {media_id}")
        _enviar_mensaje(
            f"📸 <b>Publicado en Instagram</b>\n\n"
            f"<a href='https://www.instagram.com/salsas.bestial/'>Ver en @salsas.bestial →</a>"
        )
    else:
        console.print(f"[red]Error publicando: {r3.json()}[/red]")
        _enviar_mensaje(f"❌ Error al publicar:\n{r3.json().get('error', {}).get('message', '')}")


@cli.command()
@click.option("--pilar", default="lifestyle_y_comunidad", help="Pilar de contenido para el copy")
def publicar_carpeta(pilar):
    """
    Escanea Posts/ Stories/ Reels/ de Google Drive y agrega archivos nuevos a la biblioteca.

    Los archivos se encolan para publicación automática según el horario.
    Ya publicados se registran en datos/archivos_publicados.json para no repetirlos.

    \b
    Posts/   → post del feed (imagen)
    Stories/ → Story (imagen o video)
    Reels/   → Reel (video, con caption)
    """
    import re, json
    from agente.claude.cliente_claude import ClienteClaude
    from agente.telegram.notificador import _enviar_mensaje
    from agente.media.google_drive import listar_material_local, EXTENSIONES_IMAGEN, EXTENSIONES_VIDEO
    from agente.gestores.biblioteca import agregar_item, EXTENSIONES_IMAGEN as BIB_IMG, EXTENSIONES_VIDEO as BIB_VID
    from config import brand_guidelines as brand

    # ── Registro de archivos ya publicados ──────────────────────────────────
    registro_path = settings.DATOS_DIR / "archivos_publicados.json"
    if registro_path.exists():
        publicados = set(json.loads(registro_path.read_text(encoding="utf-8")).get("publicados", []))
    else:
        publicados = set()

    def _guardar_registro():
        registro_path.write_text(
            json.dumps({"publicados": sorted(publicados)}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    # ── Escanear carpetas ────────────────────────────────────────────────────
    carpetas = {
        "Posts":   ("post",   list(EXTENSIONES_IMAGEN)),
        "Stories": ("story",  list(EXTENSIONES_IMAGEN | EXTENSIONES_VIDEO)),
        "Reels":   ("reel",   list(EXTENSIONES_VIDEO)),
    }

    total_nuevos = 0
    total_agregados = 0
    cliente = ClienteClaude()
    resumen_lineas = []

    for nombre_carpeta, (tipo_pub, exts_validas) in carpetas.items():
        archivos = listar_material_local(nombre_carpeta)
        archivos = [a for a in archivos if a.suffix.lower() in set(exts_validas)]
        nuevos = [a for a in archivos if a.name not in publicados]

        if not nuevos:
            continue

        console.print(f"\n[bold cyan]{nombre_carpeta}/[/bold cyan] — {len(nuevos)} archivo(s) nuevo(s)")

        for idx, archivo in enumerate(nuevos, 1):
            total_nuevos += 1
            es_video = archivo.suffix.lower() in EXTENSIONES_VIDEO
            etiqueta = f"{tipo_pub.upper()} {idx}/{len(nuevos)}"
            console.print(f"\n  [{etiqueta}] {archivo.name[:40]}")

            # ── Generar caption (solo para posts y reels) ─────────────────
            caption = ""
            if tipo_pub in ("post", "reel"):
                console.print("  Generando caption con Claude...")
                caption_raw = cliente.generar(
                    prompt_sistema=(
                        "Eres el community manager de Salsas Bestial, marca colombiana de salsas picantes artesanales. "
                        "Tu trabajo es hacer que la persona se identifique con la experiencia del picante. "
                        "Tono: cercano, real, apasionado, directo. Sin frases publicitarias genéricas."
                    ),
                    prompt_usuario=(
                        f"Tipo de publicación: {tipo_pub.upper()}.\n"
                        f"Pilar de contenido: {pilar}.\n\n"
                        "Escribe un caption para Instagram:\n"
                        "- Primera línea: verdad o sensación que los amantes del picante reconocen al instante\n"
                        "- Cuerpo (2-3 líneas): la experiencia — olor, sabor, el momento\n"
                        f"- CTA final exacto: Pídela aquí → {brand.LINK_COMPRA_WHATSAPP}\n"
                        "- 15 hashtags mezcla español/inglés\n"
                        "- Máximo 3 emojis"
                    ),
                    temperatura=0.85,
                    max_tokens=600,
                )
                caption = limpiar_caption(re.sub(r"\*\*(.+?)\*\*", r"\1", caption_raw))

            # ── Agregar a biblioteca ──────────────────────────────────────
            item = agregar_item(archivo, tipo_pub, pilar, caption=caption)
            console.print(f"  [green]✓[/green] Biblioteca → {item.id}")
            publicados.add(archivo.name)
            _guardar_registro()
            total_agregados += 1
            emoji = {"post": "📸", "reel": "🎬", "story": "⭕"}.get(tipo_pub, "📁")
            resumen_lineas.append(f"{emoji} {tipo_pub.upper()}: {archivo.name[:35]}")

    if total_nuevos == 0:
        console.print("[yellow]No hay archivos nuevos en Posts/, Stories/ ni Reels/.[/yellow]")
        console.print("Sube contenido a Google Drive y vuelve a ejecutar.")
    else:
        console.print(f"\n[green]✓[/green] {total_agregados}/{total_nuevos} archivo(s) en la biblioteca.")
        resumen = "\n".join(resumen_lineas)
        _enviar_mensaje(
            f"📚 <b>{total_agregados} archivo(s) en la biblioteca</b>\n\n"
            f"{resumen}\n\n"
            "Se publicarán según el horario programado.\n"
            "Usa /estado para ver la cola."
        )


@cli.command()
def configurar_drive():
    """Instrucciones para conectar Google Drive para material desde el celular."""
    console.print(Panel(
        "[bold]Configuración Google Drive — Material desde celular[/bold]\n\n"
        "[cyan]OPCIÓN A — Google Drive for Desktop (MÁS SIMPLE)[/cyan]\n"
        "1. Instala: drive.google.com/drive/downloads\n"
        "2. Crea una carpeta llamada: [bold]Salsas Bestial - Instagram[/bold]\n"
        "3. Dentro crea subcarpetas: [bold]Posts/ Reels/ Stories/ Fotos-Producto/[/bold]\n"
        "4. En el .env agrega la ruta local donde se sincroniza:\n"
        "   [bold]GOOGLE_DRIVE_LOCAL_PATH=G:/Mi unidad/Salsas Bestial - Instagram[/bold]\n"
        "   (la letra del disco puede ser D:, G:, etc — la que asignó Drive)\n\n"
        "[cyan]Desde el celular:[/cyan]\n"
        "   Abre Google Drive → entra a la carpeta → sube foto/video\n"
        "   El agente la usa automáticamente en la próxima semana\n\n"
        "[cyan]OPCIÓN B — Sin Drive Desktop (solo GitHub Actions)[/cyan]\n"
        "   Requiere configuración adicional (service account).\n"
        "   Escríbeme y te explico paso a paso.",
        title="📱 Google Drive Setup",
    ))


@cli.command()
def bot():
    """Inicia el bot de Telegram — interfaz principal del agente."""
    from agente.telegram.bot import BotTelegram
    console.print(Panel(
        "[bold green]Bot de Telegram iniciado[/bold green]\n\n"
        "Manda fotos/videos desde tu celular al bot.\n"
        "Comandos disponibles en Telegram:\n"
        "  /carrusel <tema> — carrusel educativo HTML→PNG\n"
        "  /estado — ver biblioteca de contenido\n"
        "  /ayuda — ver todos los comandos\n\n"
        "[yellow]Ctrl+C para detener[/yellow]",
        title="🤖 Agente Salsas Bestial"
    ))
    BotTelegram().ejecutar()


@cli.command()
@click.option("--forzar", is_flag=True, default=False,
              help="Publica ahora sin verificar el horario (tipo=reel por defecto)")
@click.option("--tipo", default=None, type=str,
              help="Tipo forzado: reel|post|story|carrusel")
def publicar_programado(forzar: bool = False, tipo: str | None = None):
    """
    Publica el siguiente item de la biblioteca según el horario del día.

    Horario:
      Lunes, Miércoles, Viernes → Story 9am + Post 12pm
      Martes, Jueves             → Reel 7pm

    GitHub Actions ejecuta este comando en los horarios configurados.
    Envía preview a Telegram 10 minutos antes de publicar.
    Usa --forzar para publicar fuera del horario (útil para pruebas manuales).
    """
    import datetime
    import json
    import time as _time
    import requests as req
    from zoneinfo import ZoneInfo
    from agente.gestores.biblioteca import (
        siguiente_pendiente, marcar_publicado, marcar_descartado, contar_pendientes
    )
    from agente.telegram.notificador import (
        _enviar_foto, _enviar_mensaje, _enviar_foto_url, _enviar_video_url, BASE_URL
    )

    # Siempre hora Colombia (UTC-5) — funciona igual local y en GitHub Actions (Ubuntu UTC)
    tz_col = ZoneInfo("America/Bogota")
    ahora = datetime.datetime.now(tz_col)
    dia_semana = ahora.weekday()  # 0=lun ... 6=dom
    hora = ahora.hour

    # Dos slots por día, todos los días.
    # Ventanas AMPLIAS para absorber los retrasos de GitHub Actions (puede llegar
    # horas tarde). El cron dispara ~11:30am y ~6:30pm COL; las ventanas cubren
    # desde 1 h antes hasta 3 h después para no quedar "fuera de horario".
    #   Mediodía (10-16 COL) → post o carrusel
    #   Noche    (17-23 COL) → reel o story
    HORARIO = {
        # (dia_semana, hora_min, hora_max): tipo_preferido
        (0, 10, 16): "post",      # Lunes mediodía
        (0, 17, 23): "reel",      # Lunes noche
        (1, 10, 16): "post",      # Martes mediodía
        (1, 17, 23): "reel",      # Martes noche
        (2, 10, 16): "carrusel",  # Miércoles mediodía ← slot dedicado a carrusel
        (2, 17, 23): "story",     # Miércoles noche
        (3, 10, 16): "reel",      # Jueves mediodía
        (3, 17, 23): "story",     # Jueves noche
        (4, 10, 16): "post",      # Viernes mediodía
        (4, 17, 23): "reel",      # Viernes noche
        (5, 10, 16): "post",      # Sábado mediodía
        (5, 17, 23): "story",     # Sábado noche
        (6, 10, 16): "story",     # Domingo mediodía
        (6, 17, 23): "story",     # Domingo noche
    }

    tipo_pub = None
    for (dia, h_min, h_max), _tipo in HORARIO.items():
        if dia_semana == dia and h_min <= hora < h_max:
            tipo_pub = _tipo
            break

    if not tipo_pub:
        if forzar:
            tipo_pub = tipo or "reel"
            console.print(f"[yellow]⚡ Publicación forzada ({ahora.strftime('%A %H:%M')} COL) — tipo: {tipo_pub}[/yellow]")
        else:
            console.print(f"[yellow]Fuera de horario ({ahora.strftime('%A %H:%M')} COL). No se publica nada.[/yellow]")
            return

    # Si se pasó --tipo explícitamente, sobreescribir el tipo del horario
    if tipo:
        tipo_pub = tipo

    # Verificar si el usuario pausó este slot desde Telegram (/hoy)
    pausas_path = Path("datos/pausas_hoy.json")
    if pausas_path.exists():
        try:
            pausas = json.loads(pausas_path.read_text(encoding="utf-8"))
            fecha_hoy = ahora.strftime("%Y-%m-%d")
            if pausas.get("fecha") == fecha_hoy:
                if pausas.get("pausado_todo"):
                    console.print("[yellow]Publicación pausada por el usuario para hoy — saliendo.[/yellow]")
                    _enviar_mensaje("⏭ Slot pausado — no se publicó nada en este horario.")
                    return
                # Buscar el h_min del slot actual
                slot_h_min = None
                for (d, h_min_s, h_max_s), t in HORARIO.items():
                    if d == dia_semana and h_min_s <= hora < h_max_s:
                        slot_h_min = h_min_s
                        break
                if slot_h_min in pausas.get("slots_pausados", []):
                    hora_label = "12pm" if slot_h_min < 15 else "7pm"
                    console.print(f"[yellow]Slot {hora_label} pausado por el usuario — saliendo.[/yellow]")
                    _enviar_mensaje(f"⏭ Slot {hora_label} pausado — no se publicó nada.")
                    return
        except Exception as e:
            console.print(f"[yellow]No se pudo leer pausas_hoy.json: {e}[/yellow]")

    console.print(Panel(
        f"[bold blue]Publicación programada[/bold blue]\n"
        f"Día: {ahora.strftime('%A')} | Hora: {ahora.strftime('%H:%M')} COL | Tipo: {tipo_pub.upper()}"
    ))

    # Verificar si el usuario aprobó un ítem específico para este slot
    fecha_hoy = ahora.strftime("%Y-%m-%d")
    aprobaciones_path = Path("datos/aprobaciones_hoy.json")
    item_aprobado_id = None
    if aprobaciones_path.exists():
        try:
            aprobaciones = json.loads(aprobaciones_path.read_text(encoding="utf-8"))
            if aprobaciones.get("fecha") == fecha_hoy:
                # Buscar h_min del slot actual
                slot_h_min_apr = None
                for (d, h_min_s, h_max_s), _ in HORARIO.items():
                    if d == dia_semana and h_min_s <= hora < h_max_s:
                        slot_h_min_apr = h_min_s
                        break
                if slot_h_min_apr is not None:
                    item_aprobado_id = aprobaciones.get("aprobados", {}).get(str(slot_h_min_apr))
        except Exception as e:
            console.print(f"[yellow]No se pudo leer aprobaciones_hoy.json: {e}[/yellow]")

    # Intentar tipo preferido; si no hay, cualquier tipo disponible
    # Si hay un ítem aprobado específico, usarlo directamente
    from agente.gestores.biblioteca import (
        listar_pendientes as _listar_pendientes,
        siguiente_carrusel_pendiente as _sig_carrusel,
    )

    # ── Temas rotativos para carruseles auto-generados ────────────────────────
    TEMAS_CARRUSEL = [
        "curiosidades del chile habanero",
        "beneficios de comer picante",
        "historia de las salsas picantes en Latinoamérica",
        "tipos de chile y su nivel de picante",
        "por qué el picante es adictivo",
        "maridajes perfectos para salsas artesanales",
        "cómo se hace una salsa tatemada",
        "diferencia entre salsa fresca y salsa ahumada",
        "el chile más picante del mundo",
        "rituales del picante en Colombia y México",
    ]

    item = None
    if item_aprobado_id:
        todos_pendientes = _listar_pendientes()
        item = next((i for i in todos_pendientes if i.id == item_aprobado_id), None)
        if item:
            console.print(f"[green]✅ Publicando ítem aprobado: {item_aprobado_id}[/green]")
        else:
            console.print(f"[yellow]Ítem aprobado {item_aprobado_id} no encontrado en pendientes — usando siguiente disponible[/yellow]")

    if not item:
        if tipo_pub == "carrusel":
            # Slot dedicado a carrusel (miércoles mediodía):
            # 1. Buscar cualquier carrusel pendiente en la biblioteca
            # 2. Si no hay ninguno → auto-generar un carrusel de datos curiosos
            item = _sig_carrusel()
            if item:
                console.print(f"[green]📖 Carrusel pendiente encontrado: {item.id}[/green]")
                tipo_pub = "post"  # Los carruseles se publican como tipo post
            else:
                console.print("[yellow]Sin carruseles en biblioteca — generando carrusel de datos curiosos...[/yellow]")
                try:
                    import random as _random
                    from agente.generadores.carrusel_html import generar_carrusel_html
                    from agente.gestores.biblioteca import agregar_carrusel
                    tema_auto = _random.choice(TEMAS_CARRUSEL)
                    _enviar_mensaje(f"📚 <b>Miércoles = día de carrusel</b>\n\nNo hay carruseles en biblioteca — generando uno automático sobre:\n<b>{tema_auto}</b> 🌶️")
                    console.print(f"  Tema: '{tema_auto}'")
                    rutas_auto = generar_carrusel_html(tema=tema_auto, n_slides=3, pilar="educacion_sobre_salsas")
                    if rutas_auto:
                        item = agregar_carrusel(rutas_auto, tipo="post", pilar="educacion_sobre_salsas")
                        console.print(f"  [green]✓[/green] Carrusel auto-generado: {len(rutas_auto)} slides → {item.id}")
                        _enviar_mensaje(f"✅ Carrusel generado ({len(rutas_auto)} slides). Publicando...")
                        tipo_pub = "post"
                    else:
                        raise RuntimeError("No se generaron slides")
                except Exception as e:
                    console.print(f"  [red]Error generando carrusel automático: {e}[/red]")
                    # Fallback: publicar cualquier post disponible
                    item = siguiente_pendiente("post")
                    if item:
                        tipo_pub = "post"
                        console.print("[yellow]Fallback → publicando post disponible en lugar del carrusel[/yellow]")
        else:
            item = siguiente_pendiente(tipo_pub)

    if not item:
        for tipo_alt in ["post", "reel", "story"]:
            if tipo_alt != tipo_pub:
                item_alt = siguiente_pendiente(tipo_alt)
                if item_alt:
                    console.print(f"[yellow]No hay {tipo_pub}s — usando {tipo_alt.upper()} disponible[/yellow]")
                    tipo_pub = tipo_alt
                    item = item_alt
                    break
    if not item:
        conteo = contar_pendientes()
        console.print(f"[yellow]No hay {tipo_pub}s pendientes. Intentando generar carrusel de emergencia...[/yellow]")

        # ── Fallback automático: generar carrusel educativo ───────────────────
        if tipo_pub == "post":
            try:
                from agente.generadores.carrusel_html import generar_carrusel_html
                from agente.gestores.biblioteca import agregar_carrusel
                import random

                TEMAS_FALLBACK = [
                    "curiosidades del chile habanero",
                    "beneficios de comer picante",
                    "historia de las salsas picantes en México",
                    "tipos de chile y su nivel de picante",
                    "por qué el picante es adictivo",
                    "maridajes perfectos para salsas artesanales",
                    "cómo se hace una salsa tatemada",
                    "diferencia entre salsa fresca y salsa ahumada",
                    "el chile más picante del mundo",
                    "rituales del picante en Latinoamérica",
                ]
                tema = random.choice(TEMAS_FALLBACK)
                console.print(f"  Generando carrusel: '{tema}'...")
                _enviar_mensaje(f"📚 Sin material en biblioteca — generando carrusel automático sobre: <b>{tema}</b>")

                rutas = generar_carrusel_html(tema=tema, n_slides=3, pilar="educacion_sobre_salsas")
                if rutas:
                    item = agregar_carrusel(rutas, tipo="post", pilar="educacion_sobre_salsas")
                    console.print(f"  [green]✓[/green] Carrusel generado: {len(rutas)} slides → {item.id}")
                    _enviar_mensaje(f"✅ Carrusel generado ({len(rutas)} slides). Publicando...")
                else:
                    raise RuntimeError("No se generaron slides")
            except Exception as e:
                console.print(f"  [red]Error generando carrusel fallback: {e}[/red]")
                _enviar_mensaje(
                    f"⚠️ <b>Sin material</b> — no hay {tipo_pub.upper()}s ni se pudo generar contenido.\n"
                    f"Posts: {conteo['post']} | Reels: {conteo['reel']} | Stories: {conteo['story']}"
                )
                return
        else:
            # Para reels y stories no hay generación automática — solo avisar
            _enviar_mensaje(
                f"⚠️ <b>Sin material en biblioteca</b>\n\n"
                f"No hay {tipo_pub.upper()}s listos para publicar hoy.\n"
                f"Mándame fotos/videos al bot para cargar la biblioteca.\n\n"
                f"Posts: {conteo['post']} | Reels: {conteo['reel']} | Stories: {conteo['story']}"
            )
            return

    # ── Verificar archivo existe (local o Cloudinary) ────────────────────────
    ruta = None
    cloudinary_url = getattr(item, "cloudinary_url", "")
    if not item.es_carrusel:
        ruta = Path(item.ruta_local)
        if not ruta.exists() and not cloudinary_url:
            console.print(f"[red]Archivo no encontrado ni en disco ni en Cloudinary: {item.nombre_archivo}[/red]")
            marcar_descartado(item.id)
            return
        if not ruta.exists():
            ruta = None  # Usar cloudinary_url directamente

    tipo_label = {"post": "📸 POST", "reel": "🎬 REEL", "story": "⭕ STORY"}.get(tipo_pub, tipo_pub.upper())

    # Generar caption si no tiene (post, reel y story)
    if not item.caption:
        from agente.claude.cliente_claude import ClienteClaude
        from config import brand_guidelines as brand
        import re
        import logging as _logging
        _log = _logging.getLogger("publicar_programado")

        try:
            cliente = ClienteClaude()

            if tipo_pub == "story":
                caption_raw = cliente.generar(
                    prompt_sistema=(
                        "Eres el community manager de Salsas Bestial. "
                        "Escribes textos breves, directos y con personalidad para Stories de Instagram."
                    ),
                    prompt_usuario=(
                        f"Pilar: {item.pilar}.\n"
                        "Escribe el texto para una Story de Instagram de Salsas Bestial:\n"
                        "- 1 línea impactante (máx 10 palabras) — lo que se ve en la pantalla\n"
                        "- 1 línea de CTA corta: 'Pídela 👇' o 'Desliza para pedir 🌶️'\n"
                        "- Sin hashtags (las stories no los necesitan)\n"
                        "- Máximo 2 emojis\n"
                        "Formato: solo el texto, sin explicaciones."
                    ),
                    temperatura=0.85,
                    max_tokens=150,
                )
            else:
                caption_raw = cliente.generar(
                    prompt_sistema=(
                        "Eres el community manager de Salsas Bestial. "
                        "Haz que la persona se identifique con la experiencia del picante."
                    ),
                    prompt_usuario=(
                        f"Tipo: {tipo_pub.upper()}. Pilar: {item.pilar}.\n"
                        "Caption para Instagram:\n"
                        "- Primera línea: verdad que los amantes del picante reconocen\n"
                        "- Cuerpo (2-3 líneas): la experiencia\n"
                        f"- CTA de compra: Pídela aquí → {brand.LINK_COMPRA_WHATSAPP}\n"
                        f"- Pregunta de cierre (OBLIGATORIA, última línea antes de hashtags): elige la más apropiada de esta lista: {brand.PREGUNTAS_ENGAGEMENT}\n"
                        f"- Usa exactamente estos hashtags al final (mezcla nicho/amplio ya seleccionada): {' '.join(brand.seleccionar_hashtags())}\n"
                        "- Máximo 3 emojis"
                    ),
                    temperatura=0.85,
                    max_tokens=600,
                )

            caption_limpio = limpiar_caption(re.sub(r"\*\*(.+?)\*\*", r"\1", caption_raw))
            _log.info("Caption generado (%d chars): %s", len(caption_limpio), caption_limpio[:80])

            # Fallback: si limpiar_caption devolvió vacío, usar el texto crudo
            if not caption_limpio.strip():
                _log.warning("limpiar_caption devolvió vacío — usando caption_raw sin limpiar")
                caption_limpio = caption_raw.strip()

            item.caption = caption_limpio

        except Exception as _e:
            _log.error("Error generando caption con Claude: %s", _e, exc_info=True)
            _enviar_mensaje(f"⚠️ No se pudo generar el caption automáticamente: <code>{str(_e)[:200]}</code>\nSe publicará sin texto.")

        # Guardar caption generado en biblioteca para que persista entre runs
        if item.caption:
            try:
                from agente.gestores.biblioteca import _cargar, _guardar
                _data = _cargar()
                for _raw in _data["items"]:
                    if _raw["id"] == item.id:
                        _raw["caption"] = item.caption
                        break
                _guardar(_data)
                _log.info("Caption guardado en biblioteca para item %s", item.id)
            except Exception as _e2:
                _log.warning("No se pudo guardar caption en biblioteca: %s", _e2)

    # ── Helper interno para publicar y notificar ─────────────────────────────
    def _ejecutar_publicacion(item_pub, tipo_pub_str):
        from agente.instagram.publicar_item import publicar_item as _pub
        emoji_t = {"post": "📸", "reel": "🎬", "story": "⭕"}.get(tipo_pub_str, "📌")
        console.print(f"Publicando {tipo_pub_str.upper()}...")
        mid = _pub(item_pub)
        if mid == "SIN_MEDIA":
            marcar_descartado(item_pub.id)
            console.print("[yellow]Item descartado — sin archivo ni URL[/yellow]")
            _enviar_mensaje(f"⚠️ {tipo_pub_str.upper()} descartado — no tiene archivo ni URL.")
        elif mid:
            marcar_publicado(item_pub.id, mid)
            console.print(f"[green bold]✓ Publicado[/green bold] — media_id: {mid}")
            _enviar_mensaje(
                f"{emoji_t} <b>{tipo_pub_str.upper()} publicado</b>\n"
                f"<a href='https://www.instagram.com/salsas.bestial/'>Ver en @salsas.bestial →</a>"
            )
        else:
            console.print("[red]Error al publicar[/red]")
            _enviar_mensaje(f"❌ Error publicando {tipo_pub_str.upper()}. Revisa los logs.")

    # ── Helper para carruseles: enviar slides + caption a Telegram (subida manual) ──
    # Los carruseles NO se publican automáticamente — el usuario los sube desde
    # la app de Instagram para poder agregar música. El sistema sólo envía el
    # material y el caption, y marca el item como publicado para no repetirlo.
    def _enviar_carrusel_manual(item_pub):
        slide_urls = [
            u.strip()
            for u in (item_pub.cloudinary_url or "").split(",")
            if u.strip().startswith("http")
        ]
        n = len(slide_urls)
        if n == 0:
            console.print("[yellow]Carrusel sin URLs de Cloudinary — no se puede enviar[/yellow]")
            _enviar_mensaje(
                "⚠️ <b>Carrusel sin imágenes</b>\n\n"
                "No se encontraron URLs de Cloudinary para este carrusel.\n"
                "Usa /estado para revisar el item."
            )
            return

        console.print(f"[cyan]Enviando carrusel manual ({n} slides) a Telegram...[/cyan]")
        _enviar_mensaje(
            f"📖 <b>CARRUSEL listo para subir</b> ({n} slides)\n\n"
            f"<b>Pasos:</b>\n"
            f"1️⃣ Guarda las {n} fotos que te envío abajo\n"
            f"2️⃣ Abre Instagram → <b>+</b> → elige las {n} fotos <b>en orden</b>\n"
            f"3️⃣ Agrega música desde la app 🎵\n"
            f"4️⃣ Copia el caption de abajo y pégalo en Instagram\n\n"
            f"⚠️ Se marca como publicado al recibir este mensaje — no se volverá a mostrar."
        )
        for i, url in enumerate(slide_urls, 1):
            try:
                _enviar_foto_url(url, caption=f"Slide {i}/{n}")
                _time.sleep(0.5)
            except Exception as _se:
                console.print(f"[yellow]Error enviando slide {i}: {_se}[/yellow]")

        caption_carrusel = item_pub.caption or ""
        if caption_carrusel:
            # Telegram limita mensajes a 4096 chars; el caption ya es corto
            _enviar_mensaje(
                f"📋 <b>Caption — copia y pega en Instagram:</b>\n\n{caption_carrusel}"
            )
        else:
            _enviar_mensaje("ℹ️ Este carrusel no tiene caption guardado.")

        marcar_publicado(item_pub.id)
        console.print("[green bold]✓ Carrusel enviado para subida manual — marcado como publicado[/green bold]")

    # ── Flujo A: item pre-aprobado desde /hoy → publicar DIRECTAMENTE ────────
    # Esto evita la race condition donde el bot consume la respuesta del usuario
    # antes de que el workflow de publicación la reciba.
    if item_aprobado_id and item.id == item_aprobado_id:
        slot_label_a = "mediodía" if hora < 16 else "noche"
        console.print(f"[green bold]✅ Pre-aprobado desde /hoy — publicando directamente (sin preview)[/green bold]")
        if item.es_carrusel:
            _enviar_mensaje(
                f"📖 <b>Carrusel listo</b> — slot {slot_label_a}\n"
                f"Aprobado desde /hoy · enviando slides para subida manual con música..."
            )
            _enviar_carrusel_manual(item)
        else:
            _enviar_mensaje(
                f"🚀 <b>Publicando {tipo_label}</b> — slot {slot_label_a}\n"
                f"Aprobado previamente desde /hoy · publicando ahora..."
            )
            _ejecutar_publicacion(item, tipo_pub)
        return

    # ── Flujo B: sin pre-aprobación → enviar preview y esperar tap (20 min) ──
    # Nota: el bot de Telegram corre 24/7 con el mismo token. Si el usuario
    # aprueba mientras el bot está activo, hay posibilidad de race condition.
    # Para evitarla, SIEMPRE usa /hoy para aprobar ANTES de que corra el workflow.

    # ── Convertir imagen a video con música ANTES del preview ────────────────
    # Las imágenes estáticas no tienen música vía Instagram Graph API.
    # Convertimos a MP4 aquí para que el usuario vea el resultado final antes
    # de aprobar, y guardamos el video en biblioteca para no re-convertir al publicar.
    if not item.es_carrusel:
        _nombre_lower = item.nombre_archivo.lower()
        _es_imagen_preview = not any(_nombre_lower.endswith(e) for e in (".mp4", ".mov", ".avi", ".m4v"))
        if _es_imagen_preview:
            console.print("[cyan]Convirtiendo imagen a video con música para preview...[/cyan]")
            _enviar_mensaje("⏳ Preparando preview con música… (esto puede tardar ~30 seg)")

            _ruta_para_conv = ruta  # Path local o None

            # Si no tenemos el archivo localmente, descargarlo de Cloudinary
            if (_ruta_para_conv is None or not _ruta_para_conv.exists()) and cloudinary_url:
                import tempfile
                import urllib.request as _urllib
                try:
                    _ext_dl = Path(cloudinary_url.split("?")[0]).suffix or ".jpg"
                    _tmp = Path(tempfile.mktemp(suffix=_ext_dl))
                    _urllib.urlretrieve(cloudinary_url, _tmp)
                    _ruta_para_conv = _tmp
                except Exception as _dl_err:
                    console.print(f"[yellow]No se pudo descargar imagen de Cloudinary: {_dl_err}[/yellow]")
                    _ruta_para_conv = None

            if _ruta_para_conv and _ruta_para_conv.exists():
                try:
                    import cloudinary as _cld
                    _cld.config(cloudinary_url=settings.CLOUDINARY_URL)
                    from agente.instagram.publicar_item import _imagen_a_reel_cloudinary
                    _nuevo_video_url = _imagen_a_reel_cloudinary(_ruta_para_conv, item.pilar or "lifestyle_y_comunidad")
                    if _nuevo_video_url:
                        # Actualizar item en memoria y en biblioteca
                        cloudinary_url = _nuevo_video_url
                        item.cloudinary_url = _nuevo_video_url
                        _nombre_base = Path(item.nombre_archivo).stem
                        item.nombre_archivo = _nombre_base + ".mp4"
                        try:
                            from agente.gestores.biblioteca import _cargar, _guardar
                            _bib = _cargar()
                            for _raw in _bib["items"]:
                                if _raw["id"] == item.id:
                                    _raw["cloudinary_url"] = _nuevo_video_url
                                    _raw["nombre_archivo"] = item.nombre_archivo
                                    break
                            _guardar(_bib)
                            console.print("[green]✓[/green] Video con música guardado en biblioteca")
                        except Exception as _sv_err:
                            console.print(f"[yellow]No se pudo guardar video en biblioteca: {_sv_err}[/yellow]")
                        # Limpiar archivo temporal si se descargó
                        if _ruta_para_conv != ruta:
                            try:
                                _ruta_para_conv.unlink(missing_ok=True)
                            except Exception:
                                pass
                        ruta = None  # usar cloudinary_url para el preview
                    else:
                        console.print("[yellow]No se pudo convertir a video — se enviará imagen estática[/yellow]")
                except Exception as _conv_err:
                    console.print(f"[yellow]Error convirtiendo imagen a video: {_conv_err}[/yellow]")
            else:
                console.print("[yellow]Sin archivo local para convertir — se enviará imagen estática[/yellow]")

    rev_id = f"prog_{int(_time.time())}"
    slot_label = "mediodía" if hora < 16 else "noche"
    texto_prev = (
        f"🗓 <b>Publicación programada — {tipo_label}</b>\n"
        f"📅 Slot <b>{slot_label}</b> · {ahora.strftime('%a %d/%m %H:%M')} COL\n"
        f"💡 <i>Tip: aprueba desde /hoy antes de las 11:30am/6:30pm para evitar tener que responder aquí</i>\n\n"
        + (f"{item.caption[:600]}\n\n" if item.caption else "")
        + "👆 <b>¿Publicar este contenido?</b>"
    )
    botones = {"inline_keyboard": [[
        {"text": "✅ Publicar ahora", "callback_data": f"prog_si:{rev_id}"},
        {"text": "⏭ Saltar",         "callback_data": f"prog_no:{rev_id}"},
    ]]}

    # Enviar preview con el media real cuando existe
    _preview_enviado = False

    # Carrusel: enviar primer slide + resto como álbum sin botones, luego texto con botones
    if item.es_carrusel and cloudinary_url:
        _slide_urls = [u.strip() for u in cloudinary_url.split(",") if u.strip().startswith("http")]
        if _slide_urls:
            # Primer slide con caption + botones
            r = _enviar_foto_url(_slide_urls[0], caption=texto_prev, reply_markup=botones)
            _preview_enviado = r.get("ok", False)
            # Slides restantes sin caption (hasta 9 más = 10 total)
            for _su in _slide_urls[1:9]:
                _enviar_foto_url(_su, caption="")
                import time as _t; _t.sleep(0.3)

    if not _preview_enviado and cloudinary_url:
        nombre = item.nombre_archivo.lower()
        es_video_url = any(nombre.endswith(ext) for ext in (".mp4", ".mov", ".avi", ".m4v"))
        if es_video_url:
            r = _enviar_video_url(cloudinary_url, caption=texto_prev, reply_markup=botones)
            _preview_enviado = r.get("ok", False)
        else:
            r = _enviar_foto_url(cloudinary_url, caption=texto_prev, reply_markup=botones)
            _preview_enviado = r.get("ok", False)

    if not _preview_enviado and ruta and ruta.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        _enviar_foto(ruta, caption=texto_prev, reply_markup=botones)
        _preview_enviado = True

    if not _preview_enviado:
        _enviar_mensaje(texto_prev, reply_markup=botones)

    console.print("Preview enviado a Telegram. Esperando aprobación (20 min)...")

    # ── Esperar respuesta hasta 20 minutos ────────────────────────────────────
    # Prefijos prog_si / prog_no son distintos a pub_aprobar / pub_rechazar del bot
    # para minimizar interferencia. El bot ignora callbacks prog_* desconocidos.
    poll_offset = None
    decision = None
    deadline = _time.time() + 20 * 60  # 20 min

    while _time.time() < deadline:
        params_poll = {"timeout": 20, "allowed_updates": ["callback_query"]}
        if poll_offset:
            params_poll["offset"] = poll_offset
        try:
            updates = req.get(
                f"{BASE_URL}/getUpdates", params=params_poll, timeout=35
            ).json().get("result", [])
        except Exception as _pe:
            console.print(f"[yellow]Error polling: {_pe}[/yellow]")
            _time.sleep(5)
            continue
        for upd in updates:
            poll_offset = upd["update_id"] + 1
            cb = upd.get("callback_query")
            if not cb:
                continue
            cb_data = cb.get("data", "")
            if rev_id not in cb_data:
                continue
            accion_cb = cb_data.split(":")[0]
            decision = "aprobar" if accion_cb == "prog_si" else "saltar"
            req.post(f"{BASE_URL}/answerCallbackQuery", data={
                "callback_query_id": cb["id"],
                "text": "✅ Publicando..." if decision == "aprobar" else "⏭ Saltado",
            }, timeout=10)
            break
        if decision:
            break

    if not decision:
        console.print("[yellow]Sin respuesta en 20 min — publicación cancelada.[/yellow]")
        _enviar_mensaje(
            f"⏰ <b>Sin respuesta en 20 min</b> — {tipo_label} no se publicó.\n\n"
            f"Para publicar: escribe /hoy y toca <b>📅 Aprobar</b> antes de que corra el siguiente slot."
        )
        return

    if decision == "saltar":
        console.print("Saltado por el usuario.")
        _enviar_mensaje(f"⏭ {tipo_label} saltado.")
        return

    # ── Publicar ──────────────────────────────────────────────────────────────
    if item.es_carrusel:
        _enviar_carrusel_manual(item)
    else:
        _ejecutar_publicacion(item, tipo_pub)


@cli.command()
@click.argument("entrada_id")
def aprobar(entrada_id):
    """Aprueba una entrada del calendario para publicación."""
    if memoria.actualizar_estado_entrada(entrada_id, "aprobado"):
        console.print(f"[green]✓[/green] Entrada {entrada_id} aprobada para publicación.")
    else:
        console.print(f"[red]Entrada {entrada_id} no encontrada.[/red]")


@cli.command()
@click.argument("entrada_id")
def rechazar(entrada_id):
    """Rechaza una entrada del calendario."""
    if memoria.actualizar_estado_entrada(entrada_id, "rechazado"):
        console.print(f"[yellow]Entrada {entrada_id} rechazada.[/yellow]")
    else:
        console.print(f"[red]Entrada {entrada_id} no encontrada.[/red]")


@cli.command()
def probar_material():
    """Genera 1 post + 1 story + 1 reel + 1 carrusel de datos curiosos — todo con IA."""
    from agente.generadores.imagen_compuesta import generar_foto_kontext
    from agente.generadores.video_automatico import generar_reel as _generar_reel
    from agente.generadores.generador_carrusel import generar_carrusel_educativo
    from agente.generadores.imagen_compuesta import generar_escenas_para_video
    from config import imagen_params as params

    resultados = {}

    # ── 1. POST ──────────────────────────────────────────────────────────────
    console.print("\n[bold cyan]1/4 — Post (FLUX Kontext)[/bold cyan]")
    with console.status("Generando imagen de post con IA..."):
        post = generar_foto_kontext(pilar="recetas_y_maridajes", formato="post", sufijo="_prueba_post")
    if post:
        console.print(f"  [green]✓[/green] {post.name}  ({post.stat().st_size // 1024} KB)")
        resultados["post"] = str(post)
    else:
        console.print("  [red]✗[/red] Post falló")
        resultados["post"] = None

    # ── 2. STORY ─────────────────────────────────────────────────────────────
    console.print("\n[bold cyan]2/4 — Story (FLUX Kontext)[/bold cyan]")
    with console.status("Generando imagen de story 9:16 con IA..."):
        story = generar_foto_kontext(pilar="lifestyle_y_comunidad", formato="story", sufijo="_prueba_story")
    if story:
        console.print(f"  [green]✓[/green] {story.name}  ({story.stat().st_size // 1024} KB)")
        resultados["story"] = str(story)
    else:
        console.print("  [red]✗[/red] Story falló")
        resultados["story"] = None

    # ── 3. REEL ──────────────────────────────────────────────────────────────
    console.print("\n[bold cyan]3/4 — Reel slideshow (FLUX Kontext + música)[/bold cyan]")
    with console.status("Generando 4 escenas del producto..."):
        escenas = generar_escenas_para_video(
            pilar="humor_picante", n=4, formato="story", sufijo="_prueba_reel"
        )
    console.print(f"  {len(escenas)} escenas generadas")
    with console.status("Ensambando video MP4 con música..."):
        reel = _generar_reel(
            imagenes=[str(p) for p in escenas],
            mood_musica="upbeat_latino",
            sufijo="_prueba",
        )
    if reel:
        console.print(f"  [green]✓[/green] {reel.name}  ({reel.stat().st_size / 1_048_576:.1f} MB)")
        resultados["reel"] = str(reel)
    else:
        console.print("  [red]✗[/red] Reel falló")
        resultados["reel"] = None

    # ── 4. CARRUSEL DE DATOS CURIOSOS ────────────────────────────────────────
    console.print("\n[bold cyan]4/4 — Carrusel: 5 datos curiosos del picante (Claude + Pillow)[/bold cyan]")
    with console.status("Claude generando datos + Pillow creando slides..."):
        slides = generar_carrusel_educativo(
            tema="curiosidades del picante", n_slides=5, sufijo="_prueba"
        )
    if slides:
        carpeta = Path(slides[0]).parent
        console.print(f"  [green]✓[/green] {len(slides)} slides en {carpeta.name}/")
        resultados["carrusel"] = str(carpeta)
    else:
        console.print("  [red]✗[/red] Carrusel falló")
        resultados["carrusel"] = None

    # ── Resumen ───────────────────────────────────────────────────────────────
    console.print()
    tabla = Table(title="Resultado de la prueba completa")
    tabla.add_column("Tipo")
    tabla.add_column("Archivo")
    tabla.add_column("Estado")
    for tipo, ruta in resultados.items():
        nombre = Path(ruta).name if ruta else "—"
        estado_txt = "[green]✓ OK[/green]" if ruta else "[red]✗ Falló[/red]"
        tabla.add_row(tipo.upper(), nombre, estado_txt)
    console.print(tabla)
    console.print("\nRevisa los archivos en [bold]material_agente/imagenes_compuestas/[/bold] y [bold]material_agente/videos_generados/[/bold]")


@cli.command()
def estado():
    """Muestra el estado actual del agente."""
    console.print(Panel("[bold]Estado del Agente — Salsas Bestial[/bold]"))

    historial = memoria.cargar_historial()
    metricas = memoria.cargar_metricas()
    calendario = memoria.cargar_calendario()
    ideas = memoria.obtener_ideas_disponibles()
    campanas = memoria.obtener_campanas_activas()

    tabla = Table()
    tabla.add_column("Componente")
    tabla.add_column("Estado")
    tabla.add_row("Publicaciones en historial", str(len(historial.publicaciones)))
    tabla.add_row("Semanas de métricas", str(len(metricas.semanas)))
    tabla.add_row("Calendario activo", f"{calendario.semana} ({calendario.estado})" if calendario else "Ninguno")
    tabla.add_row("Ideas disponibles", str(len(ideas)))
    tabla.add_row("Campañas activas", str(len(campanas)))

    credenciales = settings.verificar_credenciales()
    faltantes = [k for k, v in credenciales.items() if not v]
    tabla.add_row(
        "Credenciales",
        "[green]Todas OK[/green]" if not faltantes else f"[red]Faltan: {', '.join(faltantes)}[/red]"
    )
    console.print(tabla)


if __name__ == "__main__":
    cli()
