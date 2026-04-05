# testserver

Two standalone tools for working with the FitBit Aria protocol without running the full Helvetic Django stack. Both require `crcmod` (`pip install -r testserver/requirements.txt`). Do not expose either to the public internet.

---

## testserver.py — fake Fitbit cloud

Implements the Aria upload API (`POST /scale/upload`). Point a real Aria scale at it via DNS spoof to observe decoded measurements without a database. Logs to stdout; status page at `http://localhost/`.

### Running

```sh
# Direct (must be port 80 so the scale can reach it):
env/Scripts/python testserver/testserver.py 0.0.0.0 80

# Docker (maps container port 8000 to host port 80):
docker build -t helvetictest testserver/
docker run -p 80:8000 -e HEL_USER=alice -it helvetictest
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HEL_USER` | `EXAMPLE` | Display name (≤20 chars, ASCII) |
| `HEL_MIN_TOLERANCE` | `89000` | Minimum weight tolerance, grams |
| `HEL_MAX_TOLERANCE` | `97000` | Maximum weight tolerance, grams |
| `HEL_BIRTHYEAR` | `1970` | Year of birth (used to compute age) |
| `HEL_GENDER` | unset | `f` = female, `m` = male, unset = unknown |
| `HEL_HEIGHT` | `1900` | Height in millimetres |

---

## scaleclient.py — Aria scale simulator

Constructs and sends a valid Aria v3 binary upload request. Primary use: validating DNS spoof end-to-end without a physical scale. Sends one measurement, prints the decoded server response, and exits.

The scale must already exist in the Helvetic database (registered via the web UI or admin). No registration flow is simulated.

### Running

```sh
# Against aria.fitbit.com — validates DNS spoof is working:
env/Scripts/python testserver/scaleclient.py \
    --mac AABBCCDDEEFF \
    --auth <32-hex-auth-code> \
    --weight 80000

# Against a local Helvetic instance — bypasses DNS spoof:
env/Scripts/python testserver/scaleclient.py \
    --host localhost --port 8000 \
    --mac AABBCCDDEEFF \
    --auth <32-hex-auth-code> \
    --weight 80000
```

**Finding `--mac` and `--auth`:** both are on the Scale record in the Django admin (`/admin/helvetic/scale/`). MAC is the hardware address (12 hex chars, no colons); auth is the `auth_code` field (32 hex chars).

### Options

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

### Example output

```
Connecting to localhost:8000
MAC: AABBCCDDEEFF  auth: DDDDDDDD...  weight: 80000g  user_id: 1  body_fat: 0.0%
HTTP 200  104 bytes received
Server timestamp: 1741996800
Units: kilograms
Status: 0x32
Users (1):
  [1] ALICE                 age=35  gender=female    height=1700mm  tolerance=76000-84000g
```
