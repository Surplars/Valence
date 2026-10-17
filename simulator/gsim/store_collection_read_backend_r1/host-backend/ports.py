"""Normalized scalar public boundaries, mechanically bound to exact FIR/header."""
import json
from pathlib import Path
_SCHEMA = json.loads(Path(__file__).with_name('SCHEMA.json').read_text())
INPUT_WIDTHS = _SCHEMA['inputs']
OUTPUT_WIDTHS = _SCHEMA['outputs']
REQUEST_WIDTHS = _SCHEMA['request']
PROOF_WIDTHS = {'token.index': 4, 'token.tag': 64, 'epoch': 32, 'address': 64,
               'data': 64, 'mask': 8, 'size': 2, 'headAuthorized': 1,
               'physicalPmpAllowed': 1, 'originalPhysical': 1, 'integerOrigin': 1,
               'legacyPostedAccepted': 1, 'finalChecked': 1}
