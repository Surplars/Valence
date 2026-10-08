#!/usr/bin/env python3
"""One opt-in banked-TX A/B batch: saturated wire timing, real DMA overlap, abort ownership."""
import argparse
import hashlib
import json
import os
import re
import subprocess
from run import BUILD, HERE, ROOT, run, setup, test
from tri_speed_gmac import inputs as media_inputs


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def inputs():
    result = media_inputs()
    names = ("tri_speed_tx_buffers.py", "harness/trispeed_tx_bandwidth.cpp", "harness/trispeed_tx_bank_owners.cpp",
             "harness/gmac_dma_tx_bandwidth.cpp", "harness/self_gmac_dma.cpp", "harness/self_gmac_frames.cpp")
    result.update({str((HERE / n).relative_to(ROOT)): digest(HERE / n) for n in names})
    for p in (ROOT / "fpga/zu15eg").glob("*trispeed*"):
        if p.is_file(): result[str(p.relative_to(ROOT))] = digest(p)
    return result


def negative(binary, marker, path):
    r = subprocess.run([str(binary), "--inject-mismatch"], capture_output=True, text=True, timeout=240,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    path.write_text(r.stdout + r.stderr)
    if r.returncode != 1 or marker not in r.stdout + r.stderr:
        raise RuntimeError("independent mismatch injection did not fail: " + str(binary))


def variant(cxx, model, top, harness, name, marker, defines=None):
    binary = model / name
    run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
         *[f"-D{k}={v}" for k, v in (defines or {}).items()], "-I" + str(model),
         *sorted(model.glob(top + "[0-9]*.cpp")), HERE / "harness" / harness, "-ldl", "-o", binary],
        log=model / (name + "-compile.log"))
    run([binary], log=model / (name + ".log"), timeout=240,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    print((model / (name + ".log")).read_text(), end="", flush=True)
    negative(binary, marker, model / (name + "-negative.log"))
    return {"executable_sha256": digest(binary), "summary": (model / (name + ".log")).read_text().strip(),
            "negative_oracle": "passed"}


def metrics(text, marker):
    return [{key: int(value) for key, value in re.findall(r"([a-z_]+)=(\d+)", line)}
            for line in text.splitlines() if line.startswith(marker + " ")]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tag", required=True)
    a = p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.tag): p.error("unsafe tag")
    name = "tri-speed-tx-buffers-" + a.tag
    out = BUILD / name
    out.mkdir(parents=True, exist_ok=False)
    before = inputs()
    report = {"status": "running", "source_sha256": before, "profiles": {},
              "scope": "native32 continuous producer and actual packetDMA, single clock; no CPU/DDR physical timing",
              "native_clock_verified": False, "synthesis_verified": False, "routed_timing_verified": False,
              "on_board_verified": False, "bit_generated": False}
    try:
        s, c = setup(False)
        for slots in (1, 2):
            row = {}
            model = test(s, c, name + f"/wire-{slots}", "ip.TriSpeedFramesGsimMain", "TriSpeedFramesGsim",
                "trispeed_tx_bandwidth.cpp", parameters=(4, slots), defines={"TX_FRAME_SLOTS": slots}, timeout=240)
            negative(model / "run", "tri-speed TX independent wire oracle mismatch", model / "negative.log")
            row["wire"] = {"fir_sha256": digest(model / "TriSpeedFramesGsim.fir"),
                "executable_sha256": digest(model / "run"), "negative_oracle": "passed",
                "measurements": metrics((model / "test.log").read_text(), "TX_BANDWIDTH")}
            if slots == 2:
                row["frames"] = variant(c, model, "TriSpeedFramesGsim", "trispeed_gmac_frames.cpp", "frames",
                    "tri-speed TX independent wire oracle mismatch")
                row["owners"] = variant(c, model, "TriSpeedFramesGsim", "trispeed_tx_bank_owners.cpp", "owners",
                    "tri-speed TX independent wire oracle mismatch")
            dma = test(s, c, name + f"/dma-{slots}", "ip.SelfGmacDmaGsimMain", "SelfGmacDmaGsim",
                "gmac_dma_tx_bandwidth.cpp", parameters=(4, slots), defines={"MAC_TX_FRAME_SLOTS": slots}, timeout=240)
            negative(dma / "run", "DMA bandwidth independent wire oracle mismatch", dma / "negative.log")
            row["dma"] = {"fir_sha256": digest(dma / "SelfGmacDmaGsim.fir"),
                "executable_sha256": digest(dma / "run"), "negative_oracle": "passed",
                "measurements": metrics((dma / "test.log").read_text(), "GMAC_DMA_TX_BANDWIDTH")}
            row["dma_functional"] = variant(c, dma, "SelfGmacDmaGsim", "self_gmac_dma.cpp", "functional",
                "GMAC DMA independent TX wire oracle mismatch", {"TX_POSTED_SLOTS": 4})
            report["profiles"][str(slots)] = row
        report["comparisons"] = []
        for kind, fields, key in (("wire", ("mbps", "body"), "steady_interval_sum"),
                                  ("dma", ("body",), "interval_sum")):
            baseline = {tuple(x[f] for f in fields): x for x in report["profiles"]["1"][kind]["measurements"]}
            candidate = {tuple(x[f] for f in fields): x for x in report["profiles"]["2"][kind]["measurements"]}
            if baseline.keys() != candidate.keys(): raise RuntimeError("A/B measurement set mismatch")
            for dimensions, old in baseline.items():
                new = candidate[dimensions]
                if new[key] > old[key]: raise RuntimeError("banked TX regressed saturated initiation interval")
                if (kind == "wire" and old["mbps"] == 1000) or kind == "dma":
                    if new[key] >= old[key]: raise RuntimeError("banked TX showed no measured bandwidth gain")
                report["comparisons"].append({"kind": kind, **dict(zip(fields, dimensions)),
                    "baseline_interval_sum": old[key], "candidate_interval_sum": new[key],
                    "cycle_reduction_percent": 100 * (old[key] - new[key]) / old[key],
                    "throughput_gain_percent": 100 * (old[key] / new[key] - 1)})
        for slots in (1, 2):
            target = out / f"rtl-{slots}"
            run(["mill", "-i", "IonSoC.test.runMain", "ip.TriSpeedManagedGmacRtlMain", target, "hardware", slots],
                log=out / f"export-{slots}.log")
            report["profiles"][str(slots)]["rtl_sha256"] = {str(p.relative_to(target)): digest(p)
                for p in sorted(target.glob("*.sv"))}
        old = BUILD / "tri-speed-gmac-rx-fixed-r1/rtl/GmiiFrameTx.sv"
        current = out / "rtl-1/GmiiFrameTx.sv"
        report["default_transmitter_rtl_byte_identical_to_tri_speed_freeze"] = old.read_bytes() == current.read_bytes()
        report["status"] = "passed_focused_tx_buffers_only"
    except BaseException as error:
        report.update(status="failed", failure=str(error))
        raise
    finally:
        if inputs() != before: report.update(status="failed", failure="source/test input drift")
        (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "passed_focused_tx_buffers_only": raise RuntimeError(report["failure"])
    print("TRI_SPEED_TX_BUFFERS_PASS receipt=" + str(out / "receipt.json"), flush=True)


if __name__ == "__main__": main()
