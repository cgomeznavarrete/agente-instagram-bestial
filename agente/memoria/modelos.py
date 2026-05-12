"""
Modelos Pydantic para todos los archivos JSON del sistema de memoria.
Validan el esquema antes de escribir cualquier dato a disco.
"""

from __future__ import annotations
from datetime import datetime, date
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ── Tipos compartidos ─────────────────────────────────────────────────────────

TipoContenido = Literal[
    "post", "reel", "story", "carrusel", "poster", "story_video"
]

EstadoPublicacion = Literal[
    "pendiente", "generado", "aprobado", "rechazado", "publicado", "fallido"
]

PilarContenido = Literal[
    "recetas_y_maridajes",
    "behind_the_scenes",
    "humor_picante",
    "educacion_sobre_salsas",
    "testimonios_y_ugc",
    "promociones_y_lanzamientos",
    "como_comprar",
    "beneficios_del_producto",
    "retos_y_pruebas_de_picante",
    "lifestyle_y_comunidad",
]

ObjetivoContenido = Literal[
    "awareness", "engagement", "ventas", "educacion", "entretenimiento", "comunidad"
]


# ── Copy ──────────────────────────────────────────────────────────────────────

class CopyContenido(BaseModel):
    hook: str = Field(description="Primera línea que para el scroll (máx 100 chars)")
    cuerpo: str = Field(description="Cuerpo del caption")
    cta: str = Field(description="Call to action específico")
    hashtags: list[str] = Field(default_factory=list, description="Lista de hashtags con #")
    hashtags_cantidad: int = Field(default=0)

    def model_post_init(self, __context):
        self.hashtags_cantidad = len(self.hashtags)


# ── Métricas de una publicación ───────────────────────────────────────────────

class MetricasPost(BaseModel):
    reach: int = 0
    impressions: int = 0
    likes: int = 0
    comments: int = 0
    saves: int = 0
    shares: int = 0
    profile_visits: int = 0
    link_clicks: int = 0
    engagement_rate: float = 0.0
    plays: Optional[int] = None


# ── historial_publicaciones.json ──────────────────────────────────────────────

class Publicacion(BaseModel):
    id: str = Field(description="UUID v4 generado localmente")
    instagram_media_id: Optional[str] = None
    fecha_publicacion: Optional[datetime] = None
    tipo: TipoContenido
    pilar: PilarContenido
    objetivo: ObjetivoContenido
    material_usado: list[str] = Field(default_factory=list, description="Rutas relativas al proyecto")
    contenido_copy: Optional[CopyContenido] = Field(default=None, alias="copy")
    metricas: Optional[MetricasPost] = None
    estado: EstadoPublicacion = "pendiente"
    url_cloudinary: Optional[str] = None
    url_imgbb: Optional[str] = None
    fecha_creacion: datetime = Field(default_factory=datetime.now)
    notas: Optional[str] = None

    model_config = {"populate_by_name": True}


class HistorialPublicaciones(BaseModel):
    version: str = "1.0"
    ultima_actualizacion: datetime = Field(default_factory=datetime.now)
    publicaciones: list[Publicacion] = Field(default_factory=list)


# ── calendario_semanal.json ───────────────────────────────────────────────────

class EntradaCalendario(BaseModel):
    id: str
    dia: str = Field(description="lunes, martes, miercoles, jueves, viernes, sabado, domingo")
    fecha: date
    hora_publicacion: str = Field(description="HH:MM formato 24h, ej: 19:00")
    tipo_contenido: TipoContenido
    pilar: PilarContenido
    objetivo: ObjetivoContenido
    concepto: str = Field(description="Descripción del concepto/idea de la pieza")
    material_sugerido: list[str] = Field(default_factory=list, description="Rutas sugeridas de material")
    contenido_copy: Optional[CopyContenido] = Field(default=None, alias="copy")
    brief_capcut_path: Optional[str] = None

    model_config = {"populate_by_name": True}
    video_generado_path: Optional[str] = None
    imagen_compuesta_path: Optional[str] = None
    imagenes_carrusel_paths: list[str] = Field(default_factory=list)
    estado: EstadoPublicacion = "pendiente"
    publicacion_id: Optional[str] = None


