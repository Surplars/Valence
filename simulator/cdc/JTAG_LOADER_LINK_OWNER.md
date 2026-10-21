# Composed loader owner / DMI link reset test

This is a test-only assembly of the production DebugDmiClockBoundary and
JtagRamLoader. Its loader reset comes only from commonColdReset, never linkUp.
The test does not modify production RTL or existing timer/debug fixtures.

```
source scripts/cloud/env.sh
export JAVA_TOOL_OPTIONS="$JAVA_TOOL_OPTIONS -Dchisel.project.root=$PWD"
mill -i IonSoC.test.runMain debug.JtagLoaderLinkOwnerNativeMain build/native-loader-owner/loader-owner
python3 -m unittest discover -s simulator/cdc -p test_xsim_invocation.py -v
python3 simulator/cdc/run_jtag_loader_link_owner_xsim.py --rtl-root build/native-loader-owner --output build/native-loader-owner/results --run --tool-dir /path/to/Vivado/bin
```

Without --run the runner only hashes sources and writes PREPARED_NOT_RUN.
Windows selects the installed .bat/.cmd/.exe rather than the colocated Unix
launcher; batch tokens are explicitly quoted so NAME=VALUE parameters survive
cmd parsing. Manifest runner_sources binds the runner and invocation helper.
The five Python invocation tests do not establish actual Windows execution.

Source is 250 MHz, fabric is 100 MHz, 50 MHz, and an independent noninteger ratio.
Four cancelled RAM writes cover:

- Request offered against RAM ready backpressure, link loss, later acceptance.
- Accepted RAM request, link loss, reconnect before response.
- Accepted RAM request, response while link remains down.
- Accepted RAM request, reconnect, error response.

Every case stalls the host DMI response, checks RAM address/data/size/strobes
remain stable, retains exactly one accepted owner while the response is delayed,
rejects CPU re-arm before drain, and checks busy clears only after RAM response.
The oracle counts exactly five RAM accepts and five completions, including a
fifth normal rearmed operation whose RAM completion occurs while its DMI
response remains backpressured. A fresh identity read after each cancelled
operation distinguishes the new DMI epoch from old replies. Final quiescence
checks reject owner leakage or duplicate replay.

Export/preparation and argument-construction tests are not independent-clock
simulation acceptance. Native XSIM, physical CDC/reset review, routed timing,
and board boot remain distinct gates. No GSIM or Verilator substitutes are used.
