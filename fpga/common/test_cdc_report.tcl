# Pure Tcl parser/gate tests. The retained report is historical format evidence,
# not the current candidate's CDC census or any physical qualification.
set ::common_board_definitions_only 1
source [file join [file dirname [info script]] board_audit.tcl]
proc assert {condition why} {if {![uplevel 1 [list expr $condition]]} {error $why}}
proc reject {text why} {
    assert {[catch {common_board::cdc_report $text} reason]} "$why accepted"
    assert {[string match {*unsupported report_cdc summary*} $reason]} "$why: unexpected error: $reason"
}
set root [file normalize [file join [file dirname [info script]] ../..]]
set f [open [file join $root recovery reset-signoff-r2 cdc-full.rpt]]
set actual [read $f]; close $f
set expected [dict create Critical 21 Warning 1282 Info 217]
assert {[common_board::cdc_report $actual] eq $expected} {historical 2025.2 summary tally wrong or detail rows counted twice}
assert {[common_board::cdc_report [string map [list \n \r\n] $actual]] eq $expected} {CRLF report rejected}

# Compatibility with the prior accepted pipe-row order, now bounded by its
# explicit header and closing border. This is a synthetic compatibility test.
set pipe {CDC Report
+--------+----------+---------------------------------------------------+-------+
| ID     | Severity | Description                                       | Count |
+--------+----------+---------------------------------------------------+-------+
| CDC-3  | Info     | 1-bit synchronized with ASYNC_REG property         | 209   |
| CDC-6  | Warning  | Multi-bit synchronized with ASYNC_REG property     | 11    |
| CDC-9  | Info     | Asynchronous reset synchronized                   | 8     |
| CDC-10 | Critical | Combinational logic detected before a synchronizer| 10    |
| CDC-11 | Critical | Fan-out from launch flop to destination clock      | 11    |
| CDC-15 | Warning  | Clock enable controlled CDC structure detected    | 1271  |
+--------+----------+---------------------------------------------------+-------+

Source Clock: source_clock
Destination Clock: destination_clock
CDC Type: No Common Primary Clock
| CDC-10 | Critical | detail rows are not summary rows | 999 |
}
assert {[common_board::cdc_report $pipe] eq $expected} {pipe compatibility or detail boundary failed}

set header {ID      Severity  Count  Description}
set critical {CDC-10  Critical     10  Combinational logic detected before a synchronizer}
foreach {label from to} [list \
    missing_header $header {} \
    unknown_header $header {ID Severity Instances Description} \
    reordered_header $header {ID Severity Description Count} \
    unknown_severity $critical {CDC-10 Severe 10 Combinational logic detected before a synchronizer} \
    missing_severity $critical {CDC-10 10 Combinational logic detected before a synchronizer} \
    missing_count $critical {CDC-10 Critical Combinational logic detected before a synchronizer} \
    invalid_count $critical {CDC-10 Critical unknown Combinational logic detected before a synchronizer} \
    negative_count $critical {CDC-10 Critical -1 Combinational logic detected before a synchronizer} \
    fractional_count $critical {CDC-10 Critical 1.5 Combinational logic detected before a synchronizer} \
    missing_description $critical {CDC-10 Critical 10} \
    duplicate_rule $critical "$critical\n$critical" \
    unexpected_summary_line $critical "$critical\nunsupported summary row" \
    interrupted_summary $critical "$critical\n"] {
    assert {[string first $from $actual]>=0} "$label mutation did not match the retained fixture"
    reject [string map [list $from $to] $actual] $label
}
reject {} empty
reject {No Critical crossings found.} prose_only
set summary_start [string first $header $actual]
set details_start [string first {Source Clock:} $actual]
reject [string range $actual 0 [expr {$summary_start-1}]] truncated_before_header
reject [string range $actual 0 [expr {[string first $critical $actual]-1}]] truncated_inside_summary
reject [string range $actual 0 [expr {$details_start-1}]] truncated_before_boundary
reject [string range $actual $details_start end] detail_only
reject [string map [list {CDC Report} {Unknown Report}] $actual] missing_title
reject [string map [list {| CDC-10 | Critical |} {| CDC-10 | Unknown  |}] $pipe] malformed_pipe_critical
reject [string map [list {| 10    |} {| ?     |}] $pipe] invalid_pipe_count
reject [string map [list {| CDC-10 | Critical |} {| CDC-11 | Critical |}] $pipe] duplicate_pipe_rule
set pipe_end [string last {+--------+----------+---------------------------------------------------+-------+} $pipe]
reject [string range $pipe 0 [expr {$pipe_end-1}]] unclosed_pipe_summary

# Exercise the actual cdc gate, without Vivado/netlist/timing behavior. Parsing
# Critical findings must still block, and a later unknown report must not retain
# a previous numeric count (especially zero) in board-audit.json.
proc common_cdc::collect {} {return {}}
proc common_cdc::audit_timing args {}
proc common_board::payloads {} {}
proc report_cdc args {
    set f [open [lindex $args end] w]; puts -nonewline $f $::report_text; close $f
}
set f [file tempfile directory]; close $f; file delete $directory; file mkdir $directory
set ::valence(out) $directory
try {
    set report_text $actual
    assert {[catch {common_board::cdc} reason]} {historical Critical report incorrectly passed the gate}
    assert {[string match {*21 unreviewed Critical crossings*} $reason]} {Critical gate did not preserve its diagnostic}
    assert {$::common_board::critical==21} {Critical count not exposed on the blocked result}
    set f [open [file join $directory common-bus-skew.rpt] w]; close $f
    # Synthetic zero case only: mutate both known Critical summary counts, not
    # their detailed rows. This deliberately demonstrates summary-only counting.
    set zero [string map [list {CDC-10  Critical     10} {CDC-10  Critical      0} \
        {CDC-11  Critical     11} {CDC-11  Critical      0}] $actual]
    set report_text $zero
    common_board::cdc
    assert {$::common_board::critical==0} {synthetic zero summary not parsed}
    set report_text [string map [list $critical {CDC-10 Critical unknown description}] $actual]
    assert {[catch {common_board::cdc} reason]} {malformed Critical summary passed the gate}
    assert {$::common_board::critical eq "null"} {parse failure retained a previous zero/PASS-looking count}
    proc common_cdc::collect {} {error early_structure_failure}
    set ::common_board::critical 0
    assert {[catch {common_board::cdc} reason]} {structural failure not propagated}
    assert {$::common_board::critical eq "null"} {early CDC failure retained a stale zero count}
} finally {file delete -force $directory}
puts COMMON_CDC_REPORT_FORMAT_AND_NEGATIVE_CONTROLS_PASS_NOT_PHYSICAL_EVIDENCE
