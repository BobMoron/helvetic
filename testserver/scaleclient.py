#!/usr/bin/env python
"""
scaleclient.py — Aria scale simulator for Helvetic

Constructs and sends a valid Aria v3 binary upload request to a Helvetic
server (or aria.fitbit.com with DNS spoofing). Primary use: validating
end-to-end DNS spoof setup without a physical scale.

Usage:
    env/Scripts/python testserver/scaleclient.py --mac AABBCCDDEEFF --auth <32-hex> --weight 80000

Config can also come from environment variables; see --help.
"""
from __future__ import print_function

import argparse
import http.client
import os
import struct
from time import time

from crcmod.predefined import mkCrcFun
crc16xmodem = mkCrcFun('xmodem')

UNITS = {0: 'pounds', 1: 'stone', 2: 'kilograms'}
GENDERS = {0x00: 'female', 0x02: 'male', 0x34: 'unknown'}

# Size of one serialised aria_user record in the response
_USER_STRUCT = '<L16x20sLLLBLLLLLL'
_USER_SIZE = struct.calcsize(_USER_STRUCT)  # 77


def build_request(mac_hex, auth_hex, weight_g, user_id=1, body_fat=0.0,
                  battery_pc=80, fw_ver=0, ts=None):
    """
    Build a binary Aria v3 upload request.

    Returns raw bytes suitable for POST /scale/upload.
    mac_hex  : 12-char hex string (no colons)
    auth_hex : 32-char hex string
    weight_g : weight in grams
    """
    if ts is None:
        ts = int(time())
    mac_bytes = bytes.fromhex(mac_hex.upper())
    auth_bytes = bytes.fromhex(auth_hex.upper())

    header = struct.pack('<LL6s16s', 3, battery_pc, mac_bytes, auth_bytes)

    fat = int(body_fat * 1000)
    body = struct.pack('<LLLL', fw_ver, 33, ts, 1)
    measurement = struct.pack('<LLLLLLLL', 2, 0, weight_g, ts, user_id, fat, 0, fat)

    crc = crc16xmodem(body + measurement)
    return header + body + measurement + struct.pack('<H', crc)


def parse_response(data):
    """
    Parse a binary Aria v3 upload response.

    Returns a dict with keys: ts, units, status, users (list of dicts).
    Raises ValueError on CRC failure or truncated data.
    """
    # Minimum: 11-byte response header + 12-byte trailer + 4-byte CRC/size
    if len(data) < 27:
        raise ValueError('Response too short (%d bytes)' % len(data))

    body = data[:-4]
    crc, size = struct.unpack('<HH', data[-4:])
    computed = crc16xmodem(body)
    if computed != crc:
        raise ValueError('CRC mismatch: expected 0x%04x, got 0x%04x' % (crc, computed))

    ts, units, status, unknown1, user_count = struct.unpack('<LBBBL', body[:11])
    offset = 11

    users = []
    for _ in range(user_count):
        if offset + _USER_SIZE > len(body):
            break
        uid, name, min_w, max_w, age, gender, height, w1, fat, covar, w2, uts = \
            struct.unpack(_USER_STRUCT, body[offset:offset + _USER_SIZE])
        users.append({
            'user_id': uid,
            'name': name.rstrip(b'\x00').decode('ascii', errors='replace').strip(),
            'min_weight_g': min_w,
            'max_weight_g': max_w,
            'age': age,
            'gender': GENDERS.get(gender, '0x%02x' % gender),
            'height_mm': height,
        })
        offset += _USER_SIZE

    return {
        'ts': ts,
        'units': UNITS.get(units, '0x%02x' % units),
        'status': '0x%02x' % status,
        'users': users,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Aria scale simulator — sends one upload to a Helvetic server')
    parser.add_argument('--host', default=os.environ.get('HEL_HOST', 'aria.fitbit.com'),
                        help='Target hostname (default: aria.fitbit.com, or HEL_HOST)')
    parser.add_argument('--port', type=int,
                        default=int(os.environ.get('HEL_PORT', 80)),
                        help='Target port (default: 80, or HEL_PORT)')
    parser.add_argument('--mac', default=os.environ.get('HEL_MAC', ''),
                        help='Scale MAC, 12 hex chars, no colons (required, or HEL_MAC)')
    parser.add_argument('--auth', default=os.environ.get('HEL_AUTH_CODE', ''),
                        help='Auth code, 32 hex chars (required, or HEL_AUTH_CODE)')
    parser.add_argument('--weight', type=int,
                        default=int(os.environ.get('HEL_WEIGHT', 80000)),
                        help='Weight in grams (default: 80000, or HEL_WEIGHT)')
    parser.add_argument('--user-id', type=int,
                        default=int(os.environ.get('HEL_USER_ID', 1)),
                        help='User slot 1-8 (default: 1, or HEL_USER_ID)')
    parser.add_argument('--body-fat', type=float,
                        default=float(os.environ.get('HEL_BODY_FAT', 0.0)),
                        help='Body fat %% (default: 0.0, or HEL_BODY_FAT)')
    parser.add_argument('--battery', type=int,
                        default=int(os.environ.get('HEL_BATTERY', 80)),
                        help='Battery %% (default: 80, or HEL_BATTERY)')
    parser.add_argument('--firmware', type=int,
                        default=int(os.environ.get('HEL_FIRMWARE', 0)),
                        help='Firmware version (default: 0, or HEL_FIRMWARE)')
    args = parser.parse_args()

    if not args.mac:
        parser.error('--mac is required (or set HEL_MAC)')
    if not args.auth:
        parser.error('--auth is required (or set HEL_AUTH_CODE)')
    if len(args.mac) != 12:
        parser.error('--mac must be exactly 12 hex characters')
    if len(args.auth) != 32:
        parser.error('--auth must be exactly 32 hex characters')

    payload = build_request(
        mac_hex=args.mac,
        auth_hex=args.auth,
        weight_g=args.weight,
        user_id=args.user_id,
        body_fat=args.body_fat,
        battery_pc=args.battery,
        fw_ver=args.firmware,
    )

    print('Connecting to %s:%d' % (args.host, args.port))
    print('MAC: %s  auth: %s  weight: %dg  user_id: %d  body_fat: %.1f%%' % (
        args.mac.upper(), args.auth.upper(), args.weight, args.user_id, args.body_fat))

    conn = http.client.HTTPConnection(args.host, args.port, timeout=10)
    conn.request('POST', '/scale/upload', body=payload, headers={
        'Content-Type': 'application/octet-stream',
        'Content-Length': str(len(payload)),
        'Host': 'aria.fitbit.com',
    })
    resp = conn.getresponse()
    data = resp.read()
    conn.close()

    print('HTTP %d  %d bytes received' % (resp.status, len(data)))
    if resp.status != 200:
        print('Error: server returned %d' % resp.status)
        return

    try:
        result = parse_response(data)
    except ValueError as e:
        print('Parse error: %s' % e)
        return

    print('Server timestamp: %d' % result['ts'])
    print('Units: %s' % result['units'])
    print('Status: %s' % result['status'])
    print('Users (%d):' % len(result['users']))
    for u in result['users']:
        print('  [%d] %-20s  age=%d  gender=%-7s  height=%dmm  tolerance=%d-%dg' % (
            u['user_id'], u['name'], u['age'], u['gender'],
            u['height_mm'], u['min_weight_g'], u['max_weight_g']))


if __name__ == '__main__':
    main()
