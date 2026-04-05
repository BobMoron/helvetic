# helvetic

*helvetic* replaces the FitBit cloud service for the Aria Wi-Fi Smart Scale. It intercepts the scale's HTTP traffic locally, stores weight and body-fat measurements in a SQLite database, and provides a web UI for viewing data, managing users, and exporting/importing history.

Requires local DNS spoofing to redirect `aria.fitbit.com` to your server. Implements the FitBit Aria protocol v3 (binary, CRC-16-CCITT/xmodem).

---

## Features

- **Scale integration** — receives measurements from the Aria, responds with user profiles and preferences
- **Device registration** — full WiFi setup flow with curl-based AP configuration and browser-based status polling
- **User profiles** — height, DOB, gender (used for BMI/body-fat calculations)
- **Scale configuration** — assign users to a scale, choose display unit (kg / lbs / stones)
- **Measurement history** — paginated list and Chart.js graph (last 365 readings)
- **CSV export** — download your data in helvetic format (`date`, `weight_kg`, `body_fat_pct`)
- **CSV import** — import history from helvetic exports or Fitbit weight exports (kg or lbs); duplicates skipped automatically
- **User management** — staff users can create, list, and deactivate accounts

---

## Requirements

- Python 3.x with the `env/` virtualenv (see setup below)
- Port 80 available, or nginx in front of Django on port 8000
- A way to redirect `aria.fitbit.com` DNS to your server (see DNS section)

---

## Setup

```bash
# Clone and create virtualenv
python -m venv env
env/Scripts/pip install -r requirements.txt   # Windows
# env/bin/pip install -r requirements.txt     # Linux/macOS

# Initialise the database
cd helv_test
PYTHONPATH=.. ../env/Scripts/python manage.py migrate
PYTHONPATH=.. ../env/Scripts/python manage.py createsuperuser
```

---

## Running

The scale contacts port 80 — you must either run Django directly on port 80 or put nginx in front.

**Direct (port 80, requires root/admin):**
```bash
cd helv_test
PYTHONPATH=/path/to/helvetic ../env/Scripts/python manage.py runserver 0.0.0.0:80
```

**Recommended — nginx reverse proxy + Django on port 8000:**
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
```bash
cd helv_test
PYTHONPATH=/path/to/helvetic ../env/Scripts/python manage.py runserver 0.0.0.0:8000
```

---

## DNS Spoofing

The Aria contacts `aria.fitbit.com` — you must redirect that hostname to your server's IP.

**Router custom DNS** (simplest): add a static DNS override `aria.fitbit.com → <your server IP>`.

**dnsmasq:**
```
# /etc/dnsmasq.conf
address=/aria.fitbit.com/192.168.1.x
```

**Pi-hole:** add under *Local DNS Records*: `aria.fitbit.com → 192.168.1.x`

---

## Registering a Scale

1. Log in and go to **Scales → Register new scale**.
2. Follow the curl instructions — they give you the exact command to send to the scale's temporary AP (`192.168.240.1`).
3. After running the curl command, reconnect your computer to your home network and click **Check status** — the page polls automatically until the scale checks in.

---

## Using the Web UI

| URL | What it does |
|-----|-------------|
| `/` | Dashboard |
| `/profile/` | View your profile |
| `/profile/edit/` | Set height, DOB, gender, display name |
| `/scales/` | List scales you own or are assigned to |
| `/scales/<id>/edit/` | Set display unit, assign user profiles |
| `/scales/register/` | Register a new scale |
| `/measurements/` | Paginated measurement history |
| `/measurements/graph/` | Weight and body-fat chart |
| `/measurements/export.csv` | Download your data as CSV |
| `/measurements/import/` | Import from helvetic or Fitbit CSV |
| `/users/` | User list (staff only) |
| `/users/create/` | Create a user (staff only) |
| `/admin/` | Django admin |

---

## Development

**Run tests:**
```bash
cd helv_test
PYTHONPATH=.. ../env/Scripts/python manage.py test helvetic
# 148 tests, ~1s
```

**Test server** (lightweight stand-in for the FitBit cloud API, for protocol exploration):

Point a real Aria scale at it via DNS spoof (same setup as Helvetic). It decodes and logs measurements to stdout without the full Django stack. Visit `http://localhost/` for config and recent log.

```bash
# Install testserver dependencies (separate from the main app)
env/Scripts/pip install -r testserver/requirements.txt

# Must listen on port 80 so the scale can reach it
env/Scripts/python testserver/testserver.py 0.0.0.0 80

# or via Docker:
docker build -t helvetictest testserver/
docker run -p 80:8000 -it helvetictest
```

Configure via env vars: `HEL_USER`, `HEL_HEIGHT`, `HEL_BIRTHYEAR`, `HEL_GENDER`, `HEL_MIN_TOLERANCE`, `HEL_MAX_TOLERANCE`.

**Scale client** (Aria scale simulator — validates DNS spoof end-to-end without a physical scale):

Sends one valid Aria v3 upload to `aria.fitbit.com` (or a specified host). With DNS correctly spoofed, the request reaches your local Helvetic instance. The scale must already exist in the database.

```bash
# Requires the testserver dependencies (crcmod)
env/Scripts/pip install -r testserver/requirements.txt

env/Scripts/python testserver/scaleclient.py \
    --mac AABBCCDDEEFF \
    --auth <32-hex-auth-code> \
    --weight 80000

# Override target for local testing (bypasses DNS spoof):
env/Scripts/python testserver/scaleclient.py \
    --host localhost --port 8000 \
    --mac AABBCCDDEEFF --auth <32-hex> --weight 80000
```

| Option | Env var | Default | Description |
|--------|---------|---------|-------------|
| `--host` | `HEL_HOST` | `aria.fitbit.com` | Target hostname |
| `--port` | `HEL_PORT` | `80` | Target port |
| `--mac` | `HEL_MAC` | *(required)* | Scale MAC, 12 hex chars, no colons |
| `--auth` | `HEL_AUTH_CODE` | *(required)* | Auth code, 32 hex chars |
| `--weight` | `HEL_WEIGHT` | `80000` | Weight in grams |
| `--user-id` | `HEL_USER_ID` | `1` | User slot 1–8 |
| `--body-fat` | `HEL_BODY_FAT` | `0.0` | Body fat % |
| `--battery` | `HEL_BATTERY` | `80` | Battery % |
| `--firmware` | `HEL_FIRMWARE` | `0` | Firmware version |

---

## See also

- `protocol.md` — FitBit Aria protocol v3 wire format
- `firmware.md` — firmware notes
- `docs/plans/` — feature plans and implementation notes
