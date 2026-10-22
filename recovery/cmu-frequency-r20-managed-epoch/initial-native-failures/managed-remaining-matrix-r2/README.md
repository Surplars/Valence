# Overstrong diagnostic history assertion

The corrected cancellation stimulus completed the actual AON-backpressure experiment, sequential fixed-clock retirement receipts, retained timer reply and all-domain exactly-once terminal join in71.148420 seconds. It then failed the newly added final history assertion. The exact FAIL result and logs remain unchanged; rc1 and child reaping are confirmed. No later case started.

The actual runtime park-edge count was zero. The new final assertion incorrectly demanded a matching held-plus-idle qualification history even when no park was requested. That is not required for cancellation. The per-edge contract is conditional: every actual park must have a prior matching raw-held-plus-idle witness. This checker remains unchanged. The unconditional end-of-cancel prerequisite is removed; raw-held observations and qualifying held-plus-idle observations are now counted separately. All actual early-cancel acceptance, AON ownership/no-retirement, release and final exactly-once conservation obligations remain intact.

This is a test-oracle correction, not a DUT correction or a case PASS. Normal source-bound requalification is required again before the remaining matrix.
