"""
Controla la rotación de material para evitar repetición de archivos,
formatos y pilares de contenido en publicaciones consecutivas.
"""

from datetime import date, timedelta
from agente.memoria import gestor_memoria as memoria


def archivos_usados_recientemente(semanas: int = 4) -> set[str]:
    """Retorna rutas de archivos usados en las últimas N semanas."""
    corte = date.today() - timedelta(weeks=semanas)
    registro = memoria.cargar_material_usado()
    return {
        r.archivo for r in registro.registros
        if r.ultimo_uso and r.ultimo_uso >= corte
    }


def pilares_usados_recientemente(dias: int = 2) -> list[str]:
    """Retorna pilares de contenido usados en los últimos N días."""
    corte = date.today() - timedelta(days=dias)
    historial = memoria.cargar_historial()
    return [
        p.pilar for p in historial.publicaciones
        if p.fecha_publicacion and p.fecha_publicacion.date() >= corte
    ]


def tipos_usados_recientemente(dias: int = 1) -> list[str]:
    """Evita publicar el mismo tipo de contenido dos veces el mismo día."""
    corte = date.today() - timedelta(days=dias)
    historial = memoria.cargar_historial()
    return [
        p.tipo for p in historial.publicaciones
        if p.fecha_publicacion and p.fecha_publicacion.date() >= corte
    ]


def filtrar_material_disponible(
    archivos: list[dict],
    semanas_enfriamiento: int = 4,
) -> list[dict]:
    """
    Filtra una lista de archivos del catálogo eliminando los usados recientemente.
    Si todos están 'calientes', retorna la lista completa (evita quedar sin material).
    """
    usados = archivos_usados_recientemente(semanas_enfriamiento)
    disponibles = [a for a in archivos if a["ruta"] not in usados]
    if not disponibles:
        disponibles = archivos
    return disponibles


def seleccionar_archivo(
    archivos: list[dict],
    preferencia_origen: str = "intercalado",
    ultimo_origen_usado: str | None = None,
) -> dict | None:
    """
    Selecciona el mejor archivo de una lista aplicando regla de intercalado.
    preferencia_origen: 'usuario' | 'agente' | 'intercalado'
    """
    if not archivos:
        return None

    if preferencia_origen == "intercalado":
        if ultimo_origen_usado == "usuario":
            preferidos = [a for a in archivos if a["origen"] == "agente"]
        else:
            preferidos = [a for a in archivos if a["origen"] == "usuario"]
        if preferidos:
            return preferidos[0]

    return archivos[0]


def validar_distribucion_semanal(entradas: list[dict]) -> list[str]:
    """
    Verifica que el calendario cumple reglas de distribución.
    Retorna lista de advertencias (vacía = todo OK).
    """
    advertencias = []

    # No más de 4 piezas por día
    from collections import Counter
    por_dia = Counter(e.get("dia") for e in entradas)
    for dia, cantidad in por_dia.items():
        if cantidad > 4:
            advertencias.append(f"{dia}: {cantidad} piezas (máximo 4)")

    # No mismo pilar dos días consecutivos
    dias_orden = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    entradas_por_dia = {dia: [] for dia in dias_orden}
    for e in entradas:
        dia = e.get("dia", "")
        if dia in entradas_por_dia:
            entradas_por_dia[dia].append(e.get("pilar", ""))

    for i in range(len(dias_orden) - 1):
        dia_actual = dias_orden[i]
        dia_siguiente = dias_orden[i + 1]
        pilares_actual = set(entradas_por_dia[dia_actual])
        pilares_siguiente = set(entradas_por_dia[dia_siguiente])
        repetidos = pilares_actual & pilares_siguiente
        if repetidos:
            advertencias.append(
                f"Pilar repetido en días consecutivos ({dia_actual}/{dia_siguiente}): "
                + ", ".join(repetidos)
            )

    return advertencias
