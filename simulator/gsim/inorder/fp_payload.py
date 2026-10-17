"""Generate independent SoftFloat-backed actual-CPU checks; no DUT decoder imported."""
import struct
from pathlib import Path

def generate(vectors: Path, output: Path, double: bool):
    lines = [".option norvc", ".option norelax", ".section .text.start", ".globl _start", "_start:",
             "li sp,0x80b00000", "la t0,fail", "csrw mtvec,t0", "li s0,0x80a00000",
             "sd zero,0(s0)", "sd zero,8(s0)", "li t0,0x2000", "csrs mstatus,t0", "li s1,0"]
    data = []
    cases = 0
    families = set()
    for index, row in enumerate(vectors.read_text().splitlines()):
        inst, rm, a, b, c, integer, value, flags = [int(x, 16) for x in row.split()]
        # Fixed independent edge/corner/random subset, all operations and rounding modes.
        if index % 96 not in (2, 10, 15, 17, 19, 20, 40, 95):
            continue
        op = inst & 127
        function = inst >> 25
        is_double = bool(inst & (1 << 25))
        conversion = op == 0x53 and function in (0x20, 0x21)
        if not double:
            if is_double or conversion:
                continue
            # Physical FLEN32 has no unboxed-high-half state. Only independently boxed S cases are reachable.
            if any(x >> 32 != 0xffffffff for x in (a, b, c)):
                continue
        integer_result = op == 0x53 and (function & ~1) in (0x50, 0x60, 0x70)
        uses_rounding = op in (0x43, 0x47, 0x4b, 0x4f) or (
            op == 0x53 and (function & ~1) in (0x00, 0x04, 0x08, 0x0c, 0x2c, 0x20, 0x60, 0x68))
        instruction = inst
        if uses_rounding and cases % 2:
            instruction = (instruction & ~(7 << 12)) | (7 << 12)
        lines += ["la s4,row_" + str(cases), "csrw fflags,zero", "li t0," + str(rm), "csrw frm,t0"]
        load = "fld" if double else "flw"
        lines += [load + " f1,0(s4)", load + " f2,8(s4)", load + " f3,16(s4)", "ld x1,24(s4)",
                  ".4byte " + hex(instruction)]
        lines += ["mv t0,x3" if integer_result else ("fmv.x.d t0,f3" if double else "fmv.x.w t0,f3")]
        if not double and not integer_result:
            lines += ["slli t0,t0,32", "srli t0,t0,32"]
            value &= 0xffffffff
        lines += ["ld t3,32(s4)", "bne t0,t3,fail", "csrr t1,fflags", "ld t2,40(s4)",
                  "bne t1,t2,fail", "addi s1,s1,1"]
        data += ["row_" + str(cases) + ":", ".dword " + ",".join(hex(x) for x in (a, b, c, integer, value, flags))]
        families.add((op, function if op == 0x53 else int(is_double), (inst >> 20) & 31))
        cases += 1
    lines += ["sd s1,8(s0)", "li t0,0x46504450415353", "sd t0,0(s0)", "li a0,0",
              "la t0,completed", "csrw mtvec,t0", "ebreak", "completed:", "j completed",
              "fail:", "sd s1,8(s0)", "li t0,0xbad", "sd t0,0(s0)", "li a0,1", "ebreak",
              ".section .rodata", ".balign 8", *data]
    output.write_text("\n".join(lines) + "\n")
    return {"cases": cases, "family_keys": [list(x) for x in sorted(families)],
            "scope": "actual CPU all numerical operation groups/rounding modes, independent edge subset; not Linux"}
