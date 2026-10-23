#!/usr/bin/env python3
"""Short four-state test of emitted real reset RTL, with ordinary oracle negatives."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rtl", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    args.out.mkdir(parents=True, exist_ok=True)
    bench = Path(__file__).with_name("reset_distribution_tb.sv")
    rtl = sorted(args.rtl.glob("*.sv"))
    if not rtl:
        raise SystemExit("No emitted RTL")
    binary = args.out / "reset_distribution.vvp"
    subprocess.run(["iverilog", "-g2012", "-s", "reset_distribution_tb", "-o", str(binary),
                    *map(str, rtl), str(bench)], check=True, timeout=30)
    cases = []
    for name, expected in (("normal", None),
                           ("early_release", "distribution release must take exactly four edges"),
                           ("lost_owner", "ordinary clock stop lost accepted owner")):
        result = subprocess.run(["vvp", str(binary), *([] if expected is None else ["+" + name])],
                                text=True, capture_output=True, timeout=30)
        output = result.stdout + result.stderr
        (args.out / (name + ".log")).write_text(output)
        accepted = result.returncode == 0 and "RESET_DISTRIBUTION_PASS" in output
        rejected = result.returncode != 0 and expected is not None and expected in output
        if not (accepted if expected is None else rejected):
            raise SystemExit(f"Unexpected {name} result: {output}")
        cases.append({"case": name, "result": "PASS" if expected is None else "REJECTED_BY_ORACLE",
                      "exit_code": result.returncode, "output": output.strip()})
    source = [root / p for p in (
        "src/main/scala/ip/bus/ClockDomainCrossing.scala",
        "src/main/scala/platform/CommonMachinePlatform.scala",
        "src/test/scala/platform/CommonResetDistributionMain.scala")]
    files = [*source, *rtl, bench, Path(__file__)]
    receipt = {"scope": "real reset chain and one retained-owner register, not full CPU/STA/board",
               "cases": cases, "sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (args.out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(cases, indent=2))


if __name__ == "__main__":
    main()
