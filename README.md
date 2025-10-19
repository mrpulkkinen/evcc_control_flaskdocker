# EVCC Web UI (Flask)

A simple web interface to control an **evcc** charger over its local API.  
Includes **mode switching**, **max current control**, **live status**, and a **safety cooldown** to prevent rapid mode flapping (default 120 seconds).

Works great alongside **Home Assistant**, but **does not depend on it** – connects directly to evcc on your LAN.

---

## ✅ Features

- Control evcc modes: **Start (now), Stop (off), PV, MinPV**
- Adjustable **max current** (amps)
- **Live status**: grid power, PV power, home consumption, loadpoint status
- **Cooldown protection**: prevents switching mode too frequently (default: 120 sec)
- Supports **multiple loadpoints**
- **Zero authentication** needed if evcc has no password
- **Dockerized** – easy to run on any system
- No internet required – **local network only**

---

## 🚀 Requirements

| Component       | Requirement                     |
|-----------------|----------------------------------|
| evcc instance   | Already running and reachable   |
| API Access      | `http://<evcc-ip>:7070/api`     |
| Network         | Same LAN (e.g. `192.168.1.0/24`) |
| Docker          | Yes                             |

---

## 📦 Setup

Clone this project and inside the folder ensure you have these files:

app.py
Dockerfile
docker-compose.yml
requirements.txt

yaml
Copy code

---

## ⚙️ Configure

Edit `docker-compose.yml` and set your evcc IP:

```yaml
environment:
  EVCC_BASE_URL: "http://youripCHANGEME:7070/api"
  DEFAULT_LP_ID: "1"
  MODE_COOLDOWN_SECONDS: "120"
▶️ Run
bash
Copy code
docker compose up -d --build
Then open in your browser:

cpp
Copy code
http://<your-docker-host>:5080/
Example: http://192.168.1.28:5080/
