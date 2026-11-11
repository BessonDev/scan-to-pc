# scan-to-pc

Escaneás un código de barras o QR con la cámara del teléfono y la PC lo escribe
donde esté el cursor (Excel, POS, Bloc de notas) — todo por la red local, sin internet.

## Requisitos

- Python 3.10+ en la PC
- Teléfono en la misma red Wi-Fi
- Chrome (Android) o Safari (iOS)

## Instalar y arrancar

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python server.py
```

En la terminal aparece la URL (ej. `https://192.168.1.15:8443`) y un QR:
escanealo desde el teléfono (con la app de cámara o el propio escáner).

También hay un ícono en la bandeja del sistema (barras de código):
- doble clic o "Abrir en el navegador" → abre la página en la PC
- "Salir" → detiene el servidor

Y un botón **QR** en la página: abrila en el navegador de la PC
(`https://localhost:8443`), tocá QR y escaneá el modal desde el teléfono.

Primera vez en el navegador: **Avanzado → Continuar** (certificado autofirmado).
Después tocás **Iniciar cámara**, aceptás el permiso y listo.

## Firewall de Windows

Si el teléfono no conecta, permití el puerto en redes privadas (administrador):

```powershell
netsh advfirewall firewall add rule name="scan-to-pc" dir=in action=allow protocol=TCP localport=8443
```

## Cómo funciona

1. El teléfono decódifica el código con `html5-qrcode` (corre local, sin CDN).
2. Lo manda por WebSocket al servidor HTTPS de la PC.
3. `pyautogui` lo escribe en la ventana activa y presiona Enter (configurable
   en la pantalla del teléfono: Enter on/off y retraso 0–5 s).

## Notas

- El certificado se autogenera en `certs/` en el primer arranque.
- Mismo código escaneado dos veces en <1,5 s no se reenvía (debounce).
- Cualquier dispositivo del Wi-Fi puede enviar códigos: es una red doméstica,
  no lo expongas a una red pública.
