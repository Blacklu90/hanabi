"""The app was renamed from Hanabi to Shuinkan: old progress, settings and env vars must carry over."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from app import db


def test_old_database_is_copied_and_left_intact(tmp_path):
    old = tmp_path / "old" / "hanabi.db"
    old.parent.mkdir()
    con = sqlite3.connect(old)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (42)")
    con.commit()  # left in the WAL file: the copy must still include it
    new = tmp_path / "new" / "shuinkan.db"
    assert db.adopt_legacy_db(new, [old]) == old
    assert sqlite3.connect(new).execute("SELECT x FROM t").fetchone() == (42,)
    assert con.execute("SELECT x FROM t").fetchone() == (42,)  # the old copy still works
    con.close()
    assert db.adopt_legacy_db(new, [old]) is None  # never overwrites progress that's already there


def test_old_file_next_to_the_new_one_is_found(tmp_path):
    sqlite3.connect(tmp_path / "hanabi.db").execute("CREATE TABLE t (x)").connection.commit()
    assert db.adopt_legacy_db(tmp_path / "shuinkan.db") == tmp_path / "hanabi.db"


def test_old_palette_name_is_migrated(tmp_path):
    eng = db.make_engine(tmp_path / "x.db")
    db.init_db(eng)
    with eng.begin() as c:
        c.execute(text("DELETE FROM schema_migrations WHERE version=7"))
        c.execute(text("INSERT INTO users (id, username, email, display_name, password_hash, created_at) VALUES (1,'a','a@b.c','A','x',0)"))
        c.execute(text("INSERT INTO settings (user_id, palette) VALUES (1, 'hanabi')"))
    db.init_db(eng)
    with eng.begin() as c:
        assert c.execute(text("SELECT palette FROM settings WHERE user_id=1")).scalar() == "shuinkan"


def test_old_env_names_still_work():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SHUINKAN_", "HANABI_"))}
    env["HANABI_SESSION_DAYS"] = "7"
    out = subprocess.run([sys.executable, "-c", "import os, app; print(os.environ['SHUINKAN_SESSION_DAYS'])"],
                         cwd=Path(__file__).resolve().parent.parent, env=env, capture_output=True, text=True)
    assert out.stdout.strip() == "7", out.stderr
