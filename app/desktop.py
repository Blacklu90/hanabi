"""Hanabi desktop launcher (Linux).

  hanabi               start Hanabi and open it in its own window
  hanabi --browser     open in your normal browser instead of an app window
  hanabi --install     add Hanabi to your app menu (and desktop) — for the AppImage
  hanabi --uninstall   remove the menu entry (your progress is kept)
  hanabi --stop        stop a running Hanabi
  hanabi --version

How it works: the Hanabi server runs inside this process on 127.0.0.1 only.
If a Chromium-based browser is installed (Chromium, Chrome, Brave, Vivaldi, Edge)
Hanabi opens in an app window (no tabs or address bar) with its own profile, and
closing that window stops Hanabi. Otherwise it opens in your default browser and
stops by itself after 2 hours without use (or with `hanabi --stop`).

Your data lives in $XDG_DATA_HOME/hanabi (normally ~/.local/share/hanabi), the same
folder the older install.sh used, so progress carries over.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

VERSION = "1.0.0"
APP_ROOT = Path(__file__).resolve().parent.parent
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "hanabi"
STATE = DATA_HOME / "desktop-state.json"
IDLE_LIMIT = 2 * 3600
CHROMIUMS = ["chromium", "chromium-browser", "google-chrome-stable", "google-chrome", "brave", "brave-browser",
             "vivaldi-stable", "vivaldi", "microsoft-edge-stable", "microsoft-edge", "thorium-browser"]


def notify(msg: str) -> None:
    print(msg, flush=True)
    if shutil.which("notify-send") and not sys.stdout.isatty():
        subprocess.Popen(["notify-send", "-a", "Hanabi", "-i", "hanabi", "Hanabi", msg],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/speculation.json", timeout=1.5) as r:
            return r.status == 200 and b"prefetch" in r.read(200)
    except Exception:
        return False


def free_port(preferred: int = 8000) -> int:
    for port in [preferred, *range(8001, 8020)]:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def find_chromium() -> str | None:
    for name in CHROMIUMS:
        p = shutil.which(name)
        if p:
            return p
    for flatpak in ("org.chromium.Chromium", "com.google.Chrome", "com.brave.Browser"):
        if shutil.which("flatpak") and subprocess.run(["flatpak", "info", flatpak], capture_output=True).returncode == 0:
            return f"flatpak:{flatpak}"
    return None


def open_window(url: str, force_browser: bool):
    """Returns a Popen for an app window we can wait on, or None if we used the default browser."""
    chrome = None if force_browser else find_chromium()
    if chrome:
        profile = DATA_HOME / "window-profile"
        profile.mkdir(parents=True, exist_ok=True)
        args = [f"--app={url}", f"--user-data-dir={profile}", "--class=Hanabi", "--name=Hanabi", "--no-first-run",
                "--no-default-browser-check", "--disable-features=Translate,MediaRouter", "--window-size=1200,860",
                "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-pings"]
        cmd = ["flatpak", "run", chrome.split(":", 1)[1], *args] if chrome.startswith("flatpak:") else [chrome, *args]
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    opener = shutil.which("xdg-open") or shutil.which("gio")
    if opener:
        subprocess.Popen([opener, url] if opener.endswith("xdg-open") else [opener, "open", url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print(f"Open {url} in your browser.")
    return None


def run(force_browser: bool) -> int:
    st = read_state()
    if st.get("port") and alive(st["port"]):  # already running: just open another window
        open_window(f"http://127.0.0.1:{st['port']}/", force_browser)
        return 0
    DATA_HOME.joinpath("data").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HANABI_DB", str(DATA_HOME / "data" / "hanabi.db"))
    os.environ.setdefault("HANABI_CONTENT_DB", str(APP_ROOT / "data" / "content.db"))
    os.environ.setdefault("HANABI_DEV", "1")  # local single-user app: show password-reset links on screen
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    if not (DATA_HOME / "data" / "hanabi.db").exists():
        notify("Setting up Hanabi for the first time… (a few seconds)")

    sys.path.insert(0, str(APP_ROOT))
    import uvicorn
    from app.main import app  # creates/updates the database and copies in new content

    last_hit = [time.time()]

    @app.middleware("http")
    async def touch(request, call_next):
        last_hit[0] = time.time()
        return await call_next(request)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(300):
        if server.started:
            break
        time.sleep(0.05)
    STATE.write_text(json.dumps({"port": port, "pid": os.getpid(), "version": VERSION}))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    win = open_window(url, force_browser)
    opened = time.time()
    try:
        if win is not None:  # app window: Hanabi lives as long as the window
            while not stop.is_set() and win.poll() is None:
                stop.wait(0.5)
            if not stop.is_set() and time.time() - opened < 8:
                # The browser exited right away: it either handed the window to an already-running
                # copy of itself, or couldn't start. Keep serving; open the normal browser if it failed.
                if win.returncode:
                    open_window(url, True)
                win = None
        if win is None and not stop.is_set():  # default browser: stop after a long idle period
            print(f"Hanabi is running at {url} — close it with: hanabi --stop")
            while not stop.is_set() and time.time() - last_hit[0] < IDLE_LIMIT:
                stop.wait(5)
    finally:
        server.should_exit = True
        t.join(timeout=5)
        try:
            if read_state().get("pid") == os.getpid():
                STATE.unlink()
        except FileNotFoundError:
            pass
    return 0


def stop_running() -> int:
    st = read_state()
    if st.get("pid"):
        try:
            os.kill(st["pid"], signal.SIGTERM)
            print("Hanabi stopped.")
            return 0
        except ProcessLookupError:
            pass
    print("Hanabi isn't running.")
    return 0


# ------------------------------------------------------------ menu entry
def desktop_paths():
    apps = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    icons = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "icons" / "hicolor"
    return apps / "hanabi.desktop", icons


def install() -> int:
    appimage = os.environ.get("APPIMAGE")
    exe = appimage or shutil.which("hanabi")
    if not exe:
        print("Run --install from the Hanabi AppImage (or install the package).")
        return 1
    if appimage:  # keep a stable copy so the menu entry survives moving/deleting the download
        dest = Path.home() / "Applications" / "Hanabi.AppImage"
        dest.parent.mkdir(exist_ok=True)
        if Path(appimage).resolve() != dest.resolve():
            shutil.copy2(appimage, dest)
            dest.chmod(0o755)
        exe = str(dest)
    entry, icons = desktop_paths()
    entry.parent.mkdir(parents=True, exist_ok=True)
    for size in ("256x256", "scalable"):
        (icons / size / "apps").mkdir(parents=True, exist_ok=True)
    shutil.copy2(APP_ROOT / "packaging" / "hanabi.png", icons / "256x256" / "apps" / "hanabi.png")
    shutil.copy2(APP_ROOT / "static" / "img" / "icon.svg", icons / "scalable" / "apps" / "hanabi.svg")
    text = (APP_ROOT / "packaging" / "hanabi.desktop").read_text().replace("Exec=hanabi", f'Exec="{exe}"')
    entry.write_text(text)
    entry.chmod(0o755)
    desk = Path(subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip() or Path.home() / "Desktop") \
        if shutil.which("xdg-user-dir") else Path.home() / "Desktop"
    if desk.is_dir():
        shutil.copy2(entry, desk / "hanabi.desktop")
        subprocess.run(["gio", "set", str(desk / "hanabi.desktop"), "metadata::trusted", "true"], capture_output=True)
    for cmd in (["update-desktop-database", str(entry.parent)], ["gtk-update-icon-cache", "-q", "-t", str(icons)]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, capture_output=True)
    print(f"Installed. Find “Hanabi” in your app menu. (App file: {exe})")
    return 0


def uninstall() -> int:
    entry, icons = desktop_paths()
    for p in (entry, Path.home() / "Desktop" / "hanabi.desktop", icons / "256x256" / "apps" / "hanabi.png",
              icons / "scalable" / "apps" / "hanabi.svg", Path.home() / "Applications" / "Hanabi.AppImage"):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    print(f"Removed from the app menu. Your progress is still in {DATA_HOME}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hanabi", description="Hanabi — Japanese in short, focused bursts.")
    ap.add_argument("--browser", action="store_true", help="open in your normal browser instead of an app window")
    ap.add_argument("--install", action="store_true", help="add Hanabi to your app menu")
    ap.add_argument("--uninstall", action="store_true", help="remove Hanabi from your app menu (keeps your progress)")
    ap.add_argument("--stop", action="store_true", help="stop a running Hanabi")
    ap.add_argument("--version", action="version", version=f"Hanabi {VERSION}")
    a = ap.parse_args(argv)
    if a.install:
        return install()
    if a.uninstall:
        return uninstall()
    if a.stop:
        return stop_running()
    return run(a.browser)


if __name__ == "__main__":
    sys.exit(main())
