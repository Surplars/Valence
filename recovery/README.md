# recovery-r1

This branch starts from persisted common-platform commit `a49a28b1296d216770573f4b08585a24e1d2dfbe`.
It is a new recovery candidate, not the unavailable overnight r6.

The retained r2 ZIP and its 232 generated production modules have verified hashes.
Its baseline-source manifest differs from the available source in seven production
files and fifteen test/harness files. The six complete source files and patches in
that ZIP do not supply all missing predecessor changes. This branch therefore keeps
the exact persisted source as its initial reproducible baseline. It does not claim
to reproduce the r2 SV or inherit its test results.

The first repair targets the source-domain idle announcement feeding the existing
two-stage synchronizers. Existing local transport-empty outputs and protocol
handshakes remain unchanged. First-cycle outbound offers must cancel the registered
announcement on the same source edge. Both directions require focused verification.

Formal board constraints remain mandatory: media/RGMII, BSCAN, management, and CPU/
fabric CDC. The earlier 77 common-boundary scopes alone are not a board signoff.
No bitstream or board programming is authorized before the complete gates pass.
