"""Shuinkan desktop launcher (Linux and Windows).

  shuinkan               start Shuinkan and open it in its own window
  shuinkan --browser     open in your normal browser instead of an app window
  shuinkan --install     add Shuinkan to your app menu (and desktop) — for the AppImage
  shuinkan --uninstall   remove the menu entry (your progress is kept)
  shuinkan --stop        stop a running Shuinkan
  shuinkan --version

How it works: the Shuinkan server runs inside this process on 127.0.0.1 only.
If a Chromium-based browser is installed (Chromium, Chrome, Brave, Vivaldi, Edge)
Shuinkan opens in an app window (no tabs or address bar) with its own profile, and
closing that window stops Shuinkan. Otherwise it opens in your default browser and
stops by itself after 2 hours without use (or with `shuinkan --stop`).

Your data lives in $XDG_DATA_HOME/shuinkan (normally ~/.local/share/shuinkan, the same
folder the older install.sh used, so progress carries over) or, on Windows,
%LOCALAPPDATA%/Shuinkan. On Windows the app window uses Microsoft Edge (built in).
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

VERSION = "1.2.0"
WINDOWS = os.name == "nt"
FROZEN = getattr(sys, "frozen", False)  # running from the packaged Windows .exe (PyInstaller)
APP_ROOT = Path(getattr(sys, "_MEIPASS", "")) if FROZEN else Path(__file__).resolve().parent.parent
if WINDOWS:
    _BASE = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    DATA_HOME, OLD_HOME = _BASE / "Shuinkan", _BASE / "Hanabi"
else:
    _BASE = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    DATA_HOME, OLD_HOME = _BASE / "shuinkan", _BASE / "hanabi"  # the app was called Hanabi before
STATE = DATA_HOME / "desktop-state.json"
IDLE_LIMIT = 2 * 3600
CHROMIUMS = ["chromium", "chromium-browser", "google-chrome-stable", "google-chrome", "brave", "brave-browser",
             "vivaldi-stable", "vivaldi", "microsoft-edge-stable", "microsoft-edge", "thorium-browser"]


def _quiet_console() -> None:
    """A windowed Windows app has no console: send output to a log file instead of nowhere."""
    if sys.stdout is None or sys.stderr is None:
        DATA_HOME.mkdir(parents=True, exist_ok=True)
        log = open(DATA_HOME / "shuinkan.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def notify(msg: str) -> None:
    print(msg, flush=True)
    if not WINDOWS and shutil.which("notify-send") and not sys.stdout.isatty():
        subprocess.Popen(["notify-send", "-a", "Shuinkan", "-i", "shuinkan", "Shuinkan", msg],
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
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _windows_browsers() -> list[str]:
    roots = [os.environ.get(k) for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    rel = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
           r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Vivaldi\Application\vivaldi.exe", r"Chromium\Application\chrome.exe"]
    return [str(Path(r) / x) for x in rel for r in roots if r and (Path(r) / x).exists()]


def find_chromium() -> str | None:
    if WINDOWS:
        found = _windows_browsers()
        return found[0] if found else None
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
        args = [f"--app={url}", f"--user-data-dir={profile}", "--class=Shuinkan", "--name=Shuinkan", "--no-first-run",
                "--no-default-browser-check", "--disable-features=Translate,MediaRouter", "--window-size=1200,860",
                "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-pings"]
        cmd = ["flatpak", "run", chrome.split(":", 1)[1], *args] if chrome.startswith("flatpak:") else [chrome, *args]
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if WINDOWS:
        try:
            os.startfile(url)  # default browser
        except OSError:
            print(f"Open {url} in your browser.")
        return None
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
    os.environ.setdefault("SHUINKAN_DB", str(DATA_HOME / "data" / "shuinkan.db"))
    # Progress from the old name is copied over on first start (the old folder is left as it was).
    os.environ.setdefault("SHUINKAN_LEGACY_DB", str(OLD_HOME / "data" / "hanabi.db"))
    os.environ.setdefault("SHUINKAN_CONTENT_DB", str(APP_ROOT / "data" / "content.db"))
    os.environ.setdefault("SHUINKAN_DEV", "1")  # local single-user app: show password-reset links on screen
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    if not (DATA_HOME / "data" / "shuinkan.db").exists():
        notify("Setting up Shuinkan for the first time… (a few seconds)")

    if not FROZEN:
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
    if WINDOWS:  # `Shuinkan.exe --stop` drops this file to ask the running copy to quit cleanly
        stop_file = DATA_HOME / "stop-request"
        stop_file.unlink(missing_ok=True)
        threading.Thread(target=_watch_stop_file, args=(stop, stop_file), daemon=True).start()
    win = open_window(url, force_browser)
    opened = time.time()
    try:
        if win is not None:  # app window: Shuinkan lives as long as the window
            while not stop.is_set() and win.poll() is None:
                stop.wait(0.5)
            if not stop.is_set() and time.time() - opened < 8:
                # The browser exited right away: it either handed the window to an already-running
                # copy of itself, or couldn't start. Keep serving; open the normal browser if it failed.
                if win.returncode:
                    open_window(url, True)
                win = None
        if win is None and not stop.is_set():  # default browser: stop after a long idle period
            print(f"Shuinkan is running at {url} — close it with: shuinkan --stop")
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


def _watch_stop_file(stop: threading.Event, f: Path) -> None:
    while not stop.wait(1):
        if f.exists():
            f.unlink(missing_ok=True)
            stop.set()


def stop_running() -> int:
    st = read_state()
    if WINDOWS and st.get("port") and alive(st["port"]):
        (DATA_HOME / "stop-request").write_text("stop")
        print("Shuinkan is stopping.")
        return 0
    if st.get("pid"):
        try:
            os.kill(st["pid"], signal.SIGTERM)
            print("Shuinkan stopped.")
            return 0
        except ProcessLookupError:
            pass
    print("Shuinkan isn't running.")
    return 0


# ------------------------------------------------------------ menu entry
def desktop_paths():
    apps = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    icons = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "icons" / "hicolor"
    return apps / "shuinkan.desktop", icons


def install() -> int:
    if WINDOWS:
        print("On Windows, use Shuinkan-Setup.exe to add Shuinkan to the Start menu.")
        return 0
    appimage = os.environ.get("APPIMAGE")
    exe = appimage or shutil.which("shuinkan")
    if not exe:
        print("Run --install from the Shuinkan AppImage (or install the package).")
        return 1
    if appimage:  # keep a stable copy so the menu entry survives moving/deleting the download
        dest = Path.home() / "Applications" / "Shuinkan.AppImage"
        dest.parent.mkdir(exist_ok=True)
        if Path(appimage).resolve() != dest.resolve():
            shutil.copy2(appimage, dest)
            dest.chmod(0o755)
        exe = str(dest)
    entry, icons = desktop_paths()
    entry.parent.mkdir(parents=True, exist_ok=True)
    for size in ("256x256", "scalable"):
        (icons / size / "apps").mkdir(parents=True, exist_ok=True)
    shutil.copy2(APP_ROOT / "packaging" / "shuinkan.png", icons / "256x256" / "apps" / "shuinkan.png")
    shutil.copy2(APP_ROOT / "static" / "img" / "icon.svg", icons / "scalable" / "apps" / "shuinkan.svg")
    text = (APP_ROOT / "packaging" / "shuinkan.desktop").read_text(encoding="utf-8").replace("Exec=shuinkan", f'Exec="{exe}"')
    entry.write_text(text, encoding="utf-8")
    entry.chmod(0o755)
    desk = Path(subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip() or Path.home() / "Desktop") \
        if shutil.which("xdg-user-dir") else Path.home() / "Desktop"
    if desk.is_dir():
        shutil.copy2(entry, desk / "shuinkan.desktop")
        subprocess.run(["gio", "set", str(desk / "shuinkan.desktop"), "metadata::trusted", "true"], capture_output=True)
    for cmd in (["update-desktop-database", str(entry.parent)], ["gtk-update-icon-cache", "-q", "-t", str(icons)]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, capture_output=True)
    print(f"Installed. Find “Shuinkan” in your app menu. (App file: {exe})")
    return 0


def install_voice() -> int:
    """Put the built-in voice into the data folder (the Windows build already includes it)."""
    os.environ.setdefault("SHUINKAN_DB", str(DATA_HOME / "data" / "shuinkan.db"))
    os.environ.setdefault("SHUINKAN_CONTENT_DB", str(APP_ROOT / "data" / "content.db"))
    if not FROZEN:
        sys.path.insert(0, str(APP_ROOT))
    DATA_HOME.joinpath("data").mkdir(parents=True, exist_ok=True)
    from app import voice
    print("Setting up the Japanese voice (one time)…")
    return 0 if voice.install(progress=print) else 1


def check_voice() -> int:
    os.environ.setdefault("SHUINKAN_DB", str(DATA_HOME / "data" / "shuinkan.db"))
    os.environ.setdefault("SHUINKAN_CONTENT_DB", str(APP_ROOT / "data" / "content.db"))
    if not FROZEN:
        sys.path.insert(0, str(APP_ROOT))
    DATA_HOME.joinpath("data").mkdir(parents=True, exist_ok=True)
    from app import voice
    data = voice.synth("がっこう") if voice.available() else None
    ok = bool(data and data[:4] == b"RIFF" and len(data) > 10000)
    print("voice ok" if ok else "voice missing")
    return 0 if ok else 1


def uninstall() -> int:
    if WINDOWS:
        print("On Windows, uninstall Shuinkan from Settings → Apps. Your progress stays in", DATA_HOME)
        return 0
    entry, icons = desktop_paths()
    for p in (entry, Path.home() / "Desktop" / "shuinkan.desktop", icons / "256x256" / "apps" / "shuinkan.png",
              icons / "scalable" / "apps" / "shuinkan.svg", Path.home() / "Applications" / "Shuinkan.AppImage"):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    print(f"Removed from the app menu. Your progress is still in {DATA_HOME}")
    return 0


def main(argv=None) -> int:
    _quiet_console()
    ap = argparse.ArgumentParser(prog="shuinkan", description="Shuinkan — Japanese in short, focused bursts.")
    ap.add_argument("--browser", action="store_true", help="open in your normal browser instead of an app window")
    ap.add_argument("--install", action="store_true", help="add Shuinkan to your app menu")
    ap.add_argument("--uninstall", action="store_true", help="remove Shuinkan from your app menu (keeps your progress)")
    ap.add_argument("--stop", action="store_true", help="stop a running Shuinkan")
    ap.add_argument("--install-voice", action="store_true", help="download the built-in Japanese voice (about 130 MB, once)")
    ap.add_argument("--check-voice", action="store_true", help=argparse.SUPPRESS)  # CI: exit 0 if the built-in voice speaks
    ap.add_argument("--version", action="version", version=f"Shuinkan {VERSION}")
    a = ap.parse_args(argv)
    if a.install_voice:
        return install_voice()
    if a.check_voice:
        return check_voice()
    if a.install:
        code = install()
        if code == 0 and not WINDOWS:
            install_voice()  # set up the voice now, so ▶ works right away
        return code
    if a.uninstall:
        return uninstall()
    if a.stop:
        return stop_running()
    return run(a.browser)


if __name__ == "__main__":
    sys.exit(main())
