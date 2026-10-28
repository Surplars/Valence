#!/usr/bin/env python3
"""Mutate files/transcripts as data only; never execute any ELF."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile

from source_reference import SourceProgram, ReferenceError, compare_transcripts, inspect_elf

HERE = Path(__file__).parent
ROOT = HERE.resolve().parents[4]
SOURCE = ROOT / "simulator/gsim/payloads/branch-program.S"
sha = lambda data: hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    ELF, OTHER = args.elf, args.reference
    p = SourceProgram(SOURCE.read_text())
    expected = p.run()
    binary = ELF.read_bytes()
    actual = json.loads(OTHER.read_text())
    positive = inspect_elf(ELF, p)
    compare_transcripts(expected, actual)
    cases = []
    h = struct.unpack_from("<16sHHIQQQIHHHHHH", binary)
    phoff, shoff, phsize, phnum, shsize, shnum, shstr = h[5], h[6], h[9], h[10], h[11], h[12], h[13]
    sections = [struct.unpack_from("<IIQQQQIIQQ", binary, shoff + n * shsize) for n in range(shnum)]
    strings = binary[sections[shstr][4]:sections[shstr][4] + sections[shstr][5]]
    string = lambda table, at: table[at:table.index(0, at)].decode()
    named = {string(strings, s[0]): (index, s) for index, s in enumerate(sections)}
    text_index, text = named[".text"]
    load_offset = next(phoff + n * phsize for n in range(phnum) if struct.unpack_from("<I", binary, phoff + n * phsize)[0] == 1)
    markers = {}
    for s in sections:
        if s[1] == 2:
            st = sections[s[6]]
            names = binary[st[4]:st[4] + st[5]]
            for offset in range(s[4], s[4] + s[5], s[9]):
                item = struct.unpack_from("<IBBHQQ", binary, offset)
                if item[0]:
                    markers[string(names, item[0])] = (offset, item)

    def reject_binary(name, mutate):
        changed = bytearray(binary)
        mutate(changed)
        with tempfile.TemporaryDirectory(dir=args.out) as temporary:
            path = Path(temporary) / "mutant.data"
            path.write_bytes(changed)
            try:
                inspect_elf(path, p)
            except ReferenceError as error:
                cases.append({"name": name, "category": "ELF_data_mutation", "rejected": True, "reason": str(error)})
                return
        raise RuntimeError(f"negative not rejected: {name}")

    reject_binary("ET_REL_is_not_executable", lambda b: struct.pack_into("<H", b, 16, 1))
    reject_binary("wrong_machine", lambda b: struct.pack_into("<H", b, 18, 62))
    reject_binary("entry_shift", lambda b: struct.pack_into("<Q", b, 24, h[4] + 4))
    reject_binary("LOAD_outside_RAM", lambda b: struct.pack_into("<Q", b, load_offset + 24, 0x80000000))
    reject_binary("LOAD_does_not_cover_text", lambda b: struct.pack_into("<Q", b, load_offset + 32, 4))
    reject_binary("writable_segment", lambda b: struct.pack_into("<I", b, load_offset + 4, struct.unpack_from("<I", b, load_offset + 4)[0] | 2))
    reject_binary("body_instruction_changed", lambda b: b.__setitem__(text[4], b[text[4]] ^ 1))
    terminal_file = text[4] + p.labels["benchmark_terminal"] - text[3]
    reject_binary("terminal_changed_to_NOP", lambda b: struct.pack_into("<I", b, terminal_file, 0x13))
    reject_binary("text_address_shift", lambda b: struct.pack_into("<Q", b, shoff + text_index * shsize + 16, text[3] + 4))
    reject_binary("unresolved_relocations", lambda b: struct.pack_into("<I", b, shoff + text_index * shsize + 4, 4))
    roi_offset, roi = markers["roi_end"]
    reject_binary("roi_marker_wrong_value", lambda b: struct.pack_into("<Q", b, roi_offset + 8, roi[4] + 4))
    reject_binary("roi_marker_not_exported", lambda b: b.__setitem__(roi_offset + 4, b[roi_offset + 4] & 15))
    complete_offset, _ = markers["benchmark_complete"]
    reject_binary("duplicate_marker_identity", lambda b: struct.pack_into("<I", b, complete_offset, roi[0]))
    reject_binary("truncated_file", lambda b: b.__delitem__(slice(64, None)))

    def reject_trace(name, mutate):
        changed = copy.deepcopy(actual)
        mutate(changed)
        try:
            compare_transcripts(expected, changed)
        except ReferenceError as error:
            cases.append({"name": name, "category": "distinct_ISA_transcript_mutation", "rejected": True, "reason": str(error)})
            return
        raise RuntimeError(f"negative not rejected: {name}")

    for field in ("pc", "instruction", "nextPc", "rd", "writes", "data"):
        reject_trace("event_" + field, lambda t, f=field: t["events"][10].__setitem__(f, t["events"][10][f] ^ 1))
    reject_trace("event_deleted", lambda t: t["events"].__delitem__(10))
    reject_trace("event_duplicated", lambda t: t["events"].insert(10, t["events"][10]))
    reject_trace("event_field_missing", lambda t: t["events"][10].__delitem__("nextPc"))
    reject_trace("full_GPR_corruption", lambda t: t["regs"].__setitem__(11, t["regs"][11] ^ 1))
    for field in ("retired", "roi_begin_index", "roi_end_index"):
        reject_trace(field, lambda t, f=field: t.__setitem__(f, t[f] + 1))
    for field in ("pc", "cause", "tval"):
        reject_trace("terminal_" + field, lambda t, f=field: t["terminal"].__setitem__(f, t["terminal"][f] ^ 1))
    reject_trace("terminal_metadata_absent", lambda t: t.__delitem__("terminal"))
    receipt = {"status": "PASS_DISTINCT_REFERENCE_AND_CONTAINER_NEGATIVES", "cpu_executed": False,
               "source_sha256": sha(SOURCE.read_bytes()), "evaluator_sha256": sha((HERE / "source_reference.py").read_bytes()),
               "test_sha256": sha(Path(__file__).read_bytes()), "elf_sha256": sha(binary),
               "distinct_reference_sha256": sha(OTHER.read_bytes()), "positive": positive,
               "retired": expected["retired"], "roi_retired": expected["roi_end_index"] - expected["roi_begin_index"],
               "rejected_cases": len(cases), "cases": cases}
    (args.out / "negative-qualification.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"SOURCE_LINKED_QUALIFICATION_PASS negative_cases={len(cases)} retired={expected['retired']}")


if __name__ == "__main__":
    main()
