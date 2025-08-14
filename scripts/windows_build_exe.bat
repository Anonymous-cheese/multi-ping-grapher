@echo off
setlocal
if not exist .venv (
  py -3 -m venv .venv
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name MultiPingGrapher src\multi_ping_grapher.py
echo Built dist\MultiPingGrapher.exe
pause
