# Read-only complete negative endpoint inventory from a frozen routed checkpoint.
if {$argc != 2} {error "usage: spinor_negative_paths.tcl ROUTED_DCP FRESH_OUTPUT"}
lassign $argv checkpoint output
set allowed [string tolower [file normalize E:/VM/Share/Valence-rtl/Valence-InOrder]]
foreach p [list $checkpoint $output] {
    if {![string match "${allowed}/*" [string tolower [file normalize $p]]]} {error "outside designated root"}
}
if {[file exists $output]} {error "fresh negative-path evidence required"}
file mkdir $output
set_param general.maxThreads 8
puts "VIVADO_THREADS [get_param general.maxThreads]"
open_checkpoint $checkpoint
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
close_design
