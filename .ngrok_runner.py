import os
import time
import sys
from pyngrok import ngrok

# Configurar authtoken si está disponible (recomendado para mayor estabilidad)
authtoken = os.getenv("NGROK_AUTHTOKEN")
if authtoken:
    try:
        ngrok.set_auth_token(authtoken)
    except Exception as e:
        print(f"[ngrok] Advertencia al configurar authtoken: {e}", file=sys.stderr)

# Abrir túnel HTTP al puerto local 8000
try:
    http_tunnel = ngrok.connect(addr=8000, proto="http")
except Exception as e:
    print(f"[ngrok] Error al iniciar túnel: {e}", file=sys.stderr)
    sys.exit(1)

public_url = http_tunnel.public_url
print(public_url, flush=True)

# Persistir URL en archivo para que otro proceso la lea
try:
    with open(".ngrok_url", "w") as f:
        f.write(public_url)
except Exception as e:
    print(f"[ngrok] No se pudo escribir .ngrok_url: {e}", file=sys.stderr)

# Mantener el proceso vivo
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    pass
