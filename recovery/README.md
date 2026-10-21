# Local recovery entry

Use the workspace `CURRENT.ps1`; it delegates to `recovery/CURRENT.ps1` here.
Default `-Mode Status` reads `CURRENT/STATUS.json` without launching tools.

`-Mode RunDiagnostic -OutputDirectory <fresh native Windows directory>` verifies
the recorded checkpoint SHA256, refuses a possibly active duplicate run, records
source/config/script hashes, and runs the formal constraint entries and diagnostic
opt/place/phys_opt/route. No synthesis, IP regeneration, bitstream or programming.
Outputs retain original logs, exit receipts and stage checkpoints. Exit zero is
diagnostic completion, not signoff.

Successful opt is saved immediately as `optimized-unqualified.dcp`, before the
post_opt proof gate. Explicit `-Stage RAW_OPT`, `POST_OPT` or `PLACED`, with `-Checkpoint` and
`-CheckpointSha256`, resumes the corresponding checkpoint without repeating earlier
physical steps. Clocks, IO bindings, formal post_opt mapping and native DRC are
checked again. Those branches have syntax checks; native execution is pending
the first matching checkpoint. RESTORED is the default.

The immutable r11 routed baseline uses RTL commit `76c7d983c08caca4610b9399b1d446fd262ab2c4`.
The IMSIC/GMAC timing candidate uses `f6f04c4f8a66b217e1c4511d3d8038a8f32b1f68`,
profile SHA256 `80e29e6eb99b7e2e65c7b802249dd262ff707cfc8420c9767ab87bb9732d268d`.
Directed generated-DUT xsim and affected Scala checks passed; see
`timing-batch-validation.json`. Its physical results are pending. This is recovery-r1,
not restored r6 or r2-equivalent. Final reset/CDC/IO and physical signoff remain
pending; historical PASS conclusions do not transfer.

`CURRENT.ps1 -Stage LINKED` also accepts a fresh `synthesized-unqualified.dcp`,
with explicit `-IpConstraintInventory` and original per-file hash validation.
`-RetainedDebugHubDcp` restores the exact revision4 vendor CDC timing contract,
guarded by IP SHA, clock periods and endpoint cardinalities; no CDC waivers.
`continue-timing-batch.ps1` waits for the one existing synthesis PID/exit receipt,
then uses this same CURRENT entry to run diagnostic opt/place/route. It never
restarts synthesis or generates a bitstream. Each completed phase is checkpointed
before subsequent checks. Restored vendor timing on the unchanged baseline is
reported separately in `vendor-hub-contract-review.json`.

OOC MIG owns its physical IO. Recovery synthesis/link/map preflight all 73 ports,
remove only the reviewed 27 output/2 input duplicate buffers, preserve vendor
buffers, and apply original vendor/board XDC. Package pins and IO standards must
match the original routed reference. No dedicated-route override or invented
pin/delay. See `mig-io-contract-evidence.json`.

Obsolete interactive scalar census/continuation scripts were removed from the
active Git tree; prior commits retain them. Local investigation scripts were
archived under `CURRENT/history/mig-investigation-20261021`. Original logs, DCPs,
vendor IP and user files remain intact.
