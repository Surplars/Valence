# Merged early-load / data-TLB parameter audit

Run from the repository root with the pinned Mill/Java dependencies configured:

```sh
for kind in gsim native; do
  for entries in 0 64; do
    JAVA_TOOL_OPTIONS='-Xmx2g -Xss2m -XX:MaxMetaspaceSize=512m -XX:ActiveProcessorCount=2' \
      mill -i IonSoC.test.runMain ooo.MergedMissCacheAuditMain \
      /absolute/fresh/output-$kind-$entries $kind $entries
  done
done
```

This is a Scala compile and CHIRRTL elaboration check only. Each invocation creates one FIR file and `results.json`; it does not invoke GSIM C++ generation, Vivado, or simulation.

- Reject nonzero capacities 32/64/128 when `translationService=false`.
- Reject unsupported capacity 16 with translation enabled or disabled.
- Elaborate the existing 100 MHz combined-timing-repair production profile through both GSIM and native constructor chains, with `earlyLoadPreparationDescriptor` omitted (default false), and `dataTlbMissCacheEntries` set to 0 or 64.
- Inspect constructed descendants, not configuration strings: every exposed early-load flag must be false (including IntegerBackend); each exposed miss-cache capacity must match the arm; actual translation services must be I8+0 and D16+0/64 with the existing D peek/reuse and three translation levels.

The two MachinePlatform guards only reject unsupported or ineffectual constructor arguments. They add no hardware and impose no new translation-level restriction. The service implementation and qualified 64-entry datapath remain unchanged. The miss cache stores only eligible Sv39 stage-1 translations; this audit does not qualify a future H-extension identity scheme.

This checks coexistence and forwarding of two default-off features, not combined feature-on behavior, CPU performance, or routed timing. Native atomic/LR-SC/AMO qualification remains open. The separate service tests cover capacities 32/64/128; prior full-CPU performance/permissions evidence applies to the independently qualified 64-entry arm, not to a newly simulated merged model.
