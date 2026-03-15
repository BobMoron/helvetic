# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Helvetic is a Django app that replaces the FitBit Aria scale's cloud service. It intercepts scale communication (requires local DNS spoofing to redirect `aria.fitbit.com`) and stores weight/body-fat measurements locally. Implements the FitBit Aria protocol v3 (binary, CRC-16-CCITT/xmodem).

## Commands

All Django commands run from `helv_test/` using the venv:

```bash
# First-time setup
python -m venv env
env/Scripts/pip install -r requirements.txt

# Run the server (must be on port 80 for the scale to reach it)
cd helv_test
PYTHONPATH=/c/Users/bla/git/helvetic ../env/Scripts/python manage.py runserver 0.0.0.0:80

# Database / admin
PYTHONPATH=.. ../env/Scripts/python manage.py migrate
PYTHONPATH=.. ../env/Scripts/python manage.py createsuperuser

# Tests
PYTHONPATH=.. ../env/Scripts/python manage.py test helvetic
```

Test server (simulates an Aria scale for development):
```bash
python testserver/testserver.py [host] [port]
# or via Docker:
docker build -t helvetictest testserver/
docker run -p 8000:8000 -it helvetictest
```

## Deployment / DNS Spoofing

The Aria scale contacts `aria.fitbit.com` — you must redirect that hostname to your server. The scale uses port 80 (not configurable), so helvetic must listen on port 80.

### DNS redirect options (pick one)

**Router custom DNS entry** (simplest if your router supports it):
Add a static DNS override: `aria.fitbit.com → <your server IP>`

**dnsmasq** (run on any Linux box, point your router's DNS at it):
```
# /etc/dnsmasq.conf
address=/aria.fitbit.com/192.168.1.x
```

**Pi-hole** (if already running):
Add under *Local DNS Records*: `aria.fitbit.com → 192.168.1.x`

### nginx reverse proxy (recommended over running Django on port 80 directly)

```nginx
server {
    listen 80;
    server_name aria.fitbit.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
}
```

Then run Django on the default port 8000 without root.

## Architecture

### Request Flow

Scale → DNS spoof → `POST /scale/upload` (aria.fitbit.com) → `ScaleUploadView`

The scale sends binary-packed structs; responses are also binary. See `protocol.md` for the full wire format.

### Key Components

**`helvetic/views/aria_api.py`** — Scale-facing API endpoints:
- `ScaleUploadView` — receives measurements, returns user profiles/preferences. Atomic transaction. CSRF-exempt.
- `ScaleRegisterView` — handles device registration flow
- `ScaleValidateView` — validates auth tokens during setup

**`helvetic/models.py`** — Four models:
- `Scale` — hardware record (MAC, SSID, firmware, auth_code, owner, users M2M)
- `UserProfile` — body data for BMI calculations (height, DOB, gender)
- `Measurement` — weight (grams) + body fat (%) per user per scale
- `AuthorisationToken` — 1-hour expiring tokens for device pairing

**`helvetic/views/webui.py`** — Human-facing views (all login-required): index, scale list, registration UI and curl instructions.

**`testserver/testserver.py`** — Standalone bottle.py server that mimics a real Aria scale. Useful for testing the Django app without physical hardware. Configurable via env vars (`HEL_USER`, `HEL_HEIGHT`, etc.).

### Protocol Notes

- Binary format, little-endian structs, CRC-16-CCITT (xmodem) validation
- Version 3 protocol — `crc16` library handles checksums
- `protocol.md` documents the full message structures
- Auth: scale's `auth_code` (base16) checked on every upload; tokens expire after 1 hour

### Settings

`helv_test/helv_test/settings.py` — SQLite3, `DEBUG=True` by default. The `helvetic` app is in `INSTALLED_APPS`. Static files served from `helvetic/static/`.
