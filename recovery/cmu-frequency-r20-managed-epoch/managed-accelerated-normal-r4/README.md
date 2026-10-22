# Requalified normal after cancellation test correction

Normal/unrelated r4 passed in240.339 seconds under its300-second wall-only bound, with rc0 and confirmed child reaping. The exact changed testbench includes the cancellation-only fresh-proof pause fix, prior-edge matching raw-held/idle park history oracle, and explicit owned/healthy/no-control-retirement checks while the actual AON result is unconsumed. No production or RTL/guest/MDIO/epoch timing changes.

The original r6 architectural comparison again passes, including the comparison checker negative selftests. Current packet/CSR/AXI/statistics/epoch results equal r3; timer42/42 and post-resume37/36 retain allowed phase differences from r6. Source332, RTL257 and tool/config11 inventories plus all guest/log/binary/assertion/qualification artifacts were independently rehashed. The remaining matrix is still pending and must use this changed testbench's qualified receipt.

All prior results remain unchanged, including the first cancellation TIMEOUT and the documented stimulus/oracle erratum. This is not a full matrix, production fixed-clock/gate/DRP or physical proof. Remote upload remains blocked.
