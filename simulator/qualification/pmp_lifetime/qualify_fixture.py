#!/usr/bin/env python3
"""Opt-in existing tiny four-state PMP exception. Never builds or runs a CPU.

Requires explicit installed tool paths and two freshly emitted test fixtures.
GSIM remains the repository hardware simulator; this is not a general backend.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

from check_observations import check_case


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def run(directory, name, command, expected=0):
    start, reason = time.monotonic(), None
    minimum = [shutil.disk_usage(directory).free, shutil.disk_usage("/tmp").free]
    assert minimum[0] > 512 * 1024**2 and minimum[1] > 1024**3, "disk safety floor"
    with (directory / f"{name}.stdout").open("x") as out, (directory / f"{name}.stderr").open("x") as err:
        process = subprocess.Popen([str(x) for x in command], stdout=out, stderr=err, start_new_session=True)
        while True:
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                break
            minimum = [min(minimum[0], shutil.disk_usage(directory).free),
                       min(minimum[1], shutil.disk_usage("/tmp").free)]
            status_path = Path(f"/proc/{process.pid}/status")
            try:
                match = re.search(r"^VmRSS:\s+(\d+)", status_path.read_text(), re.M)
                rss = int(match[1]) * 1024 if match else 0
            except FileNotFoundError:
                rss = 0
            if minimum[0] < 512 * 1024**2 or minimum[1] < 1024**3 or rss > 2 * 1024**3:
                reason = "resource safety floor or 2 GiB RSS ceiling"
            elif time.monotonic() - start > 120:
                reason = "120-second tiny-fixture stage limit"
            if reason:
                os.killpg(process.pid, signal.SIGKILL)
                _, status, usage = os.wait4(process.pid, 0)
                break
            time.sleep(0.05)
    receipt = dict(argv=list(map(str, command)), returncode=os.waitstatus_to_exitcode(status),
                   seconds=time.monotonic() - start, maxrss_kib=usage.ru_maxrss,
                   minimum_workspace_free_bytes=minimum[0], minimum_tmp_free_bytes=minimum[1], killed_reason=reason)
    write_json(directory / f"{name}.receipt.json", receipt)
    assert reason is None and receipt["returncode"] == expected, (name, receipt)


def build(args, kind, source):
    directory = args.out / kind
    directory.mkdir()
    shutil.copyfile(source, directory / "PmpLifetimeContract.fir")
    run(directory, "firtool", [args.firtool, directory / "PmpLifetimeContract.fir", "--strip-debug-info",
        "--disable-all-randomization", "--lowering-options=disallowLocalVariables",
        "--default-layer-specialization=enable", "--verification-flavor=immediate", "-o", directory / "original.sv"])
    original = (directory / "original.sv").read_text()
    # Remove only unsupported diagnostic else-$error actions, never conditions or assertions.
    pattern = re.compile(r'(assert__chisel3_builtin(?:_\d+)?:\s*assert\([\s\S]*?\))\s*else \$error\(("(?:[^"\\]|\\.)*")\);')
    adapted, removed = pattern.subn(lambda match: match[1] + ";", original)
    assert removed > 0 and "$error" not in adapted and "$fatal" not in adapted
    (directory / "adapted.sv").write_text(adapted)
    write_json(directory / "ADAPTER.json", dict(original_sha256=digest(directory / "original.sv"),
        adapted_sha256=digest(directory / "adapted.sv"), diagnostic_actions_removed=removed))
    run(directory, "sv2v", [args.sv2v, "--exclude=Assert", "--write=" + str(directory / "converted.v"), directory / "adapted.sv"])
    script = directory / "build.ys"
    script.write_text(f"read_verilog -sv -formal {directory}/converted.v\nhierarchy -check -top PmpLifetimeContract\n"
                      f"proc\nflatten\nopt_clean\nmemory_collect\nwrite_json {directory}/raw.json\n")
    run(directory, "yosys", [args.yosys, "-Q", "-T", "-s", script])
    graph = json.loads((directory / "raw.json").read_text())
    assert list(graph["modules"]) == ["PmpLifetimeContract"]
    module = graph["modules"]["PmpLifetimeContract"]
    before = copy.deepcopy(module)
    assert not any(c["type"].startswith(("$dff", "$adff", "$sdff", "$mem", "$dlatch")) for c in module["cells"].values())
    sites = []
    for name, cell in module["cells"].items():
        if cell["type"] != "$check":
            continue
        params, connections = cell["parameters"], cell["connections"]
        assert params["FLAVOR"] == "assert" and int(params["TRG_ENABLE"], 2) == 1
        assert int(params["TRG_WIDTH"], 2) == 1 and int(params["TRG_POLARITY"], 2) == 1
        assert connections["TRG"] == module["ports"]["clock"]["bits"] and connections["ARGS"] == []
        assert len(connections["A"]) == len(connections["EN"]) == 1
        index = len(sites)
        for port in ("A", "EN", "TRG"):
            observer = f"assert_{port}_{index}"
            assert observer not in module["ports"] and observer not in module["netnames"]
            module["ports"][observer] = dict(direction="output", bits=connections[port])
            module["netnames"][observer] = dict(hide_name=0, bits=connections[port], attributes={})
        sites.append(dict(id=index, name=name, connections=connections))
    assert len(sites) == (6 if kind == "natural" else 147), "unsupported assertion topology"
    assert module["cells"] == before["cells"]
    assert all(module["netnames"][n] == v for n, v in before["netnames"].items())
    assert all(module["ports"][n] == v for n, v in before["ports"].items())
    write_json(directory / "ASSERT_SITES.json", sites)
    write_json(directory / "observed.json", graph)
    script = directory / "lower.ys"
    script.write_text(f"read_json {directory}/observed.json\nclk2fflogic -nolower -nopeepopt t:$check\n"
                      f"chformal -lower\nwrite_rtlil {directory}/model.il\n")
    run(directory, "lower", [args.yosys, "-Q", "-T", "-s", script])
    write_json(directory / "MODEL_READY.json", dict(model_sha256=digest(directory / "model.il"), sites=len(sites),
        passive_observers_preserve_original_graph=True, stateless_before_selective_assertion_lowering=True))
    return directory, module, sites


def exercise(args, directory, module, sites, case):
    from ywio import WriteWitness, WitnessValues
    inputs = {name: port for name, port in module["ports"].items() if port["direction"] == "input"}
    values = {name: "0" * len(port["bits"]) for name, port in inputs.items()}
    values.update(io_privilege="01", io_size="011")
    for name, value in case["inputs"].items():
        assert name in inputs and len(value) == len(inputs[name]["bits"]) and set(value) <= set("01x")
        values[name] = value
    name = case["name"]
    witness = directory / f"{name}.yw"
    with witness.open("x") as stream:
        writer = WriteWitness(stream, "maintained-tiny-pmp-lifetime-contract")
        signals = {name: writer.add_sig(("\\" + name,), 0, len(port["bits"])) for name, port in inputs.items()}
        for t in range(9):
            step = dict(values, clock=str(t % 2), reset="1" if t < 2 or case["reset"] else "0")
            row = WitnessValues()
            for signal, bits in step.items():
                row[signals[signal]] = bits
            writer.step(row)
        writer.end_trace()
    for strict in ([False, True] if case["negative"] else [True]):
        suffix = "strict" if strict else "observe"
        script = directory / f"{name}-{suffix}.ys"
        script.write_text(f"read_rtlil {directory}/model.il\nrename -hide w:*\nsim -r {witness} "
            f"-vcd {directory}/{name}-{suffix}.vcd -timescale 1ns -q " + ("-assert " if strict else "") +
            f"-summary {directory}/{name}-{suffix}-summary.json\n")
        run(directory, name + "-" + suffix, [args.yosys, "-Q", "-T", "-s", script],
            expected=1 if strict and case["negative"] else 0)
    return dict(check_case(directory, case, sites), witness_sha256=digest(witness))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("natural-fir", "decoded-fir", "firtool", "sv2v", "yosys", "yosys-share", "out", "lock"):
        parser.add_argument("--" + option, required=True, type=Path)
    args = parser.parse_args()
    for key, value in vars(args).items():
        setattr(args, key, value.resolve())
    assert not args.out.exists(), "output directory must be new"
    assert all(not re.search(r"[\s;\"\\]", str(p)) for p in (args.out, args.natural_fir, args.decoded_fir))
    for source in (args.natural_fir, args.decoded_fir):
        assert source.stat().st_size < 2 * 1024**2, "only the tiny stateless PMP fixture is supported"
        assert "circuit PmpLifetimeContract :" in source.read_text()
    sys.path.insert(0, str(args.yosys_share))
    lock = args.lock.open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    args.out.mkdir(parents=True)
    files = [args.natural_fir, args.decoded_fir, args.firtool, args.sv2v, args.yosys,
             args.yosys_share / "ywio.py", Path(__file__).resolve(), Path(__file__).with_name("check_observations.py"),
             Path(__file__).with_name("cases.json")]
    write_json(args.out / "INPUT_PINS.json", {str(path): digest(path) for path in files})
    cases = json.loads(Path(__file__).with_name("cases.json").read_text())
    assert len(cases) == 20 and sum(c["negative"] for c in cases) == 10
    rows = []
    for kind, source in (("natural", args.natural_fir), ("decoded", args.decoded_fir)):
        directory, module, sites = build(args, kind, source)
        rows += [exercise(args, directory, module, sites, case) for case in cases if case["kind"] == kind]
    write_json(args.out / "RESULT.json", dict(status="PASS_TINY_FOUR_STATE_FIXTURE", cases=rows,
        scope="20 helper-fixture controls only. Actual production owner wiring is checked separately by PmpLifetimeSpec."))
    print("PASS: 10 positive and 10 reached original-assertion negative fixture cases")


if __name__ == "__main__":
    main()
