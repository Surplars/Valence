"""Exact sealed 6b223 OFF comparison; source annotations alone are removable.

No logic stripping, module filtering, inferred renaming, assertion-message
normalization or diagnostic line relocation is allowed.
"""
import hashlib
import re

COMMIT = '6b223f03c362b4a31d8dc95ef811cb21a21ef858'

def normalize(data):
    return re.sub(rb'"(?:\\.|[^"\\])*"| @\[[^\]\n]*\]',
                  lambda m: m[0] if m[0].startswith(b'"') else b'', data)

def compare(a, b):
    return normalize(a) == normalize(b)

def validate(a, b):
    if not compare(a, b):
        raise RuntimeError('OFF_FIR_DRIFT: only source-location annotations may differ')
    norm = normalize(b)
    assertion = next((x for x in norm.splitlines() if b'intrinsic(circt_chisel_ifelsefatal' in x), None)
    connection = next((x for x in norm.splitlines() if b'connect ' in x and b', ' in x), None)
    if assertion is None or connection is None:
        raise RuntimeError('missing exact OFF negative-calibration anchors')
    call = re.search(rb'(label = "chisel3_builtin">, [^,]+, [^,]+, )([^\)]+)(\))', assertion)
    if call is None:
        raise RuntimeError('missing assertion predicate anchor')
    predicate = assertion.replace(call[0], call[1] + b'UInt<1>(0h0)' + call[3], 1)
    mutations = {
        'assertion_body': norm.replace(assertion, assertion.replace(b'format = "', b'format = "MUTANT ', 1), 1),
        'assertion_predicate': norm.replace(assertion, predicate, 1),
        'functional_connection': norm.replace(connection, connection.split(b', ', 1)[0] + b', UInt<1>(0h0)', 1),
        'nonlocation_annotation': norm + b'\n; MUTANT functional byte\n',
    }
    for name, mutant in mutations.items():
        if mutant == norm or compare(a, mutant):
            raise RuntimeError('OFF comparator accepted negative mutation ' + name)
    return {'status': 'PASS_EXACT_OFF_SOURCE_LOCATIONS_ONLY', 'old_commit': COMMIT,
            'negative_calibrations': list(mutations), 'old_sha256': hashlib.sha256(a).hexdigest(),
            'new_sha256': hashlib.sha256(b).hexdigest()}
