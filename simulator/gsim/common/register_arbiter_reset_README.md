# Common MSI reset-defined arbitration, native four-state check

This is a bounded, explicitly authorized Icarus exception for a cold-start
four-state handshake defect. It is not a replacement GSIM flow, full SoC test,
CDC test, timing qualification, or a new simulator baseline.

`platform.CommonRegisterArbiterResetMain` emits the actual production
`TwoMasterRegisterArbiter` with its unchanged capacity of eight and request
locking enabled. The `common` variant enables reset-defined arbitration;
`legacy` retains the old `RRArbiter`. Both use the same testbench with no variant
flag. RTL is not patched and no internal register is read, forced, or faulted.

The external-port scoreboard checks:

- A physical 0 → 1 → 0 common reset followed by client 1 alone.
- Exact input/downstream acceptance conservation, M/S target addresses,
  identity payloads, write/size/byte-enable, and real response ownership.
- A selected request held across 33 blocked cycles while a competitor arrives.
- Eight fair alternating acceptances in eight cycles, an eight-entry owner FIFO,
  24 cycles of full-queue backpressure, and no credit from a stalled response.
- Nine actual responses after filling eight owners, delayed and backpressured
  on their true owner, with independent response data/error checks.
- Common reset canceling a queued response owner and a locked unaccepted offer;
  the opposite producer and then client 1 work after reset.

The legacy run must fail directly at the first client-1 offer with
`ORACLE_UNKNOWN_REQUEST_READY client=1`, while downstream valid and ready are
both one. A timeout, emitter failure, compile error, or variant self-rejection
does not qualify as the negative control.

## Invocation

Use the already compiled classpath and the passing batch compilation receipt:

```sh
python3 simulator/gsim/common/register_arbiter_reset.py \
  --out /existing/evidence/fresh-msi-reset-run \
  --java /existing/jdk/bin/java \
  --java-classpath-file /existing/evidence/classpath.txt \
  --compile-receipt /existing/evidence/compile.json \
  --firtool /existing/firtool/bin/firtool \
  --iverilog /existing/iverilog-wrapper \
  --vvp /existing/bin/vvp
```

The runner never compiles Scala or installs tools. Each subprocess is bounded
and protected by the shared 4 GiB free-space floor; emitted RTL and total
evidence each must stay below 20 MiB. The receipt binds source, fixture, compiled
classpath, Java/firtool/Icarus/VVP tools, testbench, runner, emitted RTL,
simulation binaries, commands, exit codes and logs. Existing evidence is never
overwritten. The test is deterministic and uses no random initialization.
