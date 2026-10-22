# Narrow correction to r16 negative-control evidence

The original native-final/receipt.json remains immutable (SHA256 f3c5f22209ce190c4d9d2a2deeca78b58680e22b2857548dc1a80f66baefa91e). Its negative-2 directly ORed the fault selector into the status-owner failure predicate. That invocation proved the fatal path worked, not the ordinary drain checker sensitivity. This specific negative-control claim was insufficient. The16 real positive runs and expected-data mutations in negatives1/3 are not invalidated.

The corrected test mutates only observed_rx_drained, then uses the same ordinary retained-status checker for positive and negative runs. No production source, emitted RTL, test stimulus, runner or budget changes. Recompiled the corrected TB against the identical22-file RTL inventory and reran16 positives plus3 negatives, all expected outcomes confirmed. All positive event ledgers remained identical. Corrected negative2 is rejected by PACKET_ORACLE_DRAIN; no negative-only fatal branch remains.

The integration owner independently rehashed319 source files,24 inputs, all7 tools, compiled VVP and all case logs. Corrected receipt SHA256647affbe451a716f347515dff5cbcf785fadbb9523d5a58b07f30c11b7c85b19. Scope remains component packets and modeled memory/terminal endpoints, not Home/AON integration or physical signoff. No upload attempted.
