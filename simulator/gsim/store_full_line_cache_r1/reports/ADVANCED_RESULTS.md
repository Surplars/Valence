# B1 advanced selected-cache results

All six advanced ON cases passed with the same tested executable and qualified r1 posted policy. Independent review verified the 63-file ADVANCED_ARTIFACT_MANIFEST, accepted/ACK/drain counts and event timelines. Full numeric results are in ADVANCED_RESULTS.json.

- Collecting read and masked-write: actual scalar DMA completes before cache acquisition. No B probe is expected while Home has no directory owner. The partial fallback retains the DMA-modified untouched byte, and actual cache readback/final backing bytes agree.
- Installed read and write: actual DMA causes a real B probe and complete dirty C data, independently paired to AW/W/B, before the scalar access completes. Later actual cache reads validate the resulting bytes.
- Permission transient: E accepts at cycle24; DMA accepts25; install26; B first appears/accepts28; response71. This witnesses an accepted DMA operation spanning the E-to-install interval. It does not exercise a B offer stalled before installation because no B is offered that early. Assertions guarding such an event remain present, but are not counted as coverage.
- Dirty victim/reuse: old dirty C-last78 and AW82 precede new permission A85/E87/install89. Old backing B107 and actual cache-side ReleaseAck110 follow. The delayed-ACK test queue may consume Home's response earlier; the observed D is at the cache boundary, and its ownership is retained until acceptance. Readback of the new target and later ordinary reacquisition of the old victim validate bytes, followed by complete flush/drain.

Read accounting spans the whole test, including explicit DMA reads and intentional later Block reacquisitions. Zero-read permission-allocation checkpoints are separate from those deliberate reads. Selected prefetch configuration is enabled, while these cases leave prefetchNextAllowed=0; every ownerless A is bound to an accepted ordinary CPU read.

Two stimulus failures remain preserved: an initial collect_read supplied the masked-write mask128 instead of a natural8-byte mask255 and triggered the real bridge assertion; the first transient stimulus was accepted before E and correctly failed the strict interval witness. All authored DMA cases now share a preflight-validated table. The transient retry triggers on the observed E handshake, not a hardcoded cycle. Neither recovery changes the DUT or weakens its assertions.

This evidence is scoped to the component fixture. It does not establish CPU progress, active-prefetch interference, direct pre-install B backpressure, physical timing or a whole-system resource reduction. OFF model runtime and lowered-default equivalence remain separately gated.
