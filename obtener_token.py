"""
Obtiene token de Instagram con permiso de publicación.
Método manual: el usuario copia la URL de retorno del navegador.
"""
import re
import sys
import webbrowser
import urllib.parse
import requests

from config import settings

APP_ID     = settings.FACEBOOK_APP_ID
APP_SECRET = settings.FACEBOOK_APP_SECRET
REDIRECT   = "https://www.facebook.com/connect/login_success.html"
SCOPES     = "instagram_basic,instagram_content_publish,pages_read_engagement,business_management"

auth_url = (
    f"https://www.facebook.com/dialog/oauth"
    f"?client_id={APP_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT)}"
    f"&scope={SCOPES}"
    f"&response_type=code"
)

print("=" * 60)
print("PASO 1: Abriendo navegador...")
print("=" * 60)
webbrowser.open(auth_url)
print()
print("Si no abre solo, copia esta URL en el navegador:")
print(auth_url)
print()
print("PASO 2: Autoriza la app en Facebook.")
print()
print("PASO 3: Después de autorizar, Facebook te redirige a una")
print("página que dice 'Success'. Copia la URL completa de esa")
print("página desde la barra del navegador y pégala aquí:")
print()

url_pegada = input("URL completa: ").strip()

# Extraer el código
match = re.search(r"[?&]code=([^&]+)", url_pegada)
if not match:
    print("ERROR: No se encontró el código en la URL.")
    sys.exit(1)

code = urllib.parse.unquote(match.group(1))
print(f"\nCódigo extraído OK.")

# Intercambiar código por token corto
r = requests.get("https://graph.facebook.com/v21.0/oauth/access_token", params={
    "client_id": APP_ID,
    "redirect_uri": REDIRECT,
    "client_secret": APP_SECRET,
    "code": code,
})
data = r.json()
if "access_token" not in data:
    print("ERROR obteniendo token:", data)
    sys.exit(1)

short_token = data["access_token"]
print("Token corto obtenido.")

# Intercambiar por token largo (60 días)
r2 = requests.get("https://graph.facebook.com/oauth/access_token", params={
    "grant_type": "fb_exchange_token",
    "client_id": APP_ID,
    "client_secret": APP_SECRET,
    "fb_exchange_token": short_token,
})
data2 = r2.json()
if "access_token" not in data2:
    print("ERROR obteniendo token largo:", data2)
    sys.exit(1)

long_token = data2["access_token"]
dias = int(data2.get("expires_in", 0)) // 86400
print(f"Token largo obtenido. Válido por ~{dias} días.")

# Guardar en .env
env_path = ".env"
with open(env_path, "r", encoding="utf-8") as f:
    contenido = f.read()

nuevo = re.sub(r"INSTAGRAM_ACCESS_TOKEN=.*", f"INSTAGRAM_ACCESS_TOKEN={long_token}", contenido)
with open(env_path, "w", encoding="utf-8") as f:
    f.write(nuevo)

print("\nToken guardado en .env")

# Verificar
from config import settings as s
import importlib
r3 = requests.get(
    f"https://graph.facebook.com/v21.0/{s.INSTAGRAM_BUSINESS_ACCOUNT_ID}",
    params={"access_token": long_token, "fields": "id,username"}
)
print("Verificación:", r3.json())
print("\nListo. Ya puedes publicar.")
