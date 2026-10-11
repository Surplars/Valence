# Case 21 output-budget retry, qualified

The first case21 execution was stopped only by the historical 1.1 GiB output cap;
its incomplete output is preserved separately and is not a failed DUT oracle.
Use this exact case21-only wrapper, not the historical split runner's case21 entry,
after materializing/rebinding the source and evidence layout. It reuses the same
frozen split model, original host, guest and full oracles without recompilation.

The new cap is 1.5 GiB, admission is 2.2 GiB free, and floor remains 700 MiB.
The measured original complete output is 1,464,074,471 bytes, leaving 146,538,265
bytes under the new cap. No-slot invocation was rejected. The unchanged original
split runner remains evidence of the earlier cap; its historical source is intact.

`run.py` and `contract.json` are exact historical copies with absolute dependency
hashes. Restore these inputs in the new external retry namespace and explicitly
rebind a new contract for a new workspace. Do not edit the original receipt to
claim a new run. The current qualified namespace is
memory-state-reuse-cpu-case21-retry-20261011-r1; invoke `python3 -B run.py
--slot-granted` only with coordinator approval after all input checks and admission.
The actual fresh retry passed at 345578 kernel / 5565 flush cycles. All 18 original
raw digests, both stdout streams and the complete primary result match; the
original trap negative exited 1. Terminal receipt SHA256 is
4a136d3d09f7096f4cfa61b7853347d3165f241da9461d1514f5fad5d5a1fc5f.
This is the historical bound run, not execution from this integration checkout.
