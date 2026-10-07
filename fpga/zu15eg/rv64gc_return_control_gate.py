"""Strict r3 evidence intake. These gates are not hardware or timing tests."""
from pathlib import Path
import hashlib
import json


PURE_SPECS = frozenset(("src/test/scala/ooo/FetchFeedbackTimingSpec.scala",
                        "src/test/scala/ooo/FrontendFeedbackTimingSpec.scala"))
LINE_WRITER = "src/main/scala/ip/tilelink/TileLinkLineWriteEngine.scala"
CHECKS = {
    "arithmetic": ("TIMING_ARITHMETIC_PASS vectors=10900", "timing arithmetic independent oracle mismatch", 1),
    "pmp-packet-2": ("GSIM PMP checker: PASS", "PMP oracle mismatch", 1),
    "pmp-packet-4": ("GSIM PMP checker: PASS", "PMP oracle mismatch", 1),
    "pmp-prefix": ("GSIM PMP checker: PASS", "PMP oracle mismatch", 1),
    "bridge-generic": ("GSIM TileLink bridge: PASS", "TileLink bridge response data, error or order mismatch", -6),
    "bridge-mixed-flow": ("GSIM TileLink bridge: PASS", "TileLink bridge response data, error or order mismatch", -6),
    "fp-numerical-fd": ("FP_FULL_PASS profile=fd", "FP full mismatch", 1),
    "fp-numerical-f": ("FP_FULL_PASS profile=f", "FP full mismatch", 1),
    "fp-numerical-small": ("FP_FULL_PASS profile=small", "FP full mismatch", 1),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def relative_path(name):
    p = Path(name)
    assert not p.is_absolute() and ".." not in p.parts and ":" not in name, "Unsafe evidence path"
    return p


def absolute_model_path(repo, name):
    prefix = "/home/openion/Valence/"
    # r2 records absolute WSL paths; r3 seals repo-relative artifact paths.
    # Both must resolve inside build/gsim, never another repo or host path.
    p = relative_path(name[len(prefix):] if name.startswith(prefix) else name)
    assert p.parts[:2] == ("build", "gsim"), "Model evidence outside GSIM artifacts"
    return repo / p


def gate_map(root, mapping):
    assert mapping, "Missing source/artifact map"
    for name, digest in mapping.items():
        assert sha(root / relative_path(name)) == digest, "Evidence drift: " + name


def gate_models(repo, mapping):
    assert mapping, "Missing actual model artifacts"
    assert any(Path(name).name == "run" for name in mapping), "Missing executed model"
    assert any(Path(name).suffix == ".fir" for name in mapping), "Missing elaborated model"
    for name, digest in mapping.items():
        assert sha(absolute_model_path(repo, name)) == digest, "Model drift: " + name


def gate_contract_update(repo, functional_path, native_path, supplement_path, export):
    """Allow exactly two archived pure contracts, with byte-identical RTL.

    All other original functional sources, CPU proof inputs and artifacts
    must still match. No general test-source exclusion is permitted.
    """
    proof = load(functional_path)
    native = load(native_path)
    supplement = load(supplement_path)
    manifest = load(export / "receipt.json")
    assert supplement["status"] == "PASS_PURE_SCALA_CONTRACT_UPDATE_UNCHANGED_BOARD_RTL"
    assert supplement["command"] == ["mill", "-i", "IonSoC.test"] and supplement["command_exit"] == 0
    assert supplement["functional_receipt_sha256"] == sha(functional_path)
    assert supplement["native_receipt_sha256"] == sha(native_path)
    assert manifest["status"] == "EXPORTED_FUNCTIONALLY_CHECKED_NOT_ROUTED"
    assert manifest["functional_receipt_sha256"] == sha(functional_path)
    assert manifest["source_contract_update_receipt_sha256"] == sha(supplement_path)
    changes = supplement["changed_pure_specs"]
    assert set(changes) == PURE_SPECS, "Only two named pure contracts may be superseded"
    assert not PURE_SPECS.intersection(native["source_sha256"]), "Pure-contract exception cannot change CPU proof"
    for name, change in changes.items():
        assert proof["source_sha256"][name] == change["before_sha256"]
        assert sha(repo / relative_path(change["archived_before"])) == change["before_sha256"]
        assert sha(repo / relative_path(name)) == change["after_sha256"]
    gate_map(repo, {n: d for n, d in proof["source_sha256"].items() if n not in PURE_SPECS})
    gate_map(repo, native["source_sha256"])
    gate_map(repo, native["cpu_artifact_sha256"])
    assert sha(supplement_path.parent / "testForked.log") == supplement["previous_failed_log_sha256"]
    log = supplement_path.parent / "updated-testForked.log"
    assert sha(log) == supplement["updated_log_sha256"]
    assert "45/45 completed." in log.read_text(), "Pure Scala checks did not finish"
    rtl = {}
    for name, digest in manifest["rtl_sha256_shards"].items():
        shard = export / relative_path(name)
        assert sha(shard) == digest, "RTL shard drift"
        entries = load(shard)
        assert not set(rtl).intersection(entries), "Duplicate RTL entries"
        rtl.update(entries)
    actual = {str(p.relative_to(export)).replace("\\", "/") for p in (export / "rtl").rglob("*.sv")}
    assert set(rtl) == actual, "Unsealed, missing or extra RTL files"
    assert len(rtl) == manifest["rtl_file_count"] == supplement["rtl_files_compared"] == 236
    gate_map(export, rtl)
    reexport = supplement_path.parent.parent / "export-after-contract"
    reexport_files = {str(p.relative_to(reexport)).replace("\\", "/") for p in (reexport / "rtl").rglob("*.sv")}
    assert reexport_files == set(rtl), "Incomplete contract re-export"
    gate_map(reexport, rtl)
    gate_map(export, manifest["firmware_sha256"])
    return sha(supplement_path)


def gate_return_control_batch(repo, path, native_path, supplement_path, export):
    proof = load(path)
    assert proof["status"] == "PASS_SOC_RETURN_CONTROL_AFFECTED_SHORT"
    assert (proof["isa"], proof["issue_width"], proof["cpu_hz"], proof["uart_baud"]) == (
        "rv64gc", 2, 100000000, 460800)
    assert proof["native_receipt_sha256"] == sha(native_path), "Fresh CPU proof mismatch"
    gate_contract_update(repo, path, native_path, supplement_path, export)
    for name, (prefix, diagnostic, exit_code) in CHECKS.items():
        assert proof["checks"][name].startswith(prefix), "Missing affected boundary: " + name
        assert (path.parent / name / "test.log").read_text().strip() == proof["checks"][name]
        assert proof["checks"][name + "-negative"] == diagnostic
        assert proof["negative_exit"][name] == exit_code
        negative = (path.parent / name / "negative.log").read_text()
        assert diagnostic in negative, "Wrong negative failure"
        if exit_code == -6: assert "std::runtime_error" in negative, "Arbitrary abort cannot qualify negative"
        gate_models(repo, proof["model_sha256"][name])
    for name in ("pmp-packet-2", "pmp-packet-4", "pmp-prefix"):
        assert "execute4=36960" in proof["checks"][name]
    assert "mixedInFlight=1" in proof["checks"]["bridge-mixed-flow"]
    assert "peakOutstanding=8" in proof["checks"]["bridge-mixed-flow"]
    assert "peakWrites=4" in proof["checks"]["bridge-mixed-flow"]
    assert "flowedResponses=20" in proof["checks"]["bridge-mixed-flow"]
    assert "GSIM short two-issue throughput + NEMU: PASS programs=13" in proof["checks"]["integer-core"]
    assert len(proof["integer_measurements"]) == 13
    # The original r3 record sealed all isolated models and the actual
    # RV64GC CPU, but did not seal this bare-core executable. Import its
    # immutable recorded metrics/log text, NOT its binary as reusable proof.
    # Current executing CPU identity is the separately hash-gated native
    # receipt above. Do not manufacture a retrospective executable digest.
    assert (path.parent / "integer-core/test.log").read_text().strip() == proof["checks"]["integer-core"]
    if "integer-core" in proof["model_sha256"]:
        gate_models(repo, proof["model_sha256"]["integer-core"])
    assert "NEMU register mismatch" in (path.parent / "integer-core/negative.log").read_text()
    for name, prefix in (("timing-smoke", "GSIM control/memory timing + NEMU: PASS"),
                         ("pipeline-recovery", "GSIM pipeline recovery + NEMU: PASS")):
        assert proof["checks"][name].startswith(prefix)
        assert (path.parent / "integer-core" / (name + ".log")).read_text().strip() == proof["checks"][name]
    comparison_path = absolute_model_path(repo, proof["coremark_receipt"])
    assert sha(comparison_path) == proof["coremark_receipt_sha256"]
    comparison = load(comparison_path)
    assert comparison["status"] == "PASS_SAME_BINARY_BOARD_COREMARK_COMPARE"
    gate_map(repo, comparison["source_sha256"])
    current = comparison["model_receipts"]["current"]
    assert current["scope"] == "current"
    assert sha(absolute_model_path(repo, current["path"])) == current["sha256"]
    assert current["sha256"] == load(native_path)["board_receipt_sha256"]
    return sha(path)


def gate_unchanged_writer(repo, path):
    """Reuse only isolated writer proof; no old CPU/fetch/FPU pass is imported."""
    proof = load(path)
    assert proof["status"] == "PASS_SOC_WINDOW_BATCH_AFFECTED_SHORT"
    required = {LINE_WRITER, "src/test/scala/ooo/TileLinkLineWriteGsim.scala",
                "simulator/gsim/harness/line_write.cpp", "build.mill", "simulator/gsim/run.py"}
    dependencies = {n: d for n, d in proof["source_sha256"].items()
                    if n.startswith(("src/main/scala/ip/", "src/main/scala/bus/")) or n in required}
    assert required <= dependencies.keys(), "Incomplete isolated writer dependency closure"
    gate_map(repo, dependencies)
    check = proof["checks"]["line-writer"]
    assert check.startswith("GSIM TileLink line write: PASS") and "II1 adjacentFinalAck" in check
    assert (path.parent / "line-writer/test.log").read_text().strip() == check
    assert "line write oracle mismatch" in (path.parent / "line-writer/negative.log").read_text()
    gate_models(repo, proof["model_sha256"]["line-writer"])
    return {LINE_WRITER: dependencies[LINE_WRITER]}
