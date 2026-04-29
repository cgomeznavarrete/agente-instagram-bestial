"""
Escanea material_usuario/ y material_agente/, construye y actualiza el catálogo.
REGLA ABSOLUTA: nunca modifica archivos originales del usuario.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from config import settings
from config import brand_guidelines as brand

logger = logging.getLogger(__name__)

EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".webp"}
EXTENSIONES_VIDEO = {".mp4", ".mov", ".avi", ".mkv"}

CATALOGO_PATH = settings.MATERIAL_AGENTE_DIR / "catalogos" / "catalogo_material.json"


def _clasificar_por_ruta(ruta: Path) -> str:
    """Infiere la categoría del material por su ruta de carpeta."""
    partes = [p.lower() for p in ruta.parts]
    if "productos" in partes:
        return "producto"
    if "lifestyle" in partes:
        return "lifestyle"
    if "eventos" in partes:
        return "evento"
    if "recortados" in partes:
        return "producto_recortado"
    if "imagenes_compuestas" in partes:
        return "compuesta"
    if "videos_generados" in partes:
        return "video_generado"
    return "general"


def _info_archivo(ruta: Path, base: Path) -> dict:
    """Construye el registro de un archivo de material."""
    stat = ruta.stat()
    es_imagen = ruta.suffix.lower() in EXTENSIONES_IMAGEN
    es_video = ruta.suffix.lower() in EXTENSIONES_VIDEO

    return {
        "ruta": str(ruta.relative_to(base)),
        "nombre": ruta.name,
        "categoria": _clasificar_por_ruta(ruta),
        "tipo": "imagen" if es_imagen else ("video" if es_video else "otro"),
        "extension": ruta.suffix.lower(),
        "tamano_kb": round(stat.st_size / 1024, 1),
        "fecha_modificacion": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "origen": "usuario" if "material_usuario" in str(ruta) else "agente",
    }


def escanear_material_usuario() -> list[dict]:
    """Escanea material_usuario/ recursivamente. Solo lectura."""
    archivos = []
    base = settings.BASE_DIR
    for ext in EXTENSIONES_IMAGEN | EXTENSIONES_VIDEO:
        for ruta in settings.MATERIAL_USUARIO_DIR.rglob(f"*{ext}"):
            archivos.append(_info_archivo(ruta, base))
    logger.info("Material usuario escaneado: %d archivos", len(archivos))
    return archivos


def escanear_material_agente() -> list[dict]:
    """Escanea material_agente/ (imágenes compuestas, videos generados)."""
    archivos = []
    base = settings.BASE_DIR
    carpetas = [
        settings.MATERIAL_AGENTE_DIR / "imagenes_compuestas",
        settings.MATERIAL_AGENTE_DIR / "videos_generados",
    ]
    for carpeta in carpetas:
        if not carpeta.exists():
            continue
        for ext in EXTENSIONES_IMAGEN | EXTENSIONES_VIDEO:
            for ruta in carpeta.rglob(f"*{ext}"):
                archivos.append(_info_archivo(ruta, base))
    logger.info("Material agente escaneado: %d archivos", len(archivos))
    return archivos


def escanear_referencia_producto() -> list[dict]:
    """Escanea las fotos oficiales del producto (fuente de verdad)."""
    archivos = []
    base = settings.BASE_DIR
    for ext in EXTENSIONES_IMAGEN:
        for ruta in settings.REFERENCIA_PRODUCTO_DIR.glob(f"*{ext}"):
            if ruta.parent.name == "recortados":
                continue
            archivos.append(_info_archivo(ruta, base))
    return archivos


def construir_catalogo() -> dict:
    """Construye el catálogo completo de todo el material disponible."""
    usuario = escanear_material_usuario()
    agente = escanear_material_agente()
    referencia = escanear_referencia_producto()

    catalogo = {
        "version": "1.0",
        "fecha_actualizacion": datetime.now().isoformat(),
        "totales": {
            "usuario": len(usuario),
            "agente": len(agente),
            "referencia": len(referencia),
        },
        "material_usuario": usuario,
        "material_agente": agente,
        "referencia_producto": referencia,
    }

    CATALOGO_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CATALOGO_PATH, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, ensure_ascii=False, indent=2)

    logger.info(
        "Catalogo construido: %d usuario + %d agente + %d referencia",
        len(usuario), len(agente), len(referencia),
    )
    return catalogo


def cargar_catalogo() -> dict:
    """Carga el catálogo existente o lo construye si no existe."""
    if CATALOGO_PATH.exists():
        with open(CATALOGO_PATH, encoding="utf-8") as f:
            return json.load(f)
    return construir_catalogo()


def obtener_por_categoria(categoria: str, origen: str = "cualquiera") -> list[dict]:
    """Filtra el catálogo por categoría y origen."""
    catalogo = cargar_catalogo()
    fuentes = []
    if origen in ("cualquiera", "usuario"):
        fuentes.extend(catalogo.get("material_usuario", []))
    if origen in ("cualquiera", "agente"):
        fuentes.extend(catalogo.get("material_agente", []))
    return [a for a in fuentes if a["categoria"] == categoria]


def obtener_imagenes_producto(incluir_recortadas: bool = False) -> list[dict]:
    """Retorna las fotos oficiales del producto de referencia."""
    catalogo = cargar_catalogo()
    refs = catalogo.get("referencia_producto", [])
    if not incluir_recortadas:
        refs = [r for r in refs if "recortad" not in r["nombre"].lower()]
    return refs


def obtener_todos_disponibles() -> list[dict]:
    """Retorna todo el material (usuario + agente) como lista plana."""
    catalogo = cargar_catalogo()
    return (
        catalogo.get("material_usuario", []) +
        catalogo.get("material_agente", [])
    )


def ruta_absoluta(ruta_relativa: str) -> Path:
    """Convierte ruta relativa del catálogo a ruta absoluta del sistema."""
    return settings.BASE_DIR / ruta_relativa


def obtener_rutas_imagenes_para_video(max_imgs: int = 6) -> list[Path]:
    """
    Devuelve rutas absolutas de imágenes para usar en slideshow de video.
    Prioriza: fotos del usuario > imágenes compuestas > fotos de referencia del producto.
    """
    rutas: list[Path] = []

    # 1. Fotos del usuario (material_usuario/)
    for ext in EXTENSIONES_IMAGEN:
        for carpeta in settings.MATERIAL_USUARIO_DIR.rglob("*"):
            if carpeta.is_dir():
                rutas.extend(carpeta.glob(f"*{ext}"))

    # 2. Imágenes compuestas generadas
    comp_dir = settings.MATERIAL_AGENTE_DIR / "imagenes_compuestas"
    if comp_dir.exists():
        for ext in EXTENSIONES_IMAGEN:
            rutas.extend(comp_dir.glob(f"*{ext}"))

    # 3. Fotos de referencia del producto
    for ext in EXTENSIONES_IMAGEN:
        for ruta in settings.REFERENCIA_PRODUCTO_DIR.glob(f"*{ext}"):
            if "recortado" not in ruta.stem.lower():
                rutas.append(ruta)

    # Ordenar por fecha de modificación (más reciente primero) y limitar
    rutas = list({r.resolve() for r in rutas if r.exists()})  # deduplicar
    rutas.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return rutas[:max_imgs]
