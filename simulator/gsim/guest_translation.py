#!/usr/bin/env python3
"""Focused nested VS/G translation component test; no whole-core H claim.

Use after merging the accompanying Scala source, emitter and C++ driver into
Valence. This entry point follows the standard Mill + pinned GSIM repository
flow. The recovery directory's run_focused.py is the separately tested direct
compiler reproduction for the restored cloud toolchain, including mutations.
"""
import argparse
import run as common


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--adapter", action="store_true", help="test the native data adapter plus nested translator")
    group.add_argument("--fetch", action="store_true", help="test the scalar fetch adapter plus nested translator")
    group.add_argument("--assembly", action="store_true", help="test C/32 instruction assembly with nested translation")
    args = parser.parse_args()
    gsim, cxx = common.setup(False)
    if args.assembly:
        output = common.test(gsim, cxx, "guest-instruction-assembler", "ooo.GuestInstructionAssemblerGsimMain",
                             "GuestInstructionAssemblerGsim", "guest_instruction_assembler.cpp", defines={})
        if "GUEST_INSTRUCTION_ASSEMBLER_PASS" not in (output / "test.log").read_text():
            raise RuntimeError("guest instruction assembler pass anchor missing")
        return
    if args.fetch:
        for parcel_bytes in (2, 4):
            output = common.test(gsim, cxx, "guest-fetch-translation-" + str(parcel_bytes),
                                 "ooo.GuestFetchTranslationGsimMain", "GuestFetchTranslationGsim",
                                 "guest_fetch_translation.cpp", parameters=(str(parcel_bytes),),
                                 defines={"PARCEL_BYTES": parcel_bytes})
            if "GUEST_FETCH_ADAPTER_PASS" not in (output / "test.log").read_text():
                raise RuntimeError("guest fetch adapter pass anchor missing")
        return
    if args.adapter:
        output = common.test(gsim, cxx, "guest-data-translation", "ooo.GuestDataTranslationGsimMain",
                             "GuestDataTranslationGsim", "guest_data_translation.cpp", defines={})
        if "GUEST_DATA_ADAPTER_PASS" not in (output / "test.log").read_text():
            raise RuntimeError("guest data adapter pass anchor missing")
        return
    output = common.test(gsim, cxx, "guest-translation", "ooo.GuestTranslationGsimMain",
                         "GuestTranslationGsim", "guest_translation.cpp", defines={})
    if "GUEST_TRANSLATION_PASS" not in (output / "test.log").read_text():
        raise RuntimeError("nested translation pass anchor missing")


if __name__ == "__main__":
    main()
