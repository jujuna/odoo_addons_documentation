"""Secure Dynamic Messaging (SDM) of NTAG 424 DNA and DESFire EV3 badges, see NXP AN12196.

At every read the chip writes into the URL of its NDEF record its UID, a
read counter and a CMAC signature computed with the encoding key, e.g.
https://odoo.com/badge?uid=04DE5F1EACC040&ctr=000001&cmac=94EED9EE65337086
"""
import re

from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.cmac import CMAC

from odoo.tools import consteq

# AES-128 key the badges were encoded with, in hex.
ENCODING_KEY = re.compile(r'^[0-9A-Fa-f]{32}$')
# Session vector prefix of the SDM MAC session key (AN12196, SV2).
SESSION_PREFIX = bytes.fromhex('3CC300010080')
# UID, read counter and MAC as the chip mirrors them in the URL of the badge.
PAYLOAD = re.compile(r'uid=([0-9A-F]{14})&ctr=([0-9A-F]{6})&cmac=([0-9A-F]{16})', re.IGNORECASE)


def cmac(key, message):
    mac = CMAC(algorithms.AES(key))
    mac.update(message)
    return mac.finalize()


def sdm_mac(key, uid, counter):
    """MAC the chip writes for this UID and counter (counter little endian in the session vector)."""
    session_key = cmac(key, SESSION_PREFIX + uid + counter.to_bytes(3, 'little'))
    # The chip keeps the odd bytes of the CMAC of an empty message.
    return cmac(session_key, b'')[1::2]


def parse(payload):
    """Return (uid, counter, mac) from a badge read, or None when it carries no SDM data."""
    match = PAYLOAD.search(payload or '')
    return match and (bytes.fromhex(match[1]), int(match[2], 16), bytes.fromhex(match[3]))


def is_genuine(key, uid, counter, mac):
    """Whether the MAC was produced by a badge encoded with this key."""
    return consteq(sdm_mac(key, uid, counter), mac)
