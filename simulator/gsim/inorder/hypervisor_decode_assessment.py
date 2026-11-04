#!/usr/bin/env python3
"""Independent H1.0 encoding/privilege GSIM gate; no CPU or physical qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build"):
        parser.error("fresh output within clone build/ required")
    output.mkdir(parents=True)
    gsim, cxx = common.setup(False)
    paths = [Path(v.split(":", 3)[3]) for v in
             json.loads((ROOT / "out/OrbitalI1/test/runClasspath.json").read_text())["value"]]
    runtime = os.pathsep.join(str(p) for p in paths if p.exists())
    sources = [ROOT / "src/main/scala/core/inorder/I1HypervisorDecode.scala",
               ROOT / "src/test/scala/inorder/I1HypervisorDecodeMain.scala",
               ROOT / "simulator/gsim/harness/i1_hypervisor_decode.cpp",
               ROOT / "simulator/gsim/config/hypervisor-h10-decode.json", Path(__file__).resolve()]
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    receipt = {"status": "RUNNING", "source_sha256": frozen, "gsim_sha256": sha(gsim),
               "scope": __doc__, "cpu_h_extension_qualified": False, "commands": [], "cases": {}}

    def run(argv, folder, log, negative=None):
        argv = list(map(str, argv))
        receipt["commands"].append({"argv": argv, "log": str(folder / log)})
        with (folder / log).open("w") as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        text = (folder / log).read_text()
        if negative:
            if result.returncode == 0 or negative not in text:
                raise RuntimeError("negative oracle injection was not rejected: " + str(folder / log))
        elif result.returncode:
            raise RuntimeError("command failed: " + str(folder / log))
        return text

    try:
        for width in [32, 64]:
            folder = output / str(width)
            folder.mkdir()
            run(["java", "-cp", runtime, "inorder.I1HypervisorDecodeMain", folder, width], folder, "elaborate.log")
            fir = folder / "I1HypervisorDecode.fir"
            run([gsim, "--threads=1", "--dir=" + str(folder), fir], folder, "generate.log")
            run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all", f"-DDUT_XLEN={width}", "-I" + str(folder),
                 *sorted(folder.glob("I1HypervisorDecode[0-9]*.cpp")),
                 ROOT / "simulator/gsim/harness/i1_hypervisor_decode.cpp", "-o", folder / "run"],
                folder, "compile.log")
            summary = run([folder / "run"], folder, "positive.log")
            run([folder / "run", "--wrong-trap-cause"], folder, "negative.log",
                "independent H encoding/permission oracle mismatch")
            receipt["cases"][str(width)] = {"summary": summary.strip(), "negative_rejected": True,
                "artifact_sha256": {p.name: sha(p) for p in folder.iterdir() if p.is_file()}}
            print(summary.strip(), flush=True)
        for name, digest in frozen.items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("source drift: " + name)
        receipt["status"] = "PASS_H10_32_64_ENCODING_PERMISSION_VIRTUAL_ILLEGAL_ORACLES"
    except BaseException as error:
        receipt.update(status="FAIL", error=repr(error))
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
