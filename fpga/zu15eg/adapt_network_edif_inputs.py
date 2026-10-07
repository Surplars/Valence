#!/usr/bin/env python3
"""Add only reviewed unused INPUT aliases; do not alter any EDIF logic/net."""
import argparse
import json
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_native_release_contract import require, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("candidate", type=Path)
    a = p.parse_args()
    root = a.candidate
    report = root / "donor-alias-boundaries.txt"
    text = report.read_text(encoding="utf-8")
    rows = re.findall(r"^ALIAS (\w+) (\w+) \{([^}]+)\} DRIVERS=\{([^}]+)\}", text, re.M)
    require(len(rows) == text.count("\nALIAS ") == 11, "Unexpected alias inventory")
    by_top = {}
    for top, direction, name, driver in rows:
        require(direction == "IN", "Never discard an output alias")
        require(top in {"CoherentLineCache", "EthernetPacketDma"}, "Unknown partition")
        require(bool(re.fullmatch(r"io_deq_bits_request_address\[(?:2|6|7)\]_repN(?:_1)?_alias", name)) or
                (top == "EthernetPacketDma" and
                 bool(re.fullmatch(r"io_registers_0_request_bits_data\[[01245]\]_alias", name))),
                "Unknown alias shape")
        require(driver.startswith("u_soc/platform/core/"), "Alias driver is not external to replaced leaf")
        by_top.setdefault(top, []).append(name)
    require(len(by_top["CoherentLineCache"]) == 5 and len(by_top["EthernetPacketDma"]) == 6,
            "Alias interface changed")
    receipt = {}
    for top, names in by_top.items():
        original = root / "partitions" / top / "leaf.edf"
        adapted = original.with_name("leaf_alias.edf")
        require(not adapted.exists(), "Preserve prior EDIF adapter")
        data = original.read_text(encoding="utf-8")
        anchor = re.compile(r"\(cell " + top + r" \(celltype GENERIC\)\s+\(view " +
                            top + r" \(viewtype NETLIST\)\s+\(interface\s*")
        matches = list(anchor.finditer(data))
        require(len(matches) == 1, "Ambiguous top EDIF interface")
        insertion = "".join('(port (rename ECO_UNUSED_INPUT_ALIAS_' + str(n) + ' "' +
                            name + '") (direction INPUT))\n        '
                            for n, name in enumerate(sorted(names)))
        pos = matches[0].end()
        result = data[:pos] + insertion + data[pos:]
        require(result[:pos] + result[pos + len(insertion):] == data,
                "EDIF change must be solely unused input declarations")
        require(all(data.count(name) == 0 for name in names), "Input already used in EDIF")
        adapted.write_text(result, encoding="utf-8")
        receipt[top] = dict(original_sha256=sha(original), adapted_sha256=sha(adapted),
                           input_aliases=sorted(names), functional_net_or_cell_changes=0)
    (root / "edif-input-alias-review.json").write_text(json.dumps(dict(
        status="PASS_ONLY_UNUSED_EXTERNAL_INPUT_ALIASES_ADDED_NOT_NETLIST_EQUIVALENCE",
        donor_boundary_report_sha256=sha(report), partitions=receipt), indent=2) + "\n")
    print("PASS_REVIEWED_UNUSED_INPUT_ALIASES", {top: len(names) for top, names in by_top.items()})


if __name__ == "__main__":
    main()
