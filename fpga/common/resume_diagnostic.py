#!/usr/bin/env python3
"""One reviewed failed run only; no IP regeneration or qualification."""
import hashlib
import json
from pathlib import Path
import sys

EXPECTED = {
 'blk_mem_gen_0': ('fdf865e38ea41769b3fbd906965e9c455f328b3ee9e79ec625c1e860be623364', 260014),
 'clk_wiz_common': ('0efc15aa18f0a65f3881c80d4fa535a3cd77a33ba9503ca882de66b09cb5bcf7', 12473),
 'ddr4_0': ('4664ca919bb8f3bb81a2a2dd8c57d9809bb94980d91f71e8342201262847986a', 5050922),
}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def verify_dcps(project, expected=EXPECTED):
    result = {}
    for name, (digest, size) in expected.items():
        p = project/'common_board.runs'/(name+'_synth_1')/(name+'.dcp')
        if not p.is_file() or p.stat().st_size != size or sha(p) != digest:
            raise ValueError('OOC DCP changed or missing: '+str(p))
        result[str(p)] = digest
    return result

def check(root):
    # Use the original frozen checker and original manifest, not a rebuilt inventory.
    sys.path.insert(0, str(root/'fpga/common'))
    import diagnostic
    _, manifest, profile = diagnostic.check(root/'diagnostic.json')
    out = root/'diagnostic-run/synthesis'
    if (out/'synthesized.dcp').exists() or (out/'diagnostic-stage.json').exists():
        raise ValueError('Synthesis already completed; do not overwrite it')
    if not (out/'diagnostic-failure.txt').is_file() or not (out/'ip-synthesis.json').is_file():
        raise ValueError('Expected preserved failed stage and successful IP evidence')
    project=out/'project'
    if not (project/'common_board.xpr').is_file(): raise ValueError('Missing original project')
    dcps=verify_dcps(project)
    here=Path(__file__).resolve().parent
    return dict(status=diagnostic.STATUS, profile_sha256=profile,
                original_manifest_sha256=sha(root/'diagnostic.json'),
                project_sha256=sha(project/'common_board.xpr'), ooc_sha256=dcps,
                recovery_tool_sha256={n:sha(here/n) for n in ('resume_diagnostic.py','resume_diagnostic.tcl','synthesize.tcl')})

if __name__=='__main__':
    try: print(json.dumps(check(Path(sys.argv[1]).absolute()), indent=2))
    except (ValueError, OSError) as exc: sys.exit(str(exc))
