# Local recovery entry

Use the workspace `CURRENT.ps1`; it delegates to `recovery/CURRENT.ps1` here.
Default `-Mode Status` reads `CURRENT/STATUS.json` without launching tools.

`-Mode RunDiagnostic -OutputDirectory <fresh native Windows directory>` verifies
the recorded checkpoint SHA256, refuses a possibly active duplicate run, records
source/config/script hashes, and runs the formal constraint entries and diagnostic
opt/place/phys_opt/route. No synthesis, IP regeneration, bitstream or programming.
Outputs retain original logs, exit receipts and stage checkpoints. Exit zero is
diagnostic completion, not signoff.

Explicit `-Stage POST_OPT` or `-Stage PLACED`, together with `-Checkpoint` and
`-CheckpointSha256`, resumes the corresponding checkpoint without repeating earlier
physical steps. Clocks, IO bindings, formal post_opt mapping and native DRC are
checked again. Those branches have syntax checks; native execution is pending
the first matching checkpoint. RESTORED is the default.

Production RTL remains commit `76c7d983c08caca4610b9399b1d446fd262ab2c4`;
profile SHA256 `8b50a14ebc9028af5180070cf9942edb4aea4c2c1f2e09ac2e0c9fa3d47eec8f`.
Later commits contain integration, constraints and evidence. This is recovery-r1,
not restored r6 or r2-equivalent. Final reset/CDC/IO and physical signoff remain
pending; historical PASS conclusions do not transfer.

OOC MIG owns its physical IO. Recovery synthesis/link/map preflight all 73 ports,
remove only the reviewed 27 output/2 input duplicate buffers, preserve vendor
buffers, and apply original vendor/board XDC. Package pins and IO standards must
match the original routed reference. No dedicated-route override or invented
pin/delay. See `mig-io-contract-evidence.json`.

Obsolete interactive scalar census/continuation scripts were removed from the
active Git tree; prior commits retain them. Local investigation scripts were
archived under `CURRENT/history/mig-investigation-20261021`. Original logs, DCPs,
vendor IP and user files remain intact.
