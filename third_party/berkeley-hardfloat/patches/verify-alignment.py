"""Exhaust the finite bit-vector identity used by the local AddRecFN patch.

This checks the expression identity, not the hardware or simulator itself;
the independent SoftFloat GSIM differential checks the arithmetic behavior.
"""
for a in range(1024):
    for b in range(1024):
        sa = a if a < 512 else a - 1024
        sb = b if b < 512 else b - 1024
        diff = (sa - sb) & 1023
        signed_diff = diff if diff < 512 else diff - 1024
        original = ((sb - sa) if signed_diff < 0 else signed_diff) & 31
        replacement = ((b - a) if signed_diff < 0 else (a - b)) & 31
        assert original == replacement
print("ALIGNMENT_EQUIVALENCE_PASS signed_input_pairs=1048576")
