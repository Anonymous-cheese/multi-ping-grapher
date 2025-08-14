# Multi-Ping Grapher

Ping multiple hosts with live graphs for **latency**, **packet loss**, and **jitter**. CSV logging optional.
- Hidden `ping.exe` (no flashing consoles)
- Set interval/timeout/packet size, IPv4/IPv6
- Rolling loss and EWMA jitter
- Windows EXE built automatically via GitHub Actions

## Quick Run (dev)
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python src\multi_ping_grapher.py
```

## Build EXE locally
```
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name MultiPingGrapher src\multi_ping_grapher.py
```
Output: `dist\MultiPingGrapher.exe`

## CI: GitHub Actions
- On every push to `main`: build the EXE and upload as pipeline artifact.
- On tag `v*`: build and attach EXE to a GitHub Release automatically.

## License
MIT
