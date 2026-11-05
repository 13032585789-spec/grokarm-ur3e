"""Start/stop VOCE from a notebook, a script or start.sh.

    from app.launcher import start
    handle = start(mode="ursim")     # idempotent: a second call returns the same running server
    handle.stop()

CLI:  python -m app.launcher --mode ursim [--no-browser]
"""

from __future__ import annotations

import argparse
import ipaddress
import socket
import threading
import time
import urllib.request
import webbrowser
from dataclasses import dataclass, field

PHONE_PORT = 8443

from .config import FRONTEND_DIST, ConfigError, load_settings

_lock = threading.Lock()
_handle: "Handle | None" = None


@dataclass
class Handle:
    mode: str
    url: str
    _server: object = field(repr=False)
    _thread: threading.Thread = field(repr=False)
    warnings: list[str] = field(default_factory=list)
    phone_urls: list[str] = field(default_factory=list)
    _https: object | None = field(default=None, repr=False)
    _https_thread: threading.Thread | None = field(default=None, repr=False)

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def stop(self, timeout: float = 10.0) -> None:
        """Safe shutdown: the app stops any motion, drops pending actions, disconnects the robot."""
        global _handle
        self._server.should_exit = True
        if self._https is not None:
            self._https.should_exit = True
        self._thread.join(timeout)
        if self._https_thread is not None:
            self._https_thread.join(timeout)
        with _lock:
            if _handle is self:
                _handle = None
        print(f"VOCE fermato ({self.url}).")

    def __repr__(self) -> str:
        return f"<VOCE {self.mode} {self.url} {'running' if self.running else 'stopped'}>"


def _port_busy(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def _lan_ips() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ips)


def _phone_cert(data_dir, ips: list[str]):
    """Self-signed cert so a phone can grant the camera. Regenerated when the LAN address changes."""
    from datetime import datetime, timedelta, timezone

    cert_path, key_path = data_dir / "phone-cert.pem", data_dir / "phone-key.pem"
    stamp = data_dir / "phone-cert.txt"
    want = ",".join(ips)
    if cert_path.exists() and key_path.exists() and stamp.exists() and stamp.read_text(encoding="utf-8").strip() == want:
        return cert_path, key_path
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "voce-phone")])
    san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    san += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(san), critical=False).sign(key, hashes.SHA256()))
    data_dir.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                            serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    stamp.write_text(want, encoding="utf-8")
    return cert_path, key_path


def start(mode: str = "ursim", *, open_browser: bool = True, port: int | None = None) -> Handle:
    global _handle
    with _lock:
        if _handle is not None and _handle.running:
            if _handle.mode != mode:
                raise RuntimeError(f"VOCE is already running in mode {_handle.mode!r}; call handle.stop() first.")
            print(f"VOCE già in esecuzione: {_handle.url}")
            return _handle

        settings = load_settings(mode)            # validates YAML + env; raises ConfigError
        if port:
            settings.port = port
        local = settings.host in ("127.0.0.1", "0.0.0.0", "localhost")
        bind = "0.0.0.0" if local else settings.host
        probe = "127.0.0.1" if bind == "0.0.0.0" else bind
        url = f"http://{'localhost' if local else settings.host}:{settings.port}"
        if _port_busy(probe, settings.port):
            raise RuntimeError(f"Port {settings.port} already in use (another VOCE instance?). Stop it first.")
        for w in settings.warnings:
            print("⚠️ ", w)
        if not (FRONTEND_DIST / "index.html").exists():
            print("⚠️  frontend not built: run ./start.sh once (or: cd frontend && npm install && npm run build)")

        import uvicorn

        from .main import create_app
        phone_urls: list[str] = []
        https = https_th = None
        try:
            ips = _lan_ips()
            if ips and not _port_busy("127.0.0.1", PHONE_PORT):
                cert, key = _phone_cert(settings.data_dir, ips)
                phone_urls = [f"https://{ip}:{PHONE_PORT}" for ip in ips]
                settings.phone_urls = phone_urls
        except Exception as e:  # noqa: BLE001 — the PC page must still come up
            print(f"⚠️  pagina telefono non avviata: {e}")
            phone_urls = []

        app = create_app(settings)
        server = uvicorn.Server(uvicorn.Config(app, host=bind, port=settings.port, log_level="warning",
                                               ws_ping_interval=20))
        server.install_signal_handlers = lambda: None  # running in a background thread
        th = threading.Thread(target=server.run, name="voce-server", daemon=True)
        th.start()
        if phone_urls:
            try:
                cert, key = settings.data_dir / "phone-cert.pem", settings.data_dir / "phone-key.pem"
                https = uvicorn.Server(uvicorn.Config(
                    app, host=bind, port=PHONE_PORT, log_level="warning", ws_ping_interval=20,
                    ssl_certfile=str(cert), ssl_keyfile=str(key)))
                https.install_signal_handlers = lambda: None
                https_th = threading.Thread(target=https.run, name="voce-https", daemon=True)
                https_th.start()
            except Exception as e:  # noqa: BLE001
                print(f"⚠️  pagina telefono non avviata: {e}")
                phone_urls = []
                settings.phone_urls = []
                https = https_th = None
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url + "/api/status", timeout=1) as r:
                    if r.status == 200:
                        break
            except OSError:
                time.sleep(0.2)
            if not th.is_alive():
                if https is not None:
                    https.should_exit = True
                raise RuntimeError("VOCE server failed to start (see logs/voce.jsonl)")
        else:
            server.should_exit = True
            if https is not None:
                https.should_exit = True
            raise RuntimeError("VOCE server did not become ready in 20 s")

        _handle = Handle(mode=mode, url=url, _server=server, _thread=th, warnings=settings.warnings,
                         phone_urls=phone_urls, _https=https, _https_thread=https_th)
        badge = "🔴 ROBOT REALE" if mode == "real" else f"modalità {mode}"
        print(f"VOCE avviato: {url}  ({badge})")
        for u in phone_urls:
            print(f"   telefono: {u}  (accetta l'avviso del certificato, poi accendi la webcam)")
        if open_browser:
            webbrowser.open(url)
        return _handle


def main() -> None:
    ap = argparse.ArgumentParser(description="Start VOCE")
    ap.add_argument("--mode", default=None, choices=["sim", "ursim", "real"])
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--port", type=int, default=None)
    a = ap.parse_args()
    try:
        h = start(a.mode or load_settings().mode, open_browser=not a.no_browser, port=a.port)
    except (ConfigError, RuntimeError) as e:
        raise SystemExit(f"VOCE: {e}")
    try:
        while h.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        h.stop()


if __name__ == "__main__":
    main()
