#!/usr/bin/env python3
"""Bind a preserved optimized checkpoint to frozen inputs and lookup-only tools."""
import json
from pathlib import Path
import re
import sys
from resume_diagnostic import check, sha

TOOLS = ('resume_cached_post_opt.py', 'resume_cached_post_opt.tcl',
         'resume_diagnostic.py', 'exact_object_cache.tcl',
         'cached_post_opt.tcl', 'test_exact_object_cache.tcl')

def verify_checkpoint(root, expected):
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('An explicit observed optimized checkpoint SHA256 is required')
    checkpoint = root/'diagnostic-run/implementation/optimized-unqualified.dcp'
    if not checkpoint.is_file() or sha(checkpoint) != expected:
        raise ValueError('Preserved optimized checkpoint missing or changed')
    return checkpoint

def prepare(root, expected):
    record = check(root, 'implementation')
    checkpoint = verify_checkpoint(root, expected)
    here = Path(__file__).resolve().parent
    record.update(mode='cached-post-opt-only', optimized_checkpoint=str(checkpoint),
                  optimized_checkpoint_sha256=expected,
                  cache_overlay_sha256={n: sha(here/n) for n in TOOLS},
                  qualification=False)
    return record

if __name__ == '__main__':
    try:
        if len(sys.argv) != 3: raise ValueError('usage: ROOT OBSERVED_OPTIMIZED_SHA256')
        print(json.dumps(prepare(Path(sys.argv[1]).resolve(), sys.argv[2]), indent=2))
    except (ValueError, OSError) as exc:
        sys.exit(str(exc))
