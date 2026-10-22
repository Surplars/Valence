# Exact extracted park-history checker unit

The current TB history always-block and final cancel-order assertion are extracted unchanged into a tiny Icarus fixture. Two positive cases pass: cancellation without park or qualifying idle history, and a legal later park following prior matching raw-held plus idle. Three negative cases enter the same ordinary checker and are rejected: park with no history, park with only a simultaneous first history sample, and park under a different epoch from stale history.

Source/extraction/tool/artifact hashes and subprocess reaping are recorded and independently rechecked. This validates only checker logic; it does not replace the real bank's normal/cancel matrix. The preliminary r1 harness setup failure is preserved separately; its incorrect str/Path argument failed before any compiler started. No DUT source changes.
