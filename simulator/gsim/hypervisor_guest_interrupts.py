#!/usr/bin/env python3
"""Focused H guest-interrupt component and physical IMSIC-chain checks, not CPU H qualification."""
import json
from run import BUILD, setup, test


def main():
    gsim, cxx = setup(False)
    results = {}
    for size in (0, 1, 7, 63):
        output = test(gsim, cxx, f"hypervisor-guest-interrupts/geilen-{size}",
                      "ooo.HypervisorGuestInterruptsGsimMain", "HypervisorGuestInterrupts",
                      "hypervisor_guest_interrupts.cpp", parameters=(str(size),), defines={"GEILEN": size})
        results[str(size)] = (output / "test.log").read_text()
    output = test(gsim, cxx, "hypervisor-guest-interrupts/imsic-chain",
                  "ooo.HypervisorImsicGuestGsimMain", "HypervisorImsicGuestGsim",
                  "hypervisor_imsic_guest.cpp")
    results["imsic-chain"] = (output / "test.log").read_text()
    (BUILD / "hypervisor-guest-interrupts/results.json").write_text(json.dumps({
        "status": "PASS", "results": results, "core_integrated": False, "full_H_supported": False
    }, indent=2) + "\n")
    print("GSIM H guest-interrupt components: PASS (not full-core H qualification)")


if __name__ == "__main__":
    main()
