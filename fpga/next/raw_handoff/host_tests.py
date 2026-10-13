#!/usr/bin/env python3
"""Bounded host-only gate runner. Keeps stdout/stderr for every actual case."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import time
import sys

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / 'evidence'
RESULTS = []


def tcl_case(name, mutation='', mode=1, merge=0, negative=False, checker='audit_raw_handoff.tcl', direct=None):
    with tempfile.TemporaryDirectory(prefix='mac-host-') as tmp:
        code = f'''source {{{HERE / 'typed_host_mock.tcl'}}}
source {{{HERE / checker}}}
rename raw_handoff::bind raw_handoff::real_bind
proc raw_handoff::bind {{contract c}} {{return [list dummy.dcp [string repeat a 64]]}}
set c [mock::fixture {mode} {merge}]
set r [expr {{{mode} ? [dict get $c roles] : {{}}}}]
set root {{fresh.mac[0]}}
{mutation}
dict set c roles $r
set f [open {{{tmp}/contract.tcldict}} w];puts $f $c;close $f
{direct or f'set result [raw_handoff::collect {{{tmp}/contract.tcldict}} {{{tmp}/reports}}]'}
{'' if direct else 'mock::verify_inventory $c'}
puts [list RESULT $result API_BOUNDARIES $mock::api TIMING_QUERIES [llength $mock::timing] REPORTS [llength $mock::reports]]
'''
        script = f'if {{[catch {{\n{code}\n}} err opts]}} {{puts stderr $err;puts stderr [dict get $opts -errorinfo];exit 1}}\n'
        start = time.monotonic()
        try:
            p = subprocess.run(['tclsh'], input=script, text=True, capture_output=True, timeout=35)
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or b'').decode() if isinstance(exc.stdout, bytes) else (exc.stdout or '')
            error = (exc.stderr or b'').decode() if isinstance(exc.stderr, bytes) else (exc.stderr or '')
            (EVIDENCE / f'{name}.log').write_text(output + '\nTIMEOUT 35 seconds\n' + error)
            RESULTS.append(dict(case=name, passed=False, error='TIMEOUT'))
            print(json.dumps(RESULTS[-1]), flush=True)
            return False
        (EVIDENCE / f'{name}.log').write_text(p.stdout + '\nSTDERR:\n' + p.stderr)
        passed = (p.returncode != 0) if negative else (p.returncode == 0)
        record = dict(case=name, expected='reject' if negative else 'accept', passed=passed,
                      exit_code=p.returncode, seconds=round(time.monotonic()-start, 3),
                      error=p.stderr.splitlines()[0] if p.stderr else None)
        RESULTS.append(record)
        print(json.dumps(record), flush=True)
        return passed


def run_tcl():
    # Portable known-bad mutant: no archived collector fixture is required.
    tcl_case('collection_degradation_mutant', negative=True, direct='proc raw_handoff::bad_collection {} {set c [get_cells -quiet -hierarchical -regexp {^fresh[.]mac\\[0\\]$}];llength $c;get_property NAME $c};raw_handoff::bad_collection')
    if not tcl_case('on_positive'):
        return
    tcl_case('off_positive', mode=0)
    tcl_case('valid_activity_merge_positive', merge=1)
    cases = {
        'wrong_edge': 'dict set mock::db pin [lindex [dict get $r falling_rx_outputs] 0]/bad NAME nope\nset f [raw_handoff::owner [lindex [dict get $r falling_rx_outputs] 0]];dict set mock::db pin $f/C IS_INVERTED 0',
        'wrong_init': 'set f [raw_handoff::owner [lindex [dict get $r falling_rx_outputs] 0]];dict set mock::db cell $f INIT 1',
        'conditional_ce': 'set f [raw_handoff::owner [lindex [dict get $r falling_rx_outputs] 0]];dict set mock::arcs $f/CE ground',
        'wrong_clear_polarity': 'set f [raw_handoff::owner [lindex [dict get $r falling_rx_outputs] 0]];dict set mock::db pin $f/CLR IS_INVERTED 1',
        'wrong_reset': 'set f [raw_handoff::owner [lindex [dict get $r falling_rx_outputs] 0]];dict set mock::arcs $f/CLR rxreset',
        'async_reg': 'set f [raw_handoff::owner [lindex [dict get $r falling_rx_outputs] 0]];dict set mock::db cell $f ASYNC_REG 1',
        'missing_bit': 'dict set r falling_rx_outputs [lrange [dict get $r falling_rx_outputs] 0 9]',
        'swapped_bit': 'dict set r managed_rx_outputs [lreplace [dict get $r managed_rx_outputs] 0 1 [lindex [dict get $r managed_rx_outputs] 1] [lindex [dict get $r managed_rx_outputs] 0]]',
        'extra_epoch': 'mock::ff $root/rawHandoff/extra extra ground raw rawreset 1',
        'bypass': 'dict set mock::arcs $root/rx/consumer0/D source0',
        'wrong_pending': 'dict set r rx_pending [lindex [dict get $r managed_rx_outputs] 8]',
        'wrong_decode': 'dict set mock::db cell $root/encode/and INIT 4\'hE',
        'missing_decode_leaf': 'dict set r encoder_phase_and_rate_gap [lrange [dict get $r encoder_phase_and_rate_gap] 0 9]',
        'hidden_decode_source': 'dict set mock::arcs $root/encode/zero_b/I4 active',
        'unsupported_primitive': 'dict set mock::db cell $root/encode/and REF_NAME CARRY8',
        'missing_pending_term': 'dict set mock::db cell $root/idle_b INIT 4\'hC',
        'wrong_divider': 'dict set mock::db cell rawdiv BUFGCE_DIVIDE 8',
        'wrong_waveform': 'dict set mock::db clock rawclk WAVEFORM {0 3}',
        'wrong_ancestry': 'dict set mock::arcs paddiv/I raw',
        'wrong_gate_ce': 'dict set mock::arcs rxgate/CE power',
        'wrong_gate_type': 'dict set mock::db cell rxgate CE_TYPE ASYNC',
        'omitted_consumer': 'dict set r fanouts rx_9 [list $root/rx/consumer9/D]',
        'extra_consumer': 'mock::ff $root/rx/rogue rogue managed0 rxclock rxreset',
        'wrong_sink_clock': 'dict set mock::arcs $root/rx/consumer0/C txclock',
        'empty_bypass': 'dict set mock::arcs $root/ingressEmptySource/D ground',
        'empty_source_drift': 'dict set r empty_launches [list $root/activity0/Q]',
    }
    for name, mutation in cases.items():
        tcl_case(name, mutation, negative=True)
    for fault in ['missing_min','missing_max','missing_clr','wrong_start','wrong_end','nan','negative','relaxed']:
        tcl_case(fault, f'set mock::fault {fault}', negative=True)
    tcl_case('merge_not_reviewed', 'dict set r reviewed_valid_activity_merge 0', merge=1, negative=True)
    tcl_case('merge_tail_mismatch', 'dict set r ingress_activity_tail $root/activity0/Q', merge=1, negative=True)
    tcl_case('off_helper_present', 'mock::ff $root/rawHandoff/rogue rogue ground raw rawreset 1', mode=0, negative=True)
    tcl_case('off_flattened_raw_ff', 'mock::ff $root/flattened rogue ground raw rawreset 1', mode=0, negative=True)
    tcl_case('untyped_boundary', negative=True, direct='get_property NAME {fresh.mac[0]/rawClock}')
    tcl_case('wrong_kind_boundary', negative=True, direct='get_nets -of_objects [raw_handoff::objects cell [list $root]]')
    tcl_case('degraded_collection', negative=True, direct='proc mock_collection_misuse {} {set c [raw_handoff::objects cell [list {fresh.mac[0]}]];llength $c;get_property NAME $c};mock_collection_misuse')
    tcl_case('serialized_timing_path', negative=True, direct='proc mock_path_misuse {} {set p @PATH1;lindex $p 0};mock_path_misuse')


if __name__ == '__main__':
    EVIDENCE.mkdir(exist_ok=True)
    if '--final-smoke' in sys.argv:
        tcl_case('final_collection_mutant', negative=True, direct='proc raw_handoff::bad_collection {} {set c [get_cells -quiet -hierarchical -regexp {^fresh[.]mac\\[0\\]$}];llength $c;get_property NAME $c};raw_handoff::bad_collection')
        tcl_case('final_on_positive')
        tcl_case('final_merge_positive', merge=1)
        tcl_case('final_nan_guard', 'set mock::fault nan', negative=True)
    else:
        run_tcl()
    receipt = dict(status='HOST_MOCK_ONLY', tests=RESULTS,
                   passed=all(r['passed'] for r in RESULTS),
                   source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                  [HERE/'audit_raw_handoff.tcl', HERE/'typed_host_mock.tcl', HERE/'host_tests.py']})
    filename = 'typed-host-final-receipt.json' if '--final-smoke' in sys.argv else 'typed-host-receipt.json'
    (EVIDENCE/filename).write_text(json.dumps(receipt, indent=2)+'\n')
    raise SystemExit(0 if receipt['passed'] else 1)
