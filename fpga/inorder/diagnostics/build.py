#!/usr/bin/env python3
"""Build board menu and short-test twin; never modify RTL, dependencies or old output."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REVISION = "1f483d5b8316753a742cbf5590caf5bd0a4e4777"
CORE = ["core_main.c", "core_list_join.c", "core_matrix.c", "core_state.c", "core_util.c"]
FLAGS = ["-O3", "-march=rv64im_zicsr_zifencei", "-mabi=lp64", "-mcmodel=medany",
         "-mno-relax", "-fno-builtin", "-ffreestanding", "-ffunction-sections", "-fdata-sections"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--coremark", type=Path, default=Path("/home/openion/Valence/simulator/build/coremark-src"))
    args = ap.parse_args()
    dep, out = args.coremark.resolve(), args.output.resolve()
    revision = subprocess.check_output(["git", "-C", str(dep), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISION or subprocess.check_output(["git", "-C", str(dep), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("clean pinned official CoreMark dependency required")
    out.mkdir(parents=True, exist_ok=False)
    gcc = "riscv64-unknown-elf-gcc"
    common = [gcc, *FLAGS, "-I"+str(HERE), "-I"+str(dep), "-DCPU_HZ=300000000UL"]
    objects = []
    commands = []
    def run(cmd):
        commands.append(list(map(str, cmd)))
        subprocess.run(cmd, check=True, cwd=ROOT)
    for source in [dep/name for name in CORE]+[HERE/name for name in ("start.S", "memory.S", "runtime.c", "core_portme.c")]:
        obj = out/(source.stem+".o")
        rename = ["-Dmain=coremark_main"] if source.name == "core_main.c" else []
        run([*common, *rename, "-c", str(source), "-o", str(obj)])
        objects.append(str(obj))
    for variant, autotest in (("i1_diag_menu_cpu300_o3", 0), ("i1_diag_smoke_cpu300_o3", 1)):
        obj = out/(variant+".o")
        run([*common, "-DDIAG_AUTOTEST="+str(autotest), "-c", str(HERE/"menu.c"), "-o", str(obj)])
        elf = out/(variant+".elf")
        run([*common, "-nostdlib", "-nostartfiles", "-Wl,--no-relax,--gc-sections",
             "-Wl,-Map="+str(out/(variant+".map")), "-T", str(HERE/"link.ld"),
             *objects, str(obj), "-lgcc", "-o", str(elf)])
        run(["riscv64-unknown-elf-objcopy", "-O", "binary", str(elf), str(out/(variant+".bin"))])
        if not 0 < (out/(variant+".bin")).stat().st_size <= 64*1024*1024:
            raise RuntimeError("current JTAG aperture exceeded")
    shutil.copy2(dep/"LICENSE.md", out/"CoreMark-LICENSE.md")
    shutil.copy2(HERE/"README.txt", out/"README.txt")
    sources = [p for p in HERE.iterdir() if p.is_file()]
    manifest = {"status": "BUILT_NOT_BOARD_TESTED", "board": "I1 batch44 CPU300/I32KiB/D32KiB/TL-C/no-MAC",
                "load_base": "0x80200000", "entry": "0x80200000", "max_download_bytes": 64*1024*1024,
                "clock_hz": 300000000, "uart_baud": 460800, "dma_present": False,
                "axi_utilization_counters_present": False, "flags": FLAGS, "commands": commands,
                "compiler": subprocess.check_output([gcc, "--version"], text=True).splitlines()[0],
                "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "coremark_revision": revision, "coremark_source_sha256": {p.name: sha(p) for p in [dep/n for n in CORE+["coremark.h", "LICENSE.md"]]},
                "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in sources},
                "files_sha256": {p.name: sha(p) for p in out.iterdir() if p.is_file()}}
    (out/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps({"output": str(out), "images": {p.name:p.stat().st_size for p in out.glob("*.bin")}}, indent=2))


if __name__ == "__main__":
    main()
