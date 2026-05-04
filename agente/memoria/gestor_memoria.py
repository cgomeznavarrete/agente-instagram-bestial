"""
Interfaz unificada de lectura/escritura para todos los archivos JSON del sistema.
Crea backup .bak antes de cada escritura. Valida con Pydantic antes de guardar.
"""

import json
import shutil
import logging
from datetime import datetime
from pathlib import Path

from config import settings
from agente.memoria.modelos import (
    HistorialPublicaciones,
    CalendarioSemanal,
    RegistroMaterialUsado,
    MaterialUsado,
    RegistroUsoMaterial,
    MetricasInstagram,
    IdeasContenido,
    Idea,
    CampanasActivas,
    Campana,
    Publicacion,
    EntradaCalendario,
    TipoContenido,
)

logger = logging.getLogger(__name__)

# Rutas de archivos JSON
_HISTORIAL = settings.DATOS_DIR / "historial_publicaciones.json"
_CALENDARIO = settings.DATOS_DIR / "calendario_semanal.json"
_MATERIAL = settings.DATOS_DIR / "material_usado.json"
_METRICAS = settings.DATOS_DIR / "metricas_instagram.json"
_IDEAS = settings.DATOS_DIR / "ideas_contenido.json"
_CAMPANAS = settings.DATOS_DIR / "campanas_activas.json"


def _leer_json(ruta: Path) -> dict:
    """Lee un archivo JSON. Retorna dict vacío si no existe."""
    if not ruta.exists():
        return {}
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _escribir_json(ruta: Path, datos: dict) -> None:
    """Crea backup y escribe el JSON con formato legible."""
    if ruta.exists():
        shutil.copy2(ruta, ruta.with_suffix(".json.bak"))
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2, default=str)


# ── Historial de publicaciones ────────────────────────────────────────────────

def cargar_historial() -> HistorialPublicaciones:
    datos = _leer_json(_HISTORIAL)
    if not datos:
        return HistorialPublicaciones()
    return HistorialPublicaciones.model_validate(datos)


def guardar_historial(historial: HistorialPublicaciones) -> None:
    historial.ultima_actualizacion = datetime.now()
    _escribir_json(_HISTORIAL, historial.model_dump(mode="json"))
    logger.info("Historial guardado: %d publicaciones", len(historial.publicaciones))


def agregar_publicacion(pub: Publicacion) -> None:
    historial = cargar_historial()
    historial.publicaciones.append(pub)
    guardar_historial(historial)


def obtener_publicaciones_recientes(semanas: int = 8) -> list[Publicacion]:
    """Retorna publicaciones de las últimas N semanas."""
    from datetime import date, timedelta
    corte = date.today() - timedelta(weeks=semanas)
    historial = cargar_historial()
    return [
        p for p in historial.publicaciones
        if p.fecha_publicacion and p.fecha_publicacion.date() >= corte
    ]


# ── Calendario semanal ────────────────────────────────────────────────────────

def cargar_calendario() -> CalendarioSemanal | None:
    datos = _leer_json(_CALENDARIO)
    if not datos:
        return None
    return CalendarioSemanal.model_validate(datos)


def guardar_calendario(calendario: CalendarioSemanal) -> None:
    _escribir_json(_CALENDARIO, calendario.model_dump(mode="json"))
    logger.info("Calendario guardado: semana %s, %d entradas",
                calendario.semana, len(calendario.entradas))


def actualizar_estado_entrada(entrada_id: str, nuevo_estado: str) -> bool:
    """Cambia el estado de una entrada del calendario. Retorna True si encontró la entrada."""
    calendario = cargar_calendario()
    if not calendario:
        return False
    for entrada in calendario.entradas:
        if entrada.id == entrada_id:
            entrada.estado = nuevo_estado
            guardar_calendario(calendario)
            logger.info("Entrada %s → estado: %s", entrada_id, nuevo_estado)
            return True
    return False


def obtener_entradas_aprobadas() -> list[EntradaCalendario]:
    calendario = cargar_calendario()
    if not calendario:
        return []
    return [e for e in calendario.entradas if e.estado == "aprobado"]


def obtener_entradas_para_publicar_ahora() -> list[EntradaCalendario]:
    """
    Retorna entradas aprobadas cuya hora de publicación ya pasó (hoy o días anteriores).

    Lógica "overdue": publica todo lo que estaba aprobado y programado para ahora o antes.
    Esto garantiza que un retraso de GitHub Actions (30+ min) no pierda la publicación.
    """
    import datetime as dt

    calendario = cargar_calendario()
    if not calendario:
        return []

    ahora = dt.datetime.now()
    hoy = ahora.date()
    resultado = []
    for entrada in calendario.entradas:
        if entrada.estado != "aprobado":
            continue
        try:
            fecha_entrada = entrada.fecha if isinstance(entrada.fecha, dt.date) else dt.date.fromisoformat(str(entrada.fecha))
            hora_pub = dt.datetime.strptime(entrada.hora_publicacion, "%H:%M").time()
            scheduled = dt.datetime.combine(fecha_entrada, hora_pub)
            # Publicar si la hora programada ya pasó (overdue) — máx 24h de retraso
            if scheduled <= ahora and (ahora - scheduled).total_seconds() <= 86400:
                resultado.append(entrada)
        except (ValueError, TypeError):
            continue
    return resultado


