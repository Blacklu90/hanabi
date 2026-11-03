@echo off
rem Start Shuinkan on http://127.0.0.1:8000  (first run creates .venv and installs dependencies)
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv
  .venv\Scripts\pip install -q -r requirements.txt
)
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
