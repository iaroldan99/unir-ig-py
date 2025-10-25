# 📱 Integración con **Messenger API for Instagram**

Este módulo permite recibir y responder mensajes directos (DMs) de Instagram utilizando **FastAPI** y la **Graph API v24.0** de Meta.

---

## 🧩 Flujo general

1. La app de Meta se conecta con un **webhook público** (por ejemplo, `/webhooks/instagram`).
2. Instagram envía eventos de mensajes entrantes (webhooks tipo `messaging`).
3. El backend valida la firma (`X-Hub-Signature`), procesa el payload y envía respuestas a través del endpoint:
   ```
   POST https://graph.facebook.com/v24.0/me/messages
   ```

---

## ⚙️ Requisitos previos

- App de Meta configurada con:
  - **Messenger API for Instagram**
  - **Webhooks**
- Una **página de Facebook** vinculada a la cuenta de **Instagram Business / Creator**.
- **Ngrok** (u otro túnel) para exponer el webhook localmente.

---

## 🔑 Variables de entorno (`.env`)

```bash
APP_ID=
APP_SECRET=
GRAPH_API_VERSION=v24.0
VERIFY_TOKEN=

PAGE_ACCESS_TOKEN=
INSTAGRAM_VERIFY_TOKEN=
```

> ⚠️ El `PAGE_ACCESS_TOKEN` debe ser generado para la **página UNIR** (la misma que aparece en `me?fields=id,name` en Herramientas > Explorador Graph API https://developers.facebook.com/tools/explorer/?method=GET&path=me%3Ffields%3Did%2Cname&version=v24.0).

---

## 🧠 Flujo de validación inicial

1. Meta realiza un `GET` al webhook para verificar el token:

   ```
   GET /webhooks/instagram?hub.mode=subscribe&hub.verify_token=demo_token&hub.challenge=1234
   ```

2. El servidor responde con `hub.challenge` si el token coincide.

---

## 💬 Recepción de mensajes (webhook POST)

Meta enviará un payload como:

```json
{
  "object": "instagram",
  "entry": [
    {
      "id": "17841478018690104",
      "time": 176140859501,
      "messaging": [
        {
          "sender": { "id": "123" },
          "recipient": { "id": "1245" },
          "timestamp": 332423,
          "message": { "text": "hola" }
        }
      ]
    }
  ]
}
```

- `sender.id`: **PSID** (Page-Scoped ID) del usuario que envió el mensaje.  
- `recipient.id`: ID de la página asociada.

---

## 🧾 Ejemplo de envío de respuesta

```bash
curl -X POST "https://graph.facebook.com/v24.0/me/messages?access_token=$PAGE_ACCESS_TOKEN"   -H "Content-Type: application/json"   -d '{
        "recipient": { "id": "123" },
        "message":   { "text": "Hola desde unir-ig-py 🚀" },
        "messaging_type": "RESPONSE"
      }'
```

Respuesta esperada:
```json
{"recipient_id":"1234","message_id":"m_..."}
```

---

## 🚧 Errores comunes

| Código | Descripción | Causa probable |
|--------|--------------|----------------|
| `(#100) No se encontró al usuario correspondiente` | PSID inválido o no asociado | El usuario no tiene rol de *Instagram Tester* en modo dev |
| `401 Unauthorized` | Firma inválida | El `APP_SECRET` no coincide o no se envió el header `X-Hub-Signature` |
| `400 Bad Request` | Body malformado | Falta `"messaging_type": "RESPONSE"` o token incorrecto |

---

## 🧪 Modo desarrollo: roles y testers

En modo **Desarrollo**, sólo los usuarios con rol en la app pueden interactuar.

1. Entra a **Meta Developers → Roles → Evaluadores de Instagram**  
   → agrega los usernames de las cuentas que vayan a probar.
2. Cada usuario debe **aceptar la invitación** desde su cuenta de Instagram:  
   `Configuración → Centro de cuentas → Apps y sitios web → Invitaciones de prueba`.
3. Una vez aceptada, los mensajes entre esa cuenta y la página quedan habilitados.

---

## 🟢 Producción

Una vez lista la app:

1. Pasala a **modo Live** (Producción).
2. Verificá los permisos requeridos (`pages_messaging`, `instagram_manage_messages`, etc.).
3. Ya no es necesario que los usuarios sean testers: cualquier usuario podrá enviar mensajes a la cuenta y recibir respuestas automáticas.

---

## 🧩 Log de eventos (ejemplo)

Con el formato actualizado del `webhook.py`:

```
💬 13:07:58 | 👤 PSID=234 | Página=124 | Texto=“hola”
📤 Enviado a 123 | respuesta: {"recipient_id":"123","message_id":"m_..."}
```
