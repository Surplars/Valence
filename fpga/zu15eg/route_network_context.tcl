# Continue from own prepared two-leaf/ROM ECO with verified parent context.
if {$argc!=2} {error "Expected PRIVATE_ROOT DONOR_ROOT"}
lassign $argv root donor
foreach name {root donor} {set $name [file normalize [set $name]]}
set out [file join $root implementation-report-recovery-r1]
if {[file exists [file join $out routed.dcp]]} {error "Preserve routed evidence"}
set_param general.maxThreads 8
open_checkpoint [file join $out patched_boundary_pending.dcp]
foreach {leaf top} {u_soc/platform/privateCache CoherentLineCache u_soc/platform/packetDma EthernetPacketDma} {
    update_design -cells [get_cells $leaf] -black_box
    update_design -cells [get_cells $leaf] -strict -from_file [file join $root partitions-context $top leaf.edf]
}
write_checkpoint [file join $out patched_context.dcp]
report_drc -checks [get_drc_checks LUTOI-1] -file [file join $out context_input_drc.rpt]
if {[llength [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]]} {
    error "Specialized input connectivity DRC failed"
}
# Reuse the unchanged full route/report body, with the selected OWN design
# already open. Only this one open_checkpoint line is removed; every actual
# timing, clock, placement preservation and I/O report check remains intact.
set f [open [file join $root scripts replace_network_candidate.tcl] r]
set body [read $f]; close $f
set needle {open_checkpoint [file join $out patched_boundary_pending.dcp]}
set first [string first $needle $body]
if {$first<0 || [string first $needle $body [expr {$first+1}]]>=0} {error "Ambiguous route body checkpoint selection"}
set body [string replace $body $first [expr {$first+[string length $needle]-1}] {# Own context-specialized design is already open.}]
set argc 3
set argv [list $root $donor route]
eval $body