# ── Material usado ────────────────────────────────────────────────────────────

def cargar_material_usado() -> RegistroMaterialUsado:
    datos = _leer_json(_MATERIAL)
    if not datos:
        return RegistroMaterialUsado()
    return RegistroMaterialUsado.model_validate(datos)


def registrar_uso_material(
    archivo: str,
    publicacion_id: str,
    tipo_contenido: TipoContenido,
) -> None:
    from datetime import date
    registro = cargar_material_usado()
    uso = RegistroUsoMaterial(
        publicacion_id=publicacion_id,
        fecha=date.today(),
        tipo_contenido=tipo_contenido,
    )
    for item in registro.registros:
        if item.archivo == archivo:
            item.usos.append(uso)
            item.total_usos = len(item.usos)
            item.ultimo_uso = date.today()
            _escribir_json(_MATERIAL, registro.model_dump(mode="json"))
            return
    nuevo = MaterialUsado(archivo=archivo, usos=[uso])
    registro.registros.append(nuevo)
    registro.ultima_actualizacion = datetime.now()
    _escribir_json(_MATERIAL, registro.model_dump(mode="json"))


def obtener_archivos_disponibles(semanas_enfriamiento: int = 4) -> list[str]:
    """Retorna archivos no usados en las últimas N semanas."""
    from datetime import date, timedelta
    corte = date.today() - timedelta(weeks=semanas_enfriamiento)
    registro = cargar_material_usado()
    usados_recientemente = {
        r.archivo for r in registro.registros
        if r.ultimo_uso and r.ultimo_uso >= corte
    }
    return usados_recientemente


# ── Métricas ──────────────────────────────────────────────────────────────────

def cargar_metricas() -> MetricasInstagram:
    datos = _leer_json(_METRICAS)
    if not datos:
        return MetricasInstagram()
    return MetricasInstagram.model_validate(datos)


def guardar_metricas(metricas: MetricasInstagram) -> None:
    _escribir_json(_METRICAS, metricas.model_dump(mode="json"))
    logger.info("Métricas guardadas: %d semanas", len(metricas.semanas))


def obtener_metricas_semana_anterior() -> dict:
    metricas = cargar_metricas()
    if not metricas.semanas:
        return {}
    return metricas.semanas[-1].model_dump(mode="json")


# ── Ideas de contenido ────────────────────────────────────────────────────────

def cargar_ideas() -> IdeasContenido:
    datos = _leer_json(_IDEAS)
    if not datos:
        return IdeasContenido()
    return IdeasContenido.model_validate(datos)


def agregar_ideas(nuevas: list[Idea]) -> None:
    banco = cargar_ideas()
    banco.banco_ideas.extend(nuevas)
    banco.ultima_actualizacion = datetime.now()
    _escribir_json(_IDEAS, banco.model_dump(mode="json"))
    logger.info("Ideas agregadas: %d nuevas (total: %d)", len(nuevas), len(banco.banco_ideas))


def marcar_idea_usada(idea_id: str) -> None:
    from datetime import date
    banco = cargar_ideas()
    for idea in banco.banco_ideas:
        if idea.id == idea_id:
            idea.usado = True
            idea.fecha_uso = date.today()
            break
    _escribir_json(_IDEAS, banco.model_dump(mode="json"))


def obtener_ideas_disponibles(prioridad: str | None = None) -> list[Idea]:
    banco = cargar_ideas()
    ideas = [i for i in banco.banco_ideas if not i.usado]
    if prioridad:
        ideas = [i for i in ideas if i.prioridad == prioridad]
    return ideas


# ── Campañas activas ──────────────────────────────────────────────────────────

def cargar_campanas() -> CampanasActivas:
    datos = _leer_json(_CAMPANAS)
    if not datos:
        return CampanasActivas()
    return CampanasActivas.model_validate(datos)


def guardar_campanas(campanas: CampanasActivas) -> None:
    campanas.ultima_actualizacion = datetime.now()
    _escribir_json(_CAMPANAS, campanas.model_dump(mode="json"))


def obtener_campanas_activas() -> list[Campana]:
    from datetime import date
    campanas = cargar_campanas()
    hoy = date.today()
    return [
        c for c in campanas.campanas
        if c.activa and c.fecha_inicio <= hoy <= c.fecha_fin
    ]


# ── Inicialización ────────────────────────────────────────────────────────────

def inicializar_archivos() -> None:
    """Crea los archivos JSON vacíos si no existen."""
    settings.DATOS_DIR.mkdir(exist_ok=True)
    archivos_iniciales = {
        _HISTORIAL: HistorialPublicaciones(),
        _CALENDARIO: None,
        _MATERIAL: RegistroMaterialUsado(),
        _METRICAS: MetricasInstagram(),
        _IDEAS: IdeasContenido(),
        _CAMPANAS: CampanasActivas(),
    }
    for ruta, modelo in archivos_iniciales.items():
        if not ruta.exists() and modelo is not None:
            _escribir_json(ruta, modelo.model_dump(mode="json"))
            logger.info("Archivo inicializado: %s", ruta.name)
