#!/usr/bin/env python3
"""Short real-CPU coherent RAM boot handoff; synchronous DMI, synthetic ROM, no TCK/CDC or C CRC claim."""
import hashlib
import json
import os
import subprocess
import run as common


def main():
    output = common.BUILD / "jtag-boot"
    output.mkdir(parents=True, exist_ok=True)
    sources = [common.ROOT / "src/test/scala/debug/JtagBootGsimMain.scala",
               common.HERE / "harness/jtag_boot.cpp", common.HERE / "jtag_boot.py",
               *sorted((common.HERE / "payloads").glob("jtag_boot_*")),
               *sorted((common.ROOT / "src/main/scala").rglob("*.scala"))]
    hashes = lambda: {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    before = hashes()
    for name in ("rom", "app"):
        stem = output / name
        source = common.HERE / f"payloads/jtag_boot_{name}"
        common.run(["riscv64-unknown-elf-gcc", "-march=rv64i_zifencei", "-mabi=lp64",
                    "-nostdlib", "-nostartfiles", "-mno-relax", "-Wl,--no-relax", "-T",
                    source.with_suffix(".ld"), source.with_suffix(".S"), "-o", stem.with_suffix(".elf")],
                   log=output / f"{name}-build.log")
        common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", stem.with_suffix(".elf"),
                    stem.with_suffix(".bin")])
    gsim, cxx = common.setup(False)
    target = common.test(gsim, cxx, "jtag-boot", "debug.JtagBootGsimMain", "JtagBootGsim", "jtag_boot.cpp",
                         runtime_args=(output / "rom.bin", output / "app.bin"), timeout=120)
    assert "JTAG_BOOT_PASS" in (target / "test.log").read_text()
    negative_results = {}
    for name in ("omit-fence", "corrupt-download"):
        result = subprocess.run([target / "run", output / "rom.bin", output / "app.bin", "--" + name],
                                capture_output=True, text=True, timeout=120,
                                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        log = result.stdout + result.stderr
        (target / f"negative-{name}.log").write_text(log)
        assert result.returncode != 0 and "downloaded RAM instruction oracle mismatch" in log, log
        negative_results[name] = "DETECTED"
    assert before == hashes(), "source changed while testing"
    (output / "receipt.json").write_text(json.dumps({
        "status": "PASS", "scope": "real two-issue CPU, staged coherent DMA, synchronous DMI, synthetic assembly ROM",
        "ram_bytes": 1048576, "ram_base": "0x80020000", "download_end": "0x8009c000",
        "dcache_lines": 8, "icache_lines": 4, "negative_cases": negative_results,
        "production_ram_base": "0x80200000",
        "topology_reductions": "test RAM base 0x80020000 and 8/4-line caches; not selected-board geometry",
        "production_bootrom_crc": "NOT_RUN", "nemu": "NOT_RUN", "tck_cdc": "NOT_RUN",
        "openocd": "NOT_RUN", "selected_board_geometry": "NOT_RUN", "board": "NOT_RUN",
        "source_sha256": before}, indent=2) + "\n")
    print("JTAG_BOOT_NEGATIVES_PASS omit_fence=detected corrupted_instruction=detected")


if __name__ == "__main__":
    main()
