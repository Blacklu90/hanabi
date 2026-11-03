"""Android entry point: start Shuinkan's server inside the app (called from MainActivity via Chaquopy)."""
import os
import socket
import threading
import time

_server = None


def _free_port(preferred=8765):
    for port in [preferred, *range(8766, 8790)]:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(res_dir: str, data_dir: str) -> int:
    """res_dir holds templates/, static/ and data/ (copied from the APK); data_dir holds your progress."""
    global _server
    os.environ["SHUINKAN_ROOT"] = res_dir
    os.environ["SHUINKAN_DB"] = os.path.join(data_dir, "shuinkan.db")
    os.environ["SHUINKAN_CONTENT_DB"] = os.path.join(res_dir, "data", "content.db")
    os.environ.setdefault("SHUINKAN_DEV", "1")  # single-user app on your phone: show password-reset links on screen

    import uvicorn

    from app.main import app  # creates/updates the database and copies in the content

    port = _free_port()
    _server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off",
                                            loop="asyncio", http="h11", ws="none"))
    threading.Thread(target=_server.run, name="shuinkan-server", daemon=True).start()
    for _ in range(600):
        if _server.started:
            break
        time.sleep(0.05)
    return port
