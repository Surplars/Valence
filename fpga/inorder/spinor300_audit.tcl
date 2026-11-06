# Read-only inspection of the routed reset synchronizers; no implementation rerun.
if {$argc != 2} {error "usage: spinor300_audit.tcl ROUTED_DCP FRESH_OUTPUT"}
lassign $argv checkpoint output
set allowed [string tolower [file normalize E:/VM/Share/Valence-rtl/Valence-InOrder]]
foreach path [list $checkpoint $output] {
    if {![string match "${allowed}/*" [string tolower [file normalize $path]]]} {error "outside designated root"}
}
if {[file exists $output]} {error "fresh audit evidence required"}
file mkdir $output
set_param general.maxThreads 8
puts "VIVADO_THREADS [get_param general.maxThreads]"
open_checkpoint $checkpoint
set fd [open [file join $output reset_registers.tsv] w]
puts $fd "cell\tprimitive\tclock\tASYNC_REG\tlocation\tdata_startpoints\treset_startpoints"
set cells [get_cells -quiet -hierarchical -filter {REF_NAME =~ FD* && NAME =~ *Release/release*}]
if {![llength $cells]} {error "no reset synchronizers found"}
foreach cell [lsort $cells] {
    set clocks [get_clocks -quiet -of_objects [get_pins -of_objects $cell -filter {REF_PIN_NAME == C}]]
    set data [all_fanin -flat -startpoints_only -to [get_pins -of_objects $cell -filter {REF_PIN_NAME == D}]]
    set resets [get_pins -of_objects $cell -filter {REF_PIN_NAME == PRE || REF_PIN_NAME == CLR}]
    set source [all_fanin -flat -startpoints_only -to $resets]
    puts $fd [join [list $cell [get_property REF_NAME $cell] $clocks [get_property ASYNC_REG $cell] \
        [get_property LOC $cell] $data $source] "\t"]
}
close $fd
# Optimization leaves some overlapping synthesis-time path groups empty.
# Query real routed module endpoints without changing groups or timing constraints.
set fd [open [file join $output module_endpoints.tsv] w]
puts $fd "module\troot\tsequential_cells\toriginal_group_paths"
foreach {name root} {cpu dut/cpu spinor dut/vector boundary dut/boundary mdu dut/cpu/core/mulDiv \
    icache dut/cpu/icache dcache dut/cpu/dcache} {
    set endpoints [get_cells -quiet -hierarchical -filter "NAME =~ $root/* && (REF_NAME =~ FD* || REF_NAME =~ RAM* || REF_NAME =~ DSP*)"]
    if {![llength $endpoints]} {error "routed module endpoints missing: $root"}
    set old [get_timing_paths -group i1_$name -max_paths 1]
    puts $fd "$name\t$root\t[llength $endpoints]\t[llength $old]"
    report_timing -to $endpoints -delay_type max -max_paths 10 -nworst 1 \
        -file [file join $output ${name}_module_setup.rpt]
}
close $fd
report_route_status -route_type GAPS -list_all_nets -file [file join $output route_gaps.rpt]
set fd [open [file join $output route_gap_names.txt] w]
foreach net [report_route_status -route_type GAPS -return_nets] {puts $fd $net}
close $fd
proc domain_states {clock root} {
    return [lsort -unique [concat [all_registers -clock $clock] \
        [get_cells -quiet -hierarchical -filter "NAME =~ $root/* && (REF_NAME =~ RAM* || REF_NAME =~ DSP*)"]]]
}
set counts [open [file join $output counts.tsv] w]
puts $counts "domain\ttype\tnegative_endpoints"
foreach {domain clock root} {cpu i1_cpu300 dut/cpu vpu i1_vpu300 dut/vector} {
    set states [domain_states $clock $root]
    foreach {type delay} {setup max hold min} {
        set paths [get_timing_paths -from $states -to $states -delay_type $delay \
            -slack_lesser_than 0 -nworst 1 -max_paths 100000 -sort_by slack]
        if {[llength $paths] >= 100000} {error "negative endpoint inventory limit reached"}
        puts $counts "$domain\t$type\t[llength $paths]"
        set fd [open [file join $output ${domain}_${type}_negative.tsv] w]
        puts $fd "slack_ns\tstart\tend\tgroup\tdata_delay_ns"
        foreach path $paths {
            puts $fd "[get_property SLACK $path]\t[get_property STARTPOINT_PIN $path]\t[get_property ENDPOINT_PIN $path]\t[get_property GROUP $path]\t[get_property DATAPATH_DELAY $path]"
        }
        close $fd
        if {[llength $paths]} {
            report_timing -of_objects $paths -file [file join $output ${domain}_${type}_negative.rpt]
        }
    }
}
foreach {type delay} {setup max hold min} {
    set paths [get_timing_paths -delay_type $delay -slack_lesser_than 0 -nworst 1 -max_paths 100000 -sort_by slack]
    puts $counts "whole_top\t$type\t[llength $paths]"
}
close $counts
puts "I1_NEGATIVE_ENDPOINT_INVENTORY_DONE READ_ONLY"
puts "I1_SPINOR300_READ_ONLY_RESET_AUDIT_DONE registers=[llength $cells]"
close_design
