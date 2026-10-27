"""This batch's reviewed 13-locator relocation, NOT raw/source-only FIR equality.

Historical normalize_fir remains unchanged. No new diagnostic text, condition,
clock, label, location mapping, or functional FIR byte is ignored.
"""
import hashlib
import re
import subprocess
import buffered_return_flow_cpu as prior

MAPPING = {('LoadStoreUnit.scala', 352): 358,
           ('ParallelLoadStoreUnit.scala', 276): 277,
           ('ParallelLoadStoreUnit.scala', 277): 278}
EXPECTED = {('LoadStoreUnit.scala', 352): 5,
            ('ParallelLoadStoreUnit.scala', 276): 4,
            ('ParallelLoadStoreUnit.scala', 277): 4}
COMMIT = '51422f567dd8d15d72373ea4984d13ab3ed3650e'
RX = re.compile(rb'(intrinsic\(circt_chisel_ifelsefatal<format = "Assertion failed at )'
                rb'(LoadStoreUnit\.scala|ParallelLoadStoreUnit\.scala):(\d+)'
                rb'(\\n", label = "chisel3_builtin">,)')


def relocate_old(data):
    counts = dict.fromkeys(MAPPING, 0)
    def replace(match):
        key = (match[2].decode(), int(match[3]))
        target = MAPPING.get(key)
        if target is None:
            return match[0]
        counts[key] += 1
        return match[1] + match[2] + b':' + str(target).encode() + match[4]
    # Exactly one pass prevents old 276->277 being spuriously relocated again.
    result = RX.sub(replace, data)
    prior.need(counts == EXPECTED, 'approved diagnostic relocation counts changed: ' + repr(counts))
    return result


def compare(a, b):
    return relocate_old(prior.row.normalize_fir(a)) == prior.row.normalize_fir(b)


def validate(a, b):
    prior.need(compare(a, b), 'OFF_FIR_DRIFT beyond approved 13 diagnostic source locators')
    mapping = []
    sources = {}
    for (file, line), new_line in MAPPING.items():
        path = 'src/main/scala/core/ooo/lsu/' + file
        before = subprocess.check_output(['git', 'show', COMMIT + ':' + path],
                                          cwd=prior.common.ROOT, text=True).splitlines()[line - 1]
        after = (prior.common.ROOT / path).read_text().splitlines()[new_line - 1]
        prior.need(before == after and before.strip().startswith('assert('),
                   'source assertion is not identical at approved relocation: ' + file)
        sources[path] = prior.sha(prior.common.ROOT / path)
        mapping.append({'file': file, 'old_line': line, 'new_line': new_line,
                        'occurrences': EXPECTED[(file, line)], 'unchanged_source_assertion': before.strip()})
    probes = [
        (b'Assertion failed at LoadStoreUnit.scala:358', b'Assertion FAILED at LoadStoreUnit.scala:358', 'diagnostic_body'),
        (b'label = "chisel3_builtin">, clock, _T_189, _T_191)',
         b'label = "chisel3_builtin">, clock, _T_189, _T_190)', 'assert_predicate'),
        (b'connect supply_states_bore, state', b'connect supply_states_bore, UInt<2>(0h0)', 'logic'),
        (b'Assertion failed at LoadStoreUnit.scala:358', b'Assertion failed at LoadStoreUnit.scala:359', 'unapproved_source_line')]
    negatives = []
    for find, replacement, name in probes:
        prior.need(find in b, 'diagnostic negative calibration anchor missing: ' + name)
        prior.need(not compare(a, b.replace(find, replacement, 1)), 'diagnostic comparator accepted mutant: ' + name)
        negatives.append(name)
    return {'status': 'PASS_LIMITED_DIAGNOSTIC_RELOCATION_EQUALITY',
            'raw_source_only_fir_exact': prior.row.normalize_fir(a) == prior.row.normalize_fir(b),
            'comparison': 'only 13 generated assertion source locators relocated; all other normalized bytes exact',
            'mapping': mapping, 'source_inputs': sources, 'negative_calibrations': negatives,
            'old_sha256': hashlib.sha256(a).hexdigest(), 'new_sha256': hashlib.sha256(b).hexdigest()}
