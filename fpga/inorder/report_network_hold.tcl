# Re-query two existing exact constrained checkpoints. NO new synthesis,
# constraints, optimization, placement, routing, or timing exceptions.
if {$argc != 3} { error "usage: report_network_hold.tcl BASELINE_DCP CURRENT_DCP NEW_REPORT_ROOT" }
lassign $argv baseline current output
foreach key {baseline current output} { set $key [file normalize [set $key]] }
if {[file exists $output]} { error "preserve previous comparison evidence" }
file mkdir $output
set_param general.maxThreads 8
set result [open [file join $output result.json] w]
puts $result "{"
set comma ""
foreach {label checkpoint} [list baseline $baseline current $current] {
    open_checkpoint $checkpoint
    if {[get_property TOP [current_design]] ne "I1NetworkFpgaShell"} { error "network checkpoint required" }
    if {abs([get_property PERIOD [get_clocks orbital_i1_cpu]] - 3.333) > 0.0006} {
        error "CPU300MHz target changed"
    }
    set folder [file join $output $label]
    file mkdir $folder
    set all [all_registers]
    set cpu [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL == 1 && NAME =~ soc/*}]
    set ingress [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL == 1 && NAME =~ bank/uart/ingress/*}]
    set uart [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL == 1 && NAME =~ bank/uart/uart/*}]
    puts $result "$comma\"$label\":{"
    set row_comma ""
    foreach {name starts ends} [list internal $all $all cpu_internal $cpu $cpu uart_raw_to_gated $ingress $uart] {
        if {![llength $starts] || ![llength $ends]} { error "missing real hold endpoints: $name" }
        set path [get_timing_paths -from $starts -to $ends -delay_type min -max_paths 1]
        if {[llength $path] != 1} { error "no actual register-to-register hold path: $name" }
        set slack [get_property SLACK $path]
        puts $result "$row_comma\"[set name]_whs_ns\":$slack"
        set row_comma ","
        report_timing -from $starts -to $ends -delay_type min -max_paths 10 -nworst 1 \
            -file [file join $folder hold_$name.rpt]
        puts "I1_HOLD_CHECKPOINT_COMPARE name=$label family=$name whs=$slack checkpoint=$checkpoint"
    }
    # Compare the exact old/new endpoint families as well, without another
    # synthesis or changing a constraint. Main synthesis reports the full top.
    foreach {name pattern} {
        line_writer soc/fabric/home/lineTransfer/writer/*
        ex_packet soc/core/core/addrPacket*
        fetch_admission soc/fabric/nativeCut/*
        instruction_translation soc/core/it/*
        instruction_cache soc/core/icache/coherent/cache/*
        cache_probe *cache/coherent/cache/probe*
        dma dma/*
        cache_metadata *cache/coherent/cache/valid*
        cache_replacement *cache/coherent/cache/replacement*
    } {
        set ends [get_cells -quiet -hierarchical -filter "IS_SEQUENTIAL == 1 && NAME =~ $pattern"]
        if {![llength $ends]} { error "missing actual setup family: $name" }
        set path [get_timing_paths -from $all -to $ends -delay_type max -max_paths 1]
        if {[llength $path] != 1} { error "no actual setup path: $name" }
        set slack [get_property SLACK $path]
        puts $result ",\"[set name]_setup_wns_ns\":$slack"
        report_timing -from $all -to $ends -delay_type max -max_paths 1 \
            -file [file join $folder setup_$name.rpt]
        puts "I1_SETUP_CHECKPOINT_COMPARE name=$label family=$name wns=$slack checkpoint=$checkpoint"
    }
    puts $result "}"
    set comma ","
    close_design
}
puts $result "}"
close $result
puts "I1_HOLD_REPORT_ONLY_DONE TWO_EXISTING_DCPS NO_SYNTHESIS NO_CONSTRAINT_CHANGES NO_ROUTE"
