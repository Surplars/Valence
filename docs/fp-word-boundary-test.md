# Same-model FP word conversion integration check

`simulator/gsim/payloads/fp_word_boundary/` contains a bounded real-CPU guest and host. It adds 20 explicit S/D W/WU boundary conversions to the existing RV64GC smoke, retaining its integer/atomic/exact FP arithmetic, Sv39 alias translation, all 32 FPR save/restore, fcsr/FS state, compressed retirement and precise S-mode ECALL checks.

Each conversion checks a literal 64-bit sign-extended result and architectural fflags. Cases cover positive/negative signed overflow, unsigned bit31 sign extension, negative fractions that round to zero or out of range, integer endpoints, rounding across a narrow endpoint, NaN/infinity and NV suppressing NX. `expected_oracle.py` independently decodes the literal IEEE bits with exact rational arithmetic; it imports no DUT or HardFloat definitions.

The exact native-board model leaves the external UART service idle. This guest therefore terminates at public retirement-PC PASS/FAIL anchors rather than sending UART MMIO. The host observes public commit PCs for each conversion and each successful result/flags check. It requires all 20 and the original S-mode/context checks. No internal DUT state is forced, and neither DDR nor fabric service behavior is changed.

## Reuse an already-built model

```
python3 simulator/gsim/payloads/fp_word_boundary/run_same_model.py \
  --model MODEL_DIR \
  --link-receipt ORIGINAL_INTEGRATION_RECEIPT_JSON \
  --service ORIGINAL_QUALIFIED_HOST_HARNESS_DIR \
  --activate PINNED_TOOLCHAIN_ACTIVATION_SH \
  --out FRESH_OUTPUT_DIR
```

The runner checks all model objects against the provided original integration receipt, uses its original C++ flags, and checks the exact original board_boot.cpp, board_ddr_benchmark.h and fabric_idle_service.h hashes. It never emits RTL or rebuilds the CPU. It assembles the guest, derives read-only public PC anchors from its ELF symbols, links a host against the retained objects, runs the positive and one expected-literal corruption negative, and verifies model hashes again. It requires the original latency32/gap1/read-credits8 service contract. No source-tree substitute for the qualified host snapshot is allowed.

The negative changes one guest expected constant, requires actual retirement of the first conversion and rejection at the independent firmware failure check. It tests the guest/host checker, not a DUT-source mutant.

Historical fixture corrections are retained in the evidence: the first marker was 17 bytes and caused a genuine misaligned load; the corrected guest now explicitly aligns the expected .quad and prechecks its ELF address. The second run reached all conversions but attempted the old UART terminal protocol, which the idle-service model correctly rejected. The final public version uses the commit-PC protocol above, without weakening any arithmetic or context comparison. The retained r6 model passes in 6,151 cycles. This is a short integration test, not exhaustive IEEE, Linux scheduling or FPGA timing qualification.
