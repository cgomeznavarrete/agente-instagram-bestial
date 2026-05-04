# Música — Salsas Bestial

Tracks royalty-free para videos automáticos (Reels, Stories, Posts de imagen).
Todos son de uso comercial libre, sin necesidad de atribución.

## Tracks instalados

| Archivo | Mood | Usado en |
|---|---|---|
| `upbeat_latino_01.mp3` | Energético, festivo, latino | Promociones, lifestyle, compras |
| `chill_food_01.mp3` | Relajado, gastronómico | Recetas, behind scenes, educación |
| `energetico_01.mp3` | Dinámico, intenso | Retos de picante, challenges |
| `humor_01.mp3` | Playful, divertido | Humor, memes del picante |

## Descargar más tracks (5 minutos, gratis)

### Pixabay Music — sin atribución, uso comercial libre
Sitio: **https://pixabay.com/music/**

Para cada track:
1. Abrí el link
2. Hacé clic en el botón **Download** (flecha hacia abajo)
3. Guardá el archivo con el nombre exacto de la columna "Guardar como"

| Mood | Buscar en Pixabay | Guardar como |
|---|---|---|
| upbeat_latino_02 | "latin upbeat" o "salsa" | `upbeat_latino_02.mp3` |
| chill_food_02 | "cooking background" o "food chill" | `chill_food_02.mp3` |
| romantico_gastro_01 | "romantic acoustic" o "gastro" | `romantico_gastro_01.mp3` |
| energetico_02 | "energetic drums" o "intense" | `energetico_02.mp3` |
| humor_02 | "funny background" o "playful" | `humor_02.mp3` |

### Links directos sugeridos (Pixabay)
- Latin/Salsa: https://pixabay.com/music/search/latin/
- Food/Cooking: https://pixabay.com/music/search/cooking/
- Upbeat: https://pixabay.com/music/search/upbeat/
- Energetic: https://pixabay.com/music/search/energetic/
- Funny/Playful: https://pixabay.com/music/search/funny/

### Fesliyan Studios — también gratis, sin atribución
Sitio: **https://www.fesliyanstudios.com**

Recomendados:
- "Hot Salsa" → https://www.fesliyanstudios.com/royalty-free-music/download/hot-salsa/727 → guardar como `upbeat_latino_02.mp3`
- "Island Mambo" → https://www.fesliyanstudios.com/royalty-free-music/download/island-mambo/847 → guardar como `chill_food_02.mp3`

## Convención de nombres

El sistema selecciona tracks aleatoriamente dentro del mismo mood.
Si agregás `upbeat_latino_03.mp3`, también se usará automáticamente.

```python
# config/imagen_params.py — registro de tracks por mood
MUSICA_POR_MOOD = {
    "upbeat_latino": ["upbeat_latino_01.mp3", "upbeat_latino_02.mp3"],
    "chill_food":    ["chill_food_01.mp3", "chill_food_02.mp3"],
    "energetico":    ["energetico_01.mp3"],
    "humor":         ["humor_01.mp3"],
    "romantico_gastro": ["romantico_gastro_01.mp3"],  # agregar cuando descargues
}
```

Cuando descargues un track nuevo, agregá su nombre al array correspondiente en `imagen_params.py`.

## Mood por pilar de contenido

| Pilar | Mood seleccionado |
|---|---|
| humor_picante | humor |
| retos_y_pruebas_de_picante | energetico |
| promociones_y_lanzamientos | upbeat_latino |
| como_comprar | upbeat_latino |
| beneficios_del_producto | upbeat_latino |
| lifestyle_y_comunidad | upbeat_latino |
| recetas_y_maridajes | chill_food |
| behind_the_scenes | chill_food |
| educacion_sobre_salsas | chill_food |
| testimonios_y_ugc | chill_food |
