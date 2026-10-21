"""Prepare a fresh native synthesis from a verified baseline and fresh emission.

Reuses existing IP products without copying, generating or upgrading them.
Does not launch Vivado. No baseline output is modified.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import tkinter


def sha(path):
    return hashlib.file_digest(Path(path).open('rb'), 'sha256').hexdigest()


def tcl(path):
    value = Path(path).resolve().as_posix()
    if any(c in value for c in '{}\n\r'):
        raise ValueError('Unsupported path characters')
    return '{' + value + '}'


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--baseline', required=True, type=Path)
p.add_argument('--rtl', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
p.add_argument('--source-commit', required=True)
a = p.parse_args()
assert re.fullmatch('[0-9a-f]{40}', a.source_commit)
assert not a.output.exists(), 'Preserve previous outputs: choose fresh directory'
repo = Path(__file__).resolve().parent.parent
old = json.loads((a.baseline / 'synthesis-inputs.json').read_text(encoding='utf-8-sig'))
profile = json.loads((a.rtl / 'emission-profile.json').read_text())
for key, value in old['configuration'].items():
    assert profile[key] == value, (key, profile[key], value)
for field in ('copied_files', 'readonly_stub_sha256', 'constraints_sha256'):
    for path, expected in old[field].items():
        assert sha(path) == expected, f'Changed baseline dependency: {path}'
config = (a.baseline / 'synthesis-config.tcl').read_text()
interp = tkinter.Tcl()
line = next(x for x in config.splitlines() if x.startswith('set recovery(rtl) '))
sources = interp.splitlist(line.split('[list ', 1)[1][:-1])
board = [Path(x) for x in sources if not re.search(r'/out/[^/]+/[^/]+\.sv$', x)]
assert len(board) == 6, board
rtl = sorted(a.rtl.glob('*.sv')) + board
assert rtl and all(x.is_file() for x in rtl)
rtl_line = 'set recovery(rtl) [list ' + ' '.join(tcl(x) for x in rtl) + ']'
config = config.replace(line, rtl_line)
config = re.sub(r'^set recovery\(output\) .*$', 'set recovery(output) ' + tcl(a.output), config, flags=re.M)
receipt = dict(old)
receipt.update(name=a.output.name, production_source_commit=a.source_commit,
               emission_profile_sha256=sha(a.rtl / 'emission-profile.json'),
               rtl_sha256={str(x.resolve()): sha(x) for x in rtl},
               ip_regenerated=False, physical_qualified=False, place_route_permitted=False,
               baseline_inputs_sha256=sha(a.baseline / 'synthesis-inputs.json'))
a.output.mkdir(parents=True)
(a.output / 'synthesis-config.tcl').write_text(config)
(a.output / 'synthesis-inputs.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'output': str(a.output), 'rtl_sources': len(rtl),
                  'profile_sha256': receipt['emission_profile_sha256'],
                  'action': 'PREPARED_ONLY_NO_VIVADO_STARTED'}))
