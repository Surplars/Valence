# Opt-in qualified reset-graph bundle

The normal `gsim_initialization_setup` path continues to require the minimal
initialization-byte-span epoch. Its existing receipt verification and bootstrap
policy are unchanged. The cloud `cloud-tools-20261030-r2` source includes the
additional reset-graph patch and is intentionally not accepted as that minimal
epoch. Do not synthesize an old receipt or Git checkout to make it appear so.

## Explicit bounded profile

`VALENCE_GSIM_RESET_GRAPH_BUNDLE` selects an existing bundle directory. Only the
pinned `cloud-tools-20261030-r2-reset-graph-v1` profile is supported. The verifier
is read-only and performs no installation, build, generation or simulation.
After authentication, setup still invokes the ordinary compiler version check
and requires its selected command to equal the authenticated compiler command. A
missing or changed selected bundle fails, even for `make gsim-setup`. It never
falls back to a canonical initialization receipt or a rebuild. Setting both
`VALENCE_GSIM_INIT_RECEIPT` and the bundle selector is an error, including an empty
initialization-receipt variable. An empty bundle selector is also an error.

Example, with an absolute path to the existing bundle:

```sh
source /path/to/cloud-tools-20261030-r2/env.sh
unset VALENCE_GSIM_INIT_RECEIPT
export VALENCE_GSIM_RESET_GRAPH_BUNDLE=/path/to/cloud-tools-20261030-r2
make gsim-hypervisor-platform-test
```

The entry still uses the ordinary single-clock platform emitter, model,
independent drivers and sanitizer configuration. This addendum changes only
which explicitly qualified tool profile the common setup accepts; it does not
change hardware or the test oracles. Historical callers that explicitly invoke
`gsim_initialization_epoch.tool_binding(receipt)` still require that epoch and
are not silently redirected by the new selector.

## What is authenticated

- SHA-256 of the historical toolchain receipt, qualification receipt and source
  manifest is fixed in code, rather than trusting their status strings.
- The manifest binds upstream revision
  `93b8cd23edd3228807c4f2a08c19c3936a463cb2`, the ordered initialization-byte-span
  then reset-graph patches, and both patch files' bytes.
- All 101 source files and 13 qualification fixtures (including model-storage
  support) are rehashed. Extra and omitted source files are rejected. Build
  products and `.git` metadata are excluded from the source inventory.
- The exact existing GSIM, compiler, Mill launcher, firtool and environment script
  match the pinned historical receipt. The qualification receipt's executable
  and source hashes match those same inputs. The Mill wrapper and system Java
  launcher have separately fixed hashes in this profile.
- Active compiler, Mill and Java paths must resolve to the verified tools.
  `CHISEL_FIRTOOL_PATH` must select the pinned directory. Conflicting explicit
  GSIM, source, firtool, firtool-directory or Java-home selections fail.

Receipt bytes retain their original historical paths. The known bundle prefix
is remapped to the explicitly selected directory; source fixtures are checked
against the current repository. No receipt or source checkout is rewritten.
This supports relocation of this same byte-identical bundle, not arbitrary
rebuilds or arbitrary self-authored PASS receipts. Java remains the fixed system
launcher at `/usr/lib/jvm/java-21-openjdk-amd64/bin/java`; a different host or
launcher requires a separately reviewed profile. The checks do not prove a
complete dynamic-library/JDK/cache dependency closure or protect against
concurrent file mutation after verification.

## Evidence and scope

The pinned qualification contains five native positives, one observer-negative
control and two generator rejections under ASan/UBSan for generated models and
hosts. The generator itself was not sanitizer-built. Authentication preserves
that existing bounded evidence; it neither reruns it nor makes a new hardware
PASS claim. Arbitrary chained UInt reset, independent clocks and RANDOMIZE_INIT
remain unqualified. Mapping/synthesis tools in the bundle are not inspected or
executed by this profile.

The focused tests perform real binding against the selected bundle and
repository, then use copied files and executable symlinks for tampering and
omission checks. The tests mock the setup compiler-version query, so they do not execute a
compiler, generator, model or installer:

```sh
source /path/to/cloud-tools-20261030-r2/env.sh
export VALENCE_RESET_GRAPH_TEST_BUNDLE=/path/to/cloud-tools-20261030-r2
export VALENCE_RESET_GRAPH_TEST_REPO="$PWD"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=simulator/gsim python3 -m unittest -v \
  test_gsim_initialization_setup test_gsim_initialization_binding \
  test_gsim_reset_graph_bundle
```

Without the two test path variables, real-profile cases are explicitly skipped;
the selection-only cases still run. A hardware result must come from the real
entry separately and must retain its output, negative-control reason and tool
binding. These unit/binding tests are not an E2E substitute.
