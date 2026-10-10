#!/usr/bin/env python3
"""No-build checks for default-OFF policy, prerequisites and exact CLI forwarding."""
import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FLAG = "--store-prefetch-lru-victim"


def call(script, args, accepted=True):
    result = subprocess.run([sys.executable, "-B", str(ROOT / script), *args],
                            text=True, capture_output=True)
    assert (result.returncode == 0) == accepted, (args, result.stdout, result.stderr)
    if not accepted:
        assert FLAG + " requires --store-next-line-prefetch" in result.stderr
        return None
    return json.loads(result.stdout)


def main():
    for path in ("fpga/next/export.py", "simulator/gsim/fpga_next_board.py"):
        ast.parse((ROOT / path).read_text())
    count = 0
    with tempfile.TemporaryDirectory(prefix="store-pf-lru-cli-") as tmp:
        output = Path(tmp) / "must-remain-absent"
        for extra in ([], ["--store-next-line-prefetch"],
                      ["--store-next-line-prefetch", FLAG],
                      ["--store-next-line-prefetch", "--store-prefetch-mru-insertion", FLAG]):
            enabled = FLAG in extra
            native = call("fpga/next/export.py", ["--output", str(output), *extra])
            assert native["status"] == "PREFLIGHT_ONLY" and not output.exists()
            assert native["command"].count(FLAG) == int(enabled)
            assert native["configuration"].get("store_prefetch_lru_victim", False) == enabled
            board = call("simulator/gsim/fpga_next_board.py",
                         ["--tag", "store-lru-preflight", "--preflight-only", "--variant", "selected", *extra])
            assert board["status"] == "PREFLIGHT_ONLY"
            assert board["plan"]["store_prefetch_lru_victim"] == enabled
            assert board["plan"]["parameters"].count(FLAG) == int(enabled)
            count += 2
        call("fpga/next/export.py", ["--output", str(output), FLAG], False)
        call("simulator/gsim/fpga_next_board.py",
             ["--tag", "store-lru-preflight", "--preflight-only", FLAG], False)
        count += 2
    print(f"STORE_PREFETCH_LRU_VICTIM_CLI_PASS cases={count} no_output_created=1")


if __name__ == "__main__":
    main()
