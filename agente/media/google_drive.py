"""
Integración con Google Drive para leer material subido desde el celular.
El usuario sube fotos/videos a carpetas de Google Drive desde el teléfono.
El agente los descarga automáticamente para usarlos como material de contenido.

Carpetas esperadas en Google Drive:
  Salsas Bestial - Instagram/
    ├── Posts/           ← fotos para posts del feed
    ├── Reels/           ← videos cortos para reels
    ├── Stories/         ← contenido para stories
    └── Fotos-Producto/  ← fotos del producto para referencia

Configuración:
  - LOCAL: Si tienes Google Drive for Desktop instalado, simplemente configura
    GOOGLE_DRIVE_LOCAL_PATH en .env apuntando a la carpeta sincronizada.
    No requiere API ni credenciales. ¡La forma más simple!

  - GITHUB ACTIONS: Requiere GOOGLE_DRIVE_FOLDER_ID y una service account.
    Configura GOOGLE_CREDENTIALS_JSON en GitHub Secrets.

Para comenzar SIN complejidad: activa Google Drive for Desktop, crea las
carpetas manualmente y apunta GOOGLE_DRIVE_LOCAL_PATH a la carpeta padre.
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

# Extensiones aceptadas por tipo de carpeta
EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
EXTENSIONES_VIDEO  = {".mp4", ".mov", ".avi", ".m4v"}

# Mapeo de nombre de subcarpeta → nombre interno
SUBCARPETAS = {
    "Posts":           "posts",
    "Reels":           "reels",
    "Stories":         "stories",
    "Fotos-Producto":  "fotos_producto",
}


def _ruta_drive_local() -> Optional[Path]:
    """
    Devuelve la ruta local a la carpeta de Google Drive si está configurada.
    """
    ruta_env = os.getenv("GOOGLE_DRIVE_LOCAL_PATH", "")
    if ruta_env:
        ruta = Path(ruta_env)
        if ruta.exists():
            return ruta
        logger.warning("GOOGLE_DRIVE_LOCAL_PATH no existe: %s", ruta)
    return None


def _ruta_drive_api() -> Optional[str]:
    """Devuelve el folder ID de Google Drive si está configurado para API."""
    return os.getenv("GOOGLE_DRIVE_FOLDER_ID", "") or None


def listar_material_local(subcarpeta: str = "Posts") -> list[Path]:
    """
    Lista archivos de imagen/video en la subcarpeta de Google Drive local.
    Retorna una lista de Path ordenada por fecha de modificación (más nuevo primero).
    """
    ruta_base = _ruta_drive_local()
    if not ruta_base:
        return []

    ruta_sub = ruta_base / subcarpeta
    if not ruta_sub.exists():
        logger.info("Subcarpeta de Drive no encontrada: %s", ruta_sub)
        return []

    archivos = []
    for ext in (EXTENSIONES_IMAGEN | EXTENSIONES_VIDEO):
        archivos.extend(ruta_sub.glob(f"*{ext}"))
        archivos.extend(ruta_sub.glob(f"*{ext.upper()}"))

    # Ordenar por fecha de modificación (más reciente primero)
    archivos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    logger.info("Google Drive local '%s': %d archivos encontrados", subcarpeta, len(archivos))
    return archivos


def descargar_material_drive_api(subcarpeta: str = "Posts") -> list[Path]:
    """
    Descarga archivos de Google Drive via API (para GitHub Actions).
    Requiere GOOGLE_DRIVE_FOLDER_ID y GOOGLE_CREDENTIALS_JSON.
    Los archivos se guardan en material_usuario/<tipo>/ local.
    """
    folder_id = _ruta_drive_api()
    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

    if not folder_id or not credentials_json:
        logger.info("Google Drive API no configurada — usando archivos locales")
        return []

    try:
        import json
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        import io

        creds_info = json.loads(credentials_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        # Buscar subcarpeta dentro del folder principal
        query = (
            f"'{folder_id}' in parents and "
            f"mimeType='application/vnd.google-apps.folder' and "
            f"name='{subcarpeta}' and trashed=false"
        )
        resultado = service.files().list(q=query, fields="files(id,name)").execute()
        subcarpetas = resultado.get("files", [])

        if not subcarpetas:
            logger.info("Subcarpeta '%s' no encontrada en Google Drive", subcarpeta)
            return []

        sub_id = subcarpetas[0]["id"]

        # Listar archivos en la subcarpeta
        query_archivos = (
            f"'{sub_id}' in parents and trashed=false and "
            f"(mimeType contains 'image/' or mimeType contains 'video/')"
        )
        res_archivos = service.files().list(
            q=query_archivos,
            fields="files(id,name,mimeType,modifiedTime)",
            orderBy="modifiedTime desc",
            pageSize=20,
        ).execute()

        archivos = res_archivos.get("files", [])
        if not archivos:
            return []

        # Determinar carpeta de destino local
        tipo_interno = SUBCARPETAS.get(subcarpeta, "posts")
        destino = settings.MATERIAL_USUARIO_DIR / tipo_interno
        destino.mkdir(parents=True, exist_ok=True)

        descargados = []
        for archivo in archivos:
            nombre = archivo["name"]
            ruta_local = destino / nombre
            if ruta_local.exists():
                descargados.append(ruta_local)
                continue  # Ya descargado

            logger.info("Descargando de Drive: %s", nombre)
            request = service.files().get_media(fileId=archivo["id"])
            with io.FileIO(str(ruta_local), "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            descargados.append(ruta_local)

        logger.info("Drive API: %d archivos descargados de '%s'", len(descargados), subcarpeta)
        return descargados

    except ImportError:
        logger.warning(
            "Google API libraries no instaladas. "
            "Ejecuta: pip install google-api-python-client google-auth"
        )
        return []
    except Exception as e:
        logger.error("Error accediendo Google Drive API: %s", e)
        return []


def obtener_material(
    tipo: str = "posts",
    max_archivos: int = 10,
    solo_nuevos: bool = False,
) -> list[Path]:
    """
    Obtiene material disponible del usuario para el tipo de contenido dado.

    tipo: "posts" | "reels" | "stories" | "fotos_producto"
    Primero intenta Google Drive local, luego API, luego material_usuario/ local.
    """
    # Mapeo inverso: tipo interno → nombre de subcarpeta en Drive
    nombre_subcarpeta = {v: k for k, v in SUBCARPETAS.items()}.get(tipo, tipo.capitalize())

    archivos = []

    # 1. Google Drive local (más simple, sin API)
    archivos = listar_material_local(nombre_subcarpeta)

    # 2. Google Drive API (para GitHub Actions)
    if not archivos:
        archivos = descargar_material_drive_api(nombre_subcarpeta)

    # 3. Fallback: material_usuario/ local del proyecto
    if not archivos:
        carpeta_local = settings.MATERIAL_USUARIO_DIR / tipo
        if carpeta_local.exists():
            for ext in (EXTENSIONES_IMAGEN | EXTENSIONES_VIDEO):
                archivos.extend(carpeta_local.glob(f"*{ext}"))
                archivos.extend(carpeta_local.glob(f"*{ext.upper()}"))
            archivos.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    # Filtrar solo imágenes si se necesitan imágenes
    if tipo in ("posts", "fotos_producto"):
        archivos = [a for a in archivos if a.suffix.lower() in EXTENSIONES_IMAGEN]

    return archivos[:max_archivos]


def obtener_foto_para_post(pilar: str = "") -> Optional[Path]:
    """
    Selecciona la foto más apropiada para un post según el pilar de contenido.
    Devuelve None si no hay material disponible (el generador usará foto del producto).
    """
    # Para pilares que necesitan fotos de comida/lifestyle, buscar en posts/
    pilares_lifestyle = {
        "recetas_y_maridajes", "lifestyle_y_comunidad",
        "retos_y_pruebas_de_picante", "humor_picante",
    }
    pilares_producto = {
        "behind_the_scenes", "beneficios_del_producto",
        "educacion_sobre_salsas", "testimonios_y_ugc",
        "promociones_y_lanzamientos", "como_comprar",
    }

    if pilar in pilares_lifestyle:
        fotos = obtener_material("posts", max_archivos=5)
        if not fotos:
            fotos = obtener_material("fotos_producto", max_archivos=3)
    else:
        fotos = obtener_material("fotos_producto", max_archivos=5)
        if not fotos:
            fotos = obtener_material("posts", max_archivos=3)

    if fotos:
        # Seleccionar de forma pseudo-aleatoria (para variedad)
        import random
        return random.choice(fotos[:5])
    return None


def obtener_video_para_reel() -> Optional[Path]:
    """Obtiene un video del usuario para usar como base de un Reel."""
    videos = obtener_material("reels", max_archivos=5)
    videos = [v for v in videos if v.suffix.lower() in EXTENSIONES_VIDEO]
    if videos:
        import random
        return random.choice(videos[:3])
    return None


def sincronizar_fotos_producto() -> list[Path]:
    """
    Descarga las fotos de producto de Google Drive y las copia a
    referencia_producto/ para que el agente las use como referencia oficial.
    """
    fotos = obtener_material("fotos_producto", max_archivos=20)
    if not fotos:
        return []

    destino = settings.REFERENCIA_PRODUCTO_DIR
    copiadas = []
    for foto in fotos:
        dest_ruta = destino / foto.name
        if not dest_ruta.exists():
            shutil.copy2(foto, dest_ruta)
            logger.info("Nueva foto de producto sincronizada: %s", foto.name)
            copiadas.append(dest_ruta)

    return copiadas
