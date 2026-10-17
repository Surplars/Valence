# Compact posted-store members: isolated evidence

This source-only supplement preserves the tested compact member-bank candidate. It depends on the sibling `posted_full_line_stagea_r1` package at commit `d5a2d1c144e79cc71c0778b4647077d86ae9715e`; all dependency hashes are in DEPENDENCIES.json. No production profile is enabled. The new constructor option `compactMembers` defaults to false. The immutable r1 full-line policy is reused; this is not the r2 policy-identity variant.

Each of sixteen member entries retains the full ROB token, owner slot and generation, and response ticket. Only the selected outgoing ACK/head member reconstructs its remaining context from the live parent. Parent release remains blocked while members exist. The external ACK/drain shapes are unchanged. Raw member storage changes from 4,720 to 2,144 bits; measured synthesis results, rather than this inventory, establish the mapped reduction.

## Qualified results

The original 32-case suite and eight directed lifetime cases pass. The original suite contains 21 positive cases, six RTL assertion negatives and five observation-sensitivity checks. The supplement contains four positive schedules, three RTL assertion negatives and one public-observation mutation. The last is not an internal storage-fault injection. Held drain across another owner's release and later generation reuse, delayed ACK/writeback, 24-token ring wrap and fatal refill behind a held success are covered.

All 1,041 checked r1 public-cycle samples match with identical stimuli, controls and valid payloads; invalid payload bits are excluded. The short-policy log is byte-identical. Default-OFF lowered owner SV is byte-identical to the qualified baseline.

Standalone 8-set, two-owner, 16-member, generation64/epoch32, timeout256 mapping gives 6,654 LUT and 4,109 FF versus r1's 7,143 LUT and 6,589 FF: 489 fewer LUT (6.85%) and 2,480 fewer FF (37.64%). Neither arm uses RAM. Correct-cut pre-ABC capture confirms 2,480 fewer sequential cells and 2,170 fewer mux cells; all other cell counts match. ABC ordering can affect LUT counts. No physical timing or logic-depth measurement was obtained.

This is component evidence under explicit synthetic authorization and coherence-completion premises. It does not qualify CPU/cache/Home integration, selected 256-set geometry, read-allocation elimination, system throughput or Fmax. The original mapped baseline was reused, not rerun.

Source files retain their existing notices. Historical archive resources and HardFloat notices/licenses remain required dependencies; no new license grant is asserted. Raw execution logs/manifests and generated artifacts are intentionally excluded. Fresh-machine replay of these packaged instructions has not been performed.
