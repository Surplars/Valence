#pragma once
// Fresh actual life16 header: candidateRemaining is a width4 scalar at line2214.
// Exact header/FIR/profile hashes and field provenance are bound in GETTER-BINDING-R1.json.
#if PREFETCH_CANDIDATE_CYCLES > 1
#define PREFETCH_CANDIDATE_REMAINING(d) ((d).board$platform$privateCache$candidateRemaining)
#endif
