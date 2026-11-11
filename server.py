"""Local HTTPS + WebSocket server: phone scans, PC types."""

import asyncio
import datetime
import ipaddress
import json
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw
import pystray
import uvicorn

from keyboard import type_code

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
    CERT_DIR = Path(sys.executable).resolve().parent / "certs"
else:
    BASE_DIR = Path(__file__).resolve().parent
    CERT_DIR = BASE_DIR / "certs"
PORT = 8443
TYPE_LOCK = asyncio.Lock()

app = FastAPI(docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def default_ip() -> str:
    """IP de la interfaz con ruta por defecto (la Wi-Fi real, no VirtualBox)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


def lan_url() -> str:
    return f"https://{default_ip()}:{PORT}"


def local_ips() -> list[str]:
    ips: set[str] = {"127.0.0.1", "localhost", default_ip()}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ips)


def ensure_certs() -> tuple[Path, Path]:
    CERT_DIR.mkdir(exist_ok=True)
    key_path = CERT_DIR / "key.pem"
    cert_path = CERT_DIR / "cert.pem"
    if key_path.exists() and cert_path.exists():
        return cert_path, key_path

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)
    san: list[x509.GeneralName] = [
        x509.IPAddress(ipaddress.ip_address(ip))
        if not ip == "localhost"
        else x509.DNSName("localhost")
        for ip in local_ips()
    ]
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "scan-to-pc")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/info")
async def api_info() -> dict:
    return {"url": lan_url()}


@app.get("/api/qr")
async def api_qr() -> Response:
    import io

    import qrcode

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4
    )
    qr.add_data(lan_url())
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            msg_id = None
            try:
                msg = json.loads(raw)
                code = str(msg.get("code", ""))
                enter = bool(msg.get("enter", True))
                delay = float(msg.get("delay", 0.5))
                msg_id = msg.get("id")
            except (json.JSONDecodeError, TypeError, ValueError):
                code, enter, delay = raw.strip(), True, 0.5
            if not code:
                continue
            async with TYPE_LOCK:
                try:
                    await asyncio.to_thread(type_code, code, enter, delay)
                    await ws.send_text(
                        json.dumps({"ok": True, "code": code, "id": msg_id})
                    )
                except Exception as exc:
                    await ws.send_text(
                        json.dumps(
                            {
                                "ok": False,
                                "code": code,
                                "id": msg_id,
                                "error": str(exc),
                            }
                        )
                    )
    except WebSocketDisconnect:
        pass


def print_banner(url: str) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print()
    print(f"  scan-to-pc corriendo en {url}")
    print("  Abre esta URL desde el teléfono (mismo Wi-Fi):")
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception:
        print(f"  {url}")
    print("  Ctrl+C para detener.")
    print()


def setup_windowed_logging() -> None:
    """Modo bandeja puro: sin consola, redirige logs a scan-to-pc.log."""
    if not getattr(sys, "frozen", False):
        return
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = Path(sys.executable).resolve().parent / "scan-to-pc.log"
    try:
        log = open(log_path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


def alert(message: str, title: str = "scan-to-pc") -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        print(message)


def tray_icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 62, 62], radius=12, fill=(33, 36, 38, 255))
    bars = [(13, 5), (21, 3), (27, 7), (37, 3), (43, 6), (52, 4)]
    for x, w in bars:
        d.rectangle([x, 17, x + w, 47], fill=(245, 244, 240, 255))
    d.rectangle([32, 17, 35, 47], fill=(255, 107, 26, 255))
    return img


def main() -> None:
    setup_windowed_logging()
    cert_path, key_path = ensure_certs()
    url = lan_url()
    print_banner(url)

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=PORT,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        log_level="warning",
    )
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()

    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    else:
        alert(f"No se pudo arrancar el servidor (¿puerto {PORT} ocupado?).")
        return

    def on_open(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        webbrowser.open(url)

    def on_quit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        server.should_exit = True
        icon.stop()

    def on_ready(icon: pystray.Icon) -> None:
        icon.visible = True
        try:
            icon.notify(f"Servidor listo: {url}", "scan-to-pc")
        except Exception:
            pass

    icon = pystray.Icon(
        "scan-to-pc",
        icon=tray_icon_image(),
        title=f"scan-to-pc — {url}",
        menu=pystray.Menu(
            pystray.MenuItem("Abrir en el navegador", on_open, default=True),
            pystray.MenuItem("Salir", on_quit),
        ),
    )
    icon.run(on_ready)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        import traceback

        traceback.print_exc()
        alert(f"Error al iniciar scan-to-pc:\n\n{exc}")
        sys.exit(1)
