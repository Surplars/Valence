if {$argc!=1} {error {usage: diagnostic-session-r7.tcl DIAGNOSTIC_ROOT}}
set root [file normalize [lindex $argv 0]]
set pkg [file join $root package combined-timing-repair-transfer-r1]
set deps [file join $root dependencies]
set out [file join $root run-r7]
if {[file exists $out]} {error {Preserve previous retained session}}
file mkdir $out;cd $out
file mkdir commands
set ::env(PYTHONDONTWRITEBYTECODE) 1
if {[info exists ::env(WSLENV)] && $::env(WSLENV) ne {}} {append ::env(WSLENV) {:PYTHONDONTWRITEBYTECODE/u}} else {set ::env(WSLENV) {PYTHONDONTWRITEBYTECODE/u}}
proc diag_event {stage status {detail {}}} {
    set f [open events.tsv a];set stamp [clock format [clock seconds] -gmt 1 -format {%Y-%m-%dT%H:%M:%SZ}]
    puts $f [join [list $stamp [pid] $stage $status [string map [list \n { } \r { } \t { }] $detail]] \t];close $f
    puts "DIAG_EVENT $stamp PID=[pid] $stage $status $detail";flush stdout
}
proc diag_seal {stage dcp} {puts [exec {D:/TOOLS/ENV/anaconda3/python.exe} -I -B [file join $::root orchestration seal_stage.py] $::root $stage $dcp [pid]]}
proc diag_save {stage name} {write_checkpoint $name;diag_seal $stage [file normalize $name]}
set_param general.maxThreads 4
diag_event session begin {RETAIN_CURRENT_NEW_CANDIDATE_DCP_NO_SYNTHESIS}
puts [exec {D:/TOOLS/ENV/anaconda3/python.exe} -I -B [file join $root orchestration verify_recovery.py] $root]
open_checkpoint [file join $root run-r1 raw-synth.dcp]
source [file join $pkg source fpga next physical_eval r3_common.tcl]
r3_discover
file mkdir complete-clock-properties
set index [open complete-clock-properties/index.tcllist w]
set pn 0;set cn 0
foreach cell [lsort [get_cells -hier -filter "NAME =~ $V_ROM_ROOT/memory/* && IS_PRIMITIVE == 1"]] {
    set ref [get_property REF_NAME $cell]
    if {$ref ni {RAMB36E2 FDRE FDCE FDSE FDPE}} {continue}
    incr cn
    set cp [format {complete-clock-properties/cell-%03d.rpt} $cn]
    report_property -all -file $cp $cell
    puts $index [list CELL $cell REF $ref FULL_PROPERTIES_FILE $cp PROPERTY_NAMES [list_property $cell]]
    foreach pin [get_pins -of_objects $cell] {
        if {[get_property IS_CLOCK $pin] ni {1 TRUE true 1'b1}} {continue}
        incr pn
        set pp [format {complete-clock-properties/pin-%03d.rpt} $pn]
        report_property -all -file $pp $pin
        puts $index [list PIN $pin REF $ref FULL_PROPERTIES_FILE $pp PROPERTY_NAMES [list_property $pin] IS_INVERTED [get_property IS_INVERTED $pin] DIRECTION [get_property DIRECTION $pin] IS_LEAF [get_property IS_LEAF $pin]]
    }
}
puts $index [list COUNTS CLOCK_PINS $pn CLOCK_CELLS $cn];close $index
if {$pn!=64 || $cn!=35} {error {Changed complete clock-object inventory}}
report_utilization -hierarchical -file original-synth-utilization.rpt
diag_event clock_properties collected {64_PINS_35_CELLS_FULL_PROPERTY_NAMES_AND_VALUES}
set f [open SESSION_READY.txt w];puts $f [list PID [pid] STATUS RETAINED_CURRENT_DCP_READY_FOR_EXTERNAL_COMMANDS];close $f
# Explicit local command files are authored by the diagnostic owner. Preserve
# the live DCP on command failures so further actual-object queries do not need
# another Vivado process. No command is implicitly retried.
while {![file exists SESSION_EXIT.txt]} {
    foreach command [lsort [glob -nocomplain commands/*.tcl]] {
        if {[file exists ${command}.started]} {continue}
        set f [open ${command}.started {WRONLY CREAT EXCL}];puts $f [clock seconds];close $f
        diag_event command begin $command
        set code [catch {source $command} why options]
        if {$code} {
            set f [open ${command}.error.txt w];puts $f $why;puts $f [dict get $options -errorinfo];close $f
            diag_event command failed "$command $why"
        } else {diag_event command complete $command}
    }
    after 1000
}
diag_event session complete {EXPLICIT_EXIT_NO_ROUTE_NO_BIT}
close_design
exit 0
