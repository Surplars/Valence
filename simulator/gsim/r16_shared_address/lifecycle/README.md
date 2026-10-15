# R16 shared-address lifecycle addendum

Source-only extension of the original R16 public recipe. Production sources and
all default settings are unchanged. This is a directed backend component test,
not CPU, ISA, full memory-order, TLB/page-walk, or physical qualification.

## Evidence and boundaries

The historical qualified runtime used the exact 244-source closure rooted at
2fa6a4b320814ad2b142d5bf0009c1d2d5475233, a 177-field profile, ROB16/PRF48/
memory4/issue2/tag64. This historical source checkout is separate from the public
recipe checkout. Current development sources must not silently replace it.
The public recipe is delivered as an increment on development commit
086ca3ac1637f2fac6e325efdf81573de7494dc2.

Four final OFF/ON paired cases passed in 454, 461, 486 and 189 cycles:
- Bound frozen store with data initially unready, exact certificate and credit use.
- Overlap exclusion, with no inappropriate binding.
- Precise fault plus killed delayed preparation; row 9 tag 9 is killed at cycle
  27, reused as tag 15 at 87, and known/prepared/canonical are clear at 88.
- Canceled load row 8 tag 8, replacement store tag 11; late reply discarded,
  replacement payload/authority preserved and no stale completion/publication.

The true frozen-VA-overwrite source negative reached the unchanged independent
row-payload oracle after the matching positive prefix of 434 cycles. The final
positive and negative used the same host, SHA-256
ac16d5cdb8a13f3a5293508515094730ae75afa5ed20744ae0b8e265d5ccedc3.
The final independent review SHA-256 is
5e4934b545165ccd74ce49fb478e35f4035243760e73aa4aad176e31ad42720c.
The catalog preserves its structured result and source/evidence identities.

The relocated public compile/build/runtime has NOT been rerun. Host-only tests
and exact source bindings do not establish a fresh runtime result. The existing
public fresh compiler is reused, with a small optional public test-source list;
the existing builder now accepts an optional emitter name. The original R16
entry point retains its defaults. No frozen private application classes are
needed or accepted by this lifecycle entry point.

Observer correction: only scalar leaves are bored. The earlier aggregate
Decoupled observer drove ready backwards and is invalid evidence. Its failure,
the initial UNREACHED delayed-capture case, and later host timing/evidence fixes
remain recorded in FAILURE_HISTORY.md. The final exact observed fixture and the
bare comparator source are included. Historical observer transparency was
independently verified; the relocated sources have not been re-elaborated.

The final 244 public outputs serialize to 276 words; 145 extra lifecycle words
are compared. Wide fields are split before narrowing. Same-seed paired traces
and exact historical trace hashes are required. Snapshots and zero-initializer
headers are checked-in source support, not newly generated DUT model artifacts.

Limits: one fixed one-page RW hit-only mapping with stable matching epoch; no
permission/epoch-negative matrix. FIFO delayed tagged service; naturally reached
full-width tokens, no fabricated high-bit tag or impossible same-edge reuse.
The accepted certificate echoes its epoch, and historical offline audit checked
accepted epoch 1 independently. No default enablement or area/timing claim.

## Portable commands

Run from the public recipe checkout containing the original R16 files plus this
increment. Set SOURCE to a separate complete checkout of the exact historical
source root above, OUT to a fresh writable output directory, and JAVA, GSIM, CXX
to installed JDK21, pinned GSIM and Clang19+ executables. The repository's
make gsim-setup supplies SETUP (the resulting toolchain-used.json).
Resolve Mill dependencies in SOURCE with:

    (cd "$SOURCE" && mill -i IonSoC.test.resolvedMvnDeps IonSoC.test.scalaCompilerClasspath IonSoC.test.scalacPluginClasspath)
    export PYTHONDONTWRITEBYTECODE=1
    python3 simulator/gsim/test_r16_shared_address.py
    python3 simulator/gsim/test_r16_lifecycle.py
    R=simulator/gsim/run_r16_lifecycle.py
    python3 "$R" verify-source --repo-root "$SOURCE"
    python3 "$R" bind-deps --repo-root "$SOURCE" --out "$OUT/deps"
    python3 "$R" compile --repo-root "$SOURCE" --deps-dir "$OUT/deps" --out "$OUT/classes" --java "$JAVA" --java-sha256 "$(sha256sum "$JAVA" | cut -d' ' -f1)"
    python3 "$R" build --repo-root "$SOURCE" --classes-dir "$OUT/classes" --out "$OUT/model" --gsim-setup-receipt "$SETUP" --java "$JAVA" --java-sha256 "$(sha256sum "$JAVA" | cut -d' ' -f1)" --gsim "$GSIM" --gsim-sha256 "$(sha256sum "$GSIM" | cut -d' ' -f1)" --cxx "$CXX" --cxx-sha256 "$(sha256sum "$CXX" | cut -d' ' -f1)"
    python3 "$R" run --repo-root "$SOURCE" --classes-dir "$OUT/classes" --build-dir "$OUT/model" --out "$OUT/runtime"

All outputs must be fresh. Compiler receipts bind the complete exact production,
HardFloat, public fixture and dependency closures; prior application classes,
duplicate fallback classes, changed profile/ABI/tool or modified build outputs
are rejected. These commands are a reproduction recipe, not a claim they ran.

For the real source negative, copy SOURCE to a separate disposable NEG_SOURCE
checkout, preserving all relative inputs; never overwrite the positive checkout.
Create the exact mutant separately, review it, and replace only the named file
in that disposable copy:

    python3 "$R" prepare-negative --repo-root "$SOURCE" --out "$OUT/IntegerBackend.scala"
    cp "$OUT/IntegerBackend.scala" "$NEG_SOURCE/src/main/scala/core/ooo/IntegerBackend.scala"

Then repeat bind-deps/compile/build/run with --negative, --repo-root
"$NEG_SOURCE", and separate fresh negative output paths. The exact mutant source
hash is enforced, the final positive host is unchanged, and only ON case 1 is
run for the negative. A sanitizer, assertion, timeout, altered oracle failure,
or wrong failure-point trace cannot qualify. The shared builder also creates an
unused OFF model for this negative; no second build infrastructure is introduced.