class CalendarioSemanal(BaseModel):
    semana: str = Field(description="Formato YYYY-WNN, ej: 2026-W18")
    fecha_inicio: date
    fecha_fin: date
    fecha_generacion: datetime = Field(default_factory=datetime.now)
    estado: Literal["borrador", "aprobado", "en_ejecucion", "completado"] = "borrador"
    campana_activa: Optional[str] = None
    entradas: list[EntradaCalendario] = Field(default_factory=list)
    notas_estrategia: Optional[str] = None


# ── material_usado.json ───────────────────────────────────────────────────────

class RegistroUsoMaterial(BaseModel):
    publicacion_id: str
    fecha: date
    tipo_contenido: TipoContenido


class MaterialUsado(BaseModel):
    archivo: str = Field(description="Ruta relativa al proyecto")
    usos: list[RegistroUsoMaterial] = Field(default_factory=list)
    ultimo_uso: Optional[date] = None
    total_usos: int = 0

    def model_post_init(self, __context):
        self.total_usos = len(self.usos)
        if self.usos:
            self.ultimo_uso = max(u.fecha for u in self.usos)


class RegistroMaterialUsado(BaseModel):
    version: str = "1.0"
    ultima_actualizacion: datetime = Field(default_factory=datetime.now)
    registros: list[MaterialUsado] = Field(default_factory=list)


# ── metricas_instagram.json ───────────────────────────────────────────────────

class InfoCuenta(BaseModel):
    seguidores: int = 0
    seguidos: int = 0
    publicaciones_total: int = 0
    ultima_actualizacion: Optional[datetime] = None


class MetricasSemana(BaseModel):
    semana: str
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    metricas_cuenta: dict = Field(default_factory=dict)
    mejores_posts: list[str] = Field(default_factory=list, description="Lista de instagram_media_id")
    peores_posts: list[str] = Field(default_factory=list)
    horario_optimo: Optional[dict] = None
    formato_ganador: Optional[TipoContenido] = None
    engagement_promedio: float = 0.0
    nuevos_seguidores: int = 0
    recomendaciones: list[str] = Field(default_factory=list)


class MetricasInstagram(BaseModel):
    version: str = "1.0"
    cuenta: InfoCuenta = Field(default_factory=InfoCuenta)
    semanas: list[MetricasSemana] = Field(default_factory=list)


# ── ideas_contenido.json ──────────────────────────────────────────────────────

class Idea(BaseModel):
    id: str
    fecha_generacion: date = Field(default_factory=date.today)
    origen: Literal["claude", "usuario", "metricas", "tendencia"] = "claude"
    tipo_sugerido: TipoContenido
    pilar: PilarContenido
    concepto: str
    notas: Optional[str] = None
    prioridad: Literal["alta", "media", "baja"] = "media"
    usado: bool = False
    fecha_uso: Optional[date] = None


class IdeasContenido(BaseModel):
    version: str = "1.0"
    ultima_actualizacion: datetime = Field(default_factory=datetime.now)
    banco_ideas: list[Idea] = Field(default_factory=list)


# ── campanas_activas.json ─────────────────────────────────────────────────────

class Campana(BaseModel):
    id: str
    nombre: str
    fecha_inicio: date
    fecha_fin: date
    objetivo: ObjetivoContenido
    descripcion: str
    contenidos_planificados: int = 0
    contenidos_publicados: int = 0
    hashtag_campana: Optional[str] = None
    notas_estrategia: Optional[str] = None
    activa: bool = True


class CampanasActivas(BaseModel):
    version: str = "1.0"
    ultima_actualizacion: datetime = Field(default_factory=datetime.now)
    campanas: list[Campana] = Field(default_factory=list)
