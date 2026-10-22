"""Exercise existing independent graph/negative fixtures with a live session.

No native Vivado or time qualification. Reuses test data and ordinary checker
oracles; no synthetic direct fatal substitutes for corrupted observations.
Usage: python3 test_collect_existing.py immutable_75cb_common_cdc.tcl
"""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
BASE_SHA = '75cb49a48404ede21d46f9714427efcafbe129d66208e776e843274970fc7edc'
base = Path(sys.argv[1]).resolve()
assert hashlib.sha256(base.read_bytes()).hexdigest() == BASE_SHA


def execute(text, label):
    # Keep info script beside the existing fixture dependencies.
    with tempfile.NamedTemporaryFile('w', dir=HERE, prefix='session-test-', suffix='.tcl') as f:
        f.write(text)
        f.flush()
        result = subprocess.run(['tclsh', f.name], text=True, capture_output=True, timeout=120)
    print(result.stdout, end='')
    if result.returncode:
        raise RuntimeError(f'{label}:\n{result.stderr}')


text = (HERE / 'test_payload_query_reuse.tcl').read_text()
start = text.index('set baseline_helpers {}')
end = text.index('\nproc assert ', start)
text = text[:start] + '''rename ::common_cdc::payload ::common_cdc::payload_baseline
source $candidate
rename ::common_cdc::payload ::common_cdc::payload_session_body
proc ::common_cdc::payload_candidate {h} {
    return [::common_collect_session::run [list ::common_cdc::payload_session_body $h]]
}
''' + text[end:]
text = text.replace('set baseline [file join $root common_cdc.baseline.tcl]', f'set baseline {{{base}}}')
text = text.replace('assert {[string match $message_pattern [dict get $new result]]}',
                    'assert {[string match $message_pattern [dict get $new result]] || [string match {COMMON_COLLECT malformed*} [dict get $new result]] || [dict get $new result] in {{COMMON_COLLECT bulk cell NAME order/identity mismatch} {COMMON_COLLECT non-cell in native get_cells collection}}}')
text = text.replace('if {$key eq {all_fanin}} {', 'if {$key in {all_fanin get_nets_segments get_cells_owner}} {')
execute(text, 'active payload equivalence')

text = (HERE / 'test_mailbox_internal_constant.tcl').read_text()
needle = 'source $candidate\n'
wrappers = '''source $candidate
foreach name {mailbox_width mailbox_unconsumed_constant} {
    rename ::common_cdc::$name ::common_cdc::${name}_session_body
    proc ::common_cdc::$name {args} [format {
        set script [list ::common_cdc::%s_session_body {*}$args]
        if {$::common_collect_session::active} {return [uplevel 1 $script]}
        return [::common_collect_session::run $script]
    } $name]
}
'''
assert text.count(needle) == 1
text = text.replace(needle, wrappers)
# Bulk-invalid observations are rejected earlier; do not force the old textual
# diagnostic, but retain every original reject/accept and scope-field oracle.
text = text.replace('assert {[string match $diagnostic $why]}',
                    'assert {[string match $diagnostic $why] || [string match {COMMON_COLLECT malformed*} $why] || $why in {{COMMON_COLLECT bulk cell NAME order/identity mismatch} {COMMON_COLLECT non-cell in native get_cells collection}}}')
execute(text, 'active internal-constant fixtures')
print('COLLECT_EXISTING_FIXTURES_PASS NATIVE_NOT_RUN PERFORMANCE_NOT_QUALIFIED')
