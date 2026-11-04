# Query optional-unit endpoint timing from existing routed checkpoints.
# This never alters path groups, constraints, placement or routing.
if {$argc < 3} {error "usage: core300_module_reports.tcl IMPLEMENTATION_ROOT FRESH_REPORTS ROLE..."}
set root [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
set roles [lrange $argv 2 end]
set allowed [string tolower [file normalize E:/VM/Share/Valence-rtl/Valence-InOrder]]
foreach path [list $root $output] {
    if {![string match "${allowed}/*" [string tolower $path]]} {error "outside designated root"}
}
if {[file exists $output]} {error "fresh reports required"}
file mkdir $output
set_param general.maxThreads 4
foreach role $roles {
    if {$role ni {ima imc imf imfd imafdc}} {error "unknown ISA assessment role"}
    open_checkpoint [file join $root physical $role routed.dcp]
    set report [open [file join $output ${role}.tsv] w]
    puts $report "unit\tsetup_ns\thold_ns\tsequential_cells"
    set units {}
    if {$role in {ima imafdc}} {lappend units atomic cpu/atomic}
    if {$role in {imf imfd imafdc}} {lappend units execute cpu/core/execute fpr cpu/core/fpr}
    foreach {name pattern} $units {
        if {[llength [get_cells -quiet $pattern]] != 1} {error "missing enabled unit: $pattern"}
        set ends [get_cells -quiet -hierarchical -filter "NAME =~ ${pattern}/* && (REF_NAME =~ FD* || REF_NAME =~ RAM* || REF_NAME =~ DSP*)"]
        if {![llength $ends]} {error "unit exists without actual state: $pattern"}
        report_timing -to $ends -delay_type max -max_paths 10 -nworst 1 -file [file join $output ${role}_${name}_setup.rpt]
        report_timing -to $ends -delay_type min -max_paths 10 -nworst 1 -file [file join $output ${role}_${name}_hold.rpt]
        set setup [get_timing_paths -to $ends -delay_type max -max_paths 1]
        set hold [get_timing_paths -to $ends -delay_type min -max_paths 1]
        puts $report "$name\t[get_property SLACK [lindex $setup 0]]\t[get_property SLACK [lindex $hold 0]]\t[llength $ends]"
    }
    close $report
    close_design
}
puts "OPTIONAL_UNIT_ROUTED_REPORTS_DONE"
