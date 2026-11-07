#!/usr/bin/env python3
"""Focused actual-MSU, Bare OoO and nested-translation OoO qualification.

Uses the repository's ordinary Scala/GSIM pipeline after applying the source
patch. No Verilator/ChiselSim fallback. This does not advertise misa.H or qualify
production W16 timing. The cloud-specific replay scripts pin the executed tools.
"""
import json
from run import BUILD, setup, test


def main():
    gsim, cxx = setup(False)
    results = {}
    for name, top, harness, label in (
        ("system", "HypervisorSystemGsim", "hypervisor_system.cpp", "H_SYSTEM_BARE_PASS"),
        ("bare-ooo", "HypervisorCoreGsim", "hypervisor_core.cpp", "H_OOO_BARE_PASS"),
        ("nested-ooo", "HypervisorTranslatedCoreGsim", "hypervisor_translated.cpp", "H_OOO_TRANSLATED_PASS"),
        ("fence-coherence", "HypervisorTranslatedCoreGsim", "hypervisor_fence_coherence.cpp", "H_OOO_FENCE_COHERENCE_PASS"),
    ):
        output = test(gsim, cxx, f"hypervisor-core/{name}", f"ooo.{top}Main", top, harness)
        log = (output / "test.log").read_text()
        assert label in log, (name, log)
        results[name] = log
    (BUILD / "hypervisor-core/results.json").write_text(json.dumps({
        "status": "PASS", "results": results,
        "configuration": "explicit experimental H, precise owners, no production profile change",
        "misa_H_advertised": False,
    }, indent=2) + "\n")
    print("GSIM experimental H actual-core focused qualification: PASS")


if __name__ == "__main__":
    main()
