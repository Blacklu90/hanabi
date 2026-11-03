"""Android entry point: start Shuinkan's server inside the app (called from MainActivity via Chaquopy)."""
import os
import socket
import sys
import threading
import time
import traceback

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


def _log(msg):
    print(f"shuinkan-start: {msg}", flush=True)  # shows up in logcat as python.stdout


def _versions():
    import importlib
    out = []
    for mod in ("fastapi", "starlette", "pydantic", "pydantic_core", "uvicorn", "sqlalchemy"):
        try:
            out.append(f"{mod} {getattr(importlib.import_module(mod), '__version__', '?')}")
        except Exception as e:  # logging must never stop the app from starting
            out.append(f"{mod} ({type(e).__name__})")
    return ", ".join(out)


def _watch(t0, done, every=20):
    """If starting takes long, print what every thread is doing (to find where it's stuck)."""
    while not done.wait(every):
        _log(f"still starting after {time.time() - t0:.0f}s; threads:")
        for tid, frame in sys._current_frames().items():
            if tid != threading.get_ident():
                _log("".join(traceback.format_stack(frame, limit=12)))


def start(res_dir: str, data_dir: str) -> int:
    """res_dir holds templates/, static/ and data/ (copied from the APK); data_dir holds your progress."""
    global _server
    os.environ["SHUINKAN_ROOT"] = res_dir
    os.environ["SHUINKAN_DB"] = os.path.join(data_dir, "shuinkan.db")
    os.environ["SHUINKAN_CONTENT_DB"] = os.path.join(res_dir, "data", "content.db")
    os.environ.setdefault("SHUINKAN_DEV", "1")  # single-user app on your phone: show password-reset links on screen

    t0 = time.time()
    done = threading.Event()
    threading.Thread(target=_watch, args=(t0, done), name="start-watch", daemon=True).start()
    try:
        _log("importing uvicorn")
        import uvicorn

        _log("versions: " + _versions())
        _log(f"loading the app ({time.time() - t0:.1f}s)")
        from app.main import app  # creates/updates the database and copies in the content

        port = _free_port()
        _log(f"app ready, starting the server on port {port} ({time.time() - t0:.1f}s)")
        return _serve(uvicorn, app, port, t0)
    except BaseException:
        _log("failed:\n" + traceback.format_exc())
        raise
    finally:
        done.set()


def _serve(uvicorn, app, port, t0):
    global _server
    _server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off",
                                            loop="asyncio", http="h11", ws="none"))
    threading.Thread(target=_server.run, name="shuinkan-server", daemon=True).start()
    for _ in range(600):
        if _server.started:
            break
        time.sleep(0.05)
    _log(f"server started={_server.started} ({time.time() - t0:.1f}s)")
    return port
