# Experimental B0 source backup

Actual Home/acquisition-engine/AXI focused fixture, default-off permission-only allocation. All scoped internal/standard/OFF tests passed independent review. No production profile enablement or CPU/cache integration qualification.

This source snapshot needs the exact historical 50cb Valence main-source closure and compatible Chisel/Scala/HardFloat plus the pinned GSIM toolchain used by the local experiment. This is not a standalone or fresh-machine replay claim. The parent qualified source closure is separately retained. Driver generation requires the emitted FullLineHomeGsim.h; no generated model, executable or tool is included.

Compile isolated renamed Home and fixture against the historical production classes. Emit arguments are target-directory, enabled(0/1), internal(0/1). Generate with the compatible GSIM backend and compile fresh model objects plus driver under sanitizer checks. host/cases.py positive covers internal mode; host/arm_cases.py standard/off/disabled/supplement selects the additional qualified cases. protocol_oracle_r2.py must be importable as in the original host layout. Exact raw command/dependency/execution receipts stay in the local sealed evidence.

All source remains subject to the parent Valence project license; this directory does not change licensing. Publication is pending separate allow-list review.

## Recoverable source and exact tool prerequisites

Historical-source archive is published in Surplars/Valence commit5614cb808b5475ce893e564e3b6f25e73cfb6b02 at simulator/gsim/translated_response_empty_flow_r1/historical-qualified-source.tar.gz (581650bytes, SHA2569d9c10c2103d6b12651fa4dc155eeb0373eaa094cb8cf42a681d21c06c40754d). It contains the qualified50cb main closure plus the separately qualified Ethernet deltas; the existing acquisition engine/Home dependencies used here are bound locally. Extract as evidence sources and build fresh dependency classes; do not install the historical tree as a current production profile.

Tested tool versions: Azul JDK21.0.10 (Zulu21.48.15), Scala2.13.17, Chisel7.3.0 with matching Chisel compiler plugin, Clang19, and pinned GSIM executable SHA256f00067c6158db342927ad0d746109ad745298fd4ebe9707fd951998069587116. GSIM flags: --threads=1 --cpp-max-size-KB=512. HardFloat source/licenses and build descriptors are in the historical archive. GSIM and compiler binaries are external prerequisites and are not redistributed here. Fresh execution from this packaged snapshot has not been verified.
