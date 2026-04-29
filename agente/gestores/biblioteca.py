"""
Biblioteca de contenido — cola de publicación por tipo.
Gestiona el material enviado por el usuario para publicación programada.
"""

import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

BIBLIOTECA_JSON = settings.DATOS_DIR / "biblioteca.json"

# Carpetas de almacenamiento por tipo
CARPETAS = {
    "post":   settings.MATERIAL_AGENTE_DIR / "biblioteca" / "posts",
    "reel":   settings.MATERIAL_AGENTE_DIR / "biblioteca" / "reels",
    "story":  settings.MATERIAL_AGENTE_DIR / "biblioteca" / "stories",
}

EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
EXTENSIONES_VIDEO  = {".mp4", ".mov", ".avi", ".m4v"}


@dataclass
class ItemBiblioteca:
    id: str
    tipo: str          # post | reel | story | carrusel
    nombre_archivo: str
    ruta_local: str
    fecha_agregado: float
    estado: str = "pendiente"   # pendiente | publicado | descartado
    pilar: str = "lifestyle_y_comunidad"
    caption: str = ""
    media_id: str = ""          # ID de Instagram cuando se publica
    fecha_publicado: float = 0.0
    es_carrusel: bool = False
    archivos_carrusel: list = field(default_factory=list)  # para carruseles multi-imagen
    cloudinary_url: str = ""    # URL pública en Cloudinary (persiste entre runners)


def _cargar() -> dict:
    if BIBLIOTECA_JSON.exists():
        return json.loads(BIBLIOTECA_JSON.read_text(encoding="utf-8"))
    return {"items": []}


def _guardar(data: dict):
    BIBLIOTECA_JSON.parent.mkdir(parents=True, exist_ok=True)
    BIBLIOTECA_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8"
    )


def _inicializar_carpetas():
    for carpeta in CARPETAS.values():
        carpeta.mkdir(parents=True, exist_ok=True)


def agregar_item(
    ruta_origen: Path,
    tipo: str,
    pilar: str = "lifestyle_y_comunidad",
    caption: str = "",
) -> ItemBiblioteca:
    """Sube el archivo a Cloudinary y lo registra en la cola.

    Los archivos se guardan en Cloudinary (no en git) para que persistan
    entre runners de GitHub Actions. El JSON es lo único que se commitea.
    """
    _inicializar_carpetas()

    ts = int(time.time() * 1000)
    item_id = f"{tipo}_{ts}"
    sufijo = ruta_origen.suffix.lower()
    nombre_guardado = f"{item_id}{sufijo}"

    # Subir a Cloudinary inmediatamente
    cloudinary_url = ""
    try:
        from agente.media.subidor_cloudinary import SubidorCloudinary
        subidor = SubidorCloudinary()
        es_video = sufijo in EXTENSIONES_VIDEO
        url = subidor.subir(ruta_origen, resource_type="video" if es_video else "image")
        if url:
            cloudinary_url = url
            logger.info("Biblioteca: subido a Cloudinary → %s", url[:60])
        else:
            logger.warning("Biblioteca: Cloudinary no retornó URL para %s", nombre_guardado)
    except Exception as e:
        logger.warning("Biblioteca: error subiendo a Cloudinary: %s", e)

    # Guardar copia local también (útil en desarrollo)
    carpeta_destino = CARPETAS.get(tipo, CARPETAS["post"])
    ruta_destino = carpeta_destino / nombre_guardado
    try:
        shutil.copy2(ruta_origen, ruta_destino)
    except Exception:
        ruta_destino = ruta_origen  # fallback: usar ruta temporal

    item = ItemBiblioteca(
        id=item_id,
        tipo=tipo,
        nombre_archivo=nombre_guardado,
        ruta_local=str(ruta_destino),
        fecha_agregado=time.time(),
        pilar=pilar,
        caption=caption,
        cloudinary_url=cloudinary_url,
    )

    data = _cargar()
    data["items"].append(asdict(item))
    _guardar(data)

    logger.info("Biblioteca: registrado %s (cloudinary=%s)", nombre_guardado, bool(cloudinary_url))
    return item


def agregar_carrusel(
    rutas: list[Path],
    tipo: str = "post",
    pilar: str = "educacion_sobre_salsas",
) -> ItemBiblioteca:
    """Registra un carrusel de múltiples imágenes en la biblioteca."""
    _inicializar_carpetas()
    ts = int(time.time() * 1000)
    item_id = f"carrusel_{ts}"

    carpeta_destino = CARPETAS.get(tipo, CARPETAS["post"]) / item_id
    carpeta_destino.mkdir(parents=True, exist_ok=True)

    archivos_guardados = []
    for i, ruta in enumerate(rutas):
        nombre = f"slide_{i:02d}{ruta.suffix.lower()}"
        dest = carpeta_destino / nombre
        shutil.copy2(ruta, dest)
        archivos_guardados.append(str(dest))

    item = ItemBiblioteca(
        id=item_id,
        tipo=tipo,
        nombre_archivo=f"carrusel_{len(rutas)}_slides",
        ruta_local=str(carpeta_destino),
        fecha_agregado=time.time(),
        pilar=pilar,
        es_carrusel=True,
        archivos_carrusel=archivos_guardados,
    )

    data = _cargar()
    data["items"].append(asdict(item))
    _guardar(data)

    logger.info("Biblioteca: carrusel %d slides → %s", len(rutas), item_id)
    return item


def siguiente_pendiente(tipo: str) -> Optional[ItemBiblioteca]:
    """Devuelve el siguiente item pendiente de la cola para el tipo dado (FIFO)."""
    data = _cargar()
    for raw in data["items"]:
        if raw["tipo"] == tipo and raw["estado"] == "pendiente":
            return ItemBiblioteca(**{k: v for k, v in raw.items()})
    return None


def marcar_publicado(item_id: str, media_id: str = ""):
    """Marca un item como publicado."""
    data = _cargar()
    for raw in data["items"]:
        if raw["id"] == item_id:
            raw["estado"] = "publicado"
            raw["media_id"] = media_id
            raw["fecha_publicado"] = time.time()
            break
    _guardar(data)


def marcar_descartado(item_id: str):
    data = _cargar()
    for raw in data["items"]:
        if raw["id"] == item_id:
            raw["estado"] = "descartado"
            break
    _guardar(data)


def contar_pendientes() -> dict:
    """Retorna cuántos items pendientes hay por tipo."""
    data = _cargar()
    conteo = {"post": 0, "reel": 0, "story": 0, "carrusel": 0}
    for raw in data["items"]:
        if raw["estado"] == "pendiente":
            tipo = raw["tipo"]
            if tipo in conteo:
                conteo[tipo] += 1
    return conteo


def listar_pendientes(tipo: str = None) -> list[ItemBiblioteca]:
    data = _cargar()
    items = []
    for raw in data["items"]:
        if raw["estado"] == "pendiente":
            if tipo is None or raw["tipo"] == tipo:
                items.append(ItemBiblioteca(**{k: v for k, v in raw.items()}))
    return items
