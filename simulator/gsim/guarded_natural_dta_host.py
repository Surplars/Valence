"""Exact, bounded derivation of the sealed independent real-DTA driver.

The old driver stays byte-for-byte unchanged. No bus, PTE, permission, queue,
latency or reply oracle is rewritten; six exact marked changes implement the new
standalone raw-invalid contract and its passive hint/idle coverage.
"""
from pathlib import Path
import hashlib
BASE_SHA = 'fc7198ab5e323ba0488df216a3a0d54a9680cae1f3adba686e498a4017b34459'
HERE = Path(__file__).resolve().parent

def derive():
    path=HERE/'harness/registered_raw_certified_flow.cpp'
    source=path.read_text()
    assert hashlib.sha256(path.read_bytes()).hexdigest()==BASE_SHA,'sealed original DTA host changed'
    edits=[
        ('mode == "--inject-fault" || mode == "--inject-canonical" || mode == "--force-undrained-flush"',
         'mode == "--inject-fault" || mode == "--inject-canonical" || mode == "--inject-hint" || mode == "--force-undrained-flush"'),
        ('using namespace canonical_store_test;', '#ifndef GUARDED_NATURAL_DTA\n#define GUARDED_NATURAL_DTA 0\n#endif\nusing namespace canonical_store_test;'),
        ('        auto actualShape = a; actualShape.physicalAddress = e.physical;',
         '        // Independent arithmetic divisibility, not the DUT low-bit mask.\n'
         '        if (GUARDED_NATURAL_DTA && e.physical % (uint64_t(1) << a.size) != 0)\n'
         '            e.accessFault = true;\n'
         '        auto actualShape = a; actualShape.physicalAddress = e.physical;'),
        ('        const auto r = request.value_or(Request{}); const auto &a = r.descriptor;',
         '        Request idle; idle.descriptor.virtualAddress = ram + 1; idle.descriptor.size = 3;\n'
         '        const auto r = request.value_or(idle); const auto &a = r.descriptor;'),
        ('            e.checked = true;',
         '            const bool poisonHint = mutate("--inject-hint", "INJECT GUARDED_NATURAL_DTA checked hint");\n'
         '            check((bool(d.get_checkedHint()) ^ poisonHint) == e.prefetch,\n'
         '                "independent captured next-line permission mismatch");\n'
         '            e.checked = true;'),
        ('    std::cout << "REGISTERED_RAW_CERTIFIED_FLOW_PASS enabled="',
         (HERE/'harness/guarded_natural_dta_cases.inc').read_text()+'\n    std::cout << "REGISTERED_RAW_CERTIFIED_FLOW_PASS enabled="'),
    ]
    for old,new in edits:
        assert source.count(old)==1, ('host derivation anchor changed',old)
        source=source.replace(old,new)
    return source

if __name__=='__main__':
    import sys
    Path(sys.argv[1]).write_text(derive())
