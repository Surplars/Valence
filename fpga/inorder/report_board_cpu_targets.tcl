# Read-only targeted STA on the currently open, fully routed I1 board.
proc i1_board_cpu_target_paths {reports} {
    set f [open [file join $reports target_timing.tsv] w]
    puts $f "target\tmatched_pins\tslack_ns\tstartpoint\tendpoint"
    foreach {label pattern pinfilter} {
        home_state {(NAME =~ u_soc/soc/fabric/home/state_reg* || NAME =~ u_soc/soc/fabric/home/stateStorage_reg*) && IS_SEQUENTIAL} {DIRECTION == IN && REF_PIN_NAME != C}
        predicted_pc {NAME =~ u_soc/soc/core/core/offerPc_reg* && IS_SEQUENTIAL} {DIRECTION == IN && REF_PIN_NAME != C}
        fetch_alignment {(NAME =~ u_soc/soc/core/aligner/cuts/firstHalf_reg* || NAME =~ u_soc/soc/core/aligner/cuts/result_instruction_reg*) && IS_SEQUENTIAL} {DIRECTION == IN && REF_PIN_NAME != C}
        jtag_control {NAME =~ u_soc/soc/loader/sbError* && IS_SEQUENTIAL} {DIRECTION == IN && REF_PIN_NAME != C}
        home_probe {NAME =~ u_soc/soc/fabric/home/probeAddress_reg* && IS_SEQUENTIAL} {DIRECTION == IN && REF_PIN_NAME != C}
        metadata_write {NAME =~ u_soc/soc/core/dcache/coherent/*I1PreparedMetadataQueue*/ram_ext/*} {REF_PIN_NAME == WE}
    } {
        set cells [get_cells -quiet -hier -filter $pattern]
        set pins [get_pins -quiet -of_objects $cells -filter $pinfilter]
        if {![llength $cells] || ![llength $pins]} {error "Missing board target: $label"}
        set path [get_timing_paths -to $pins -delay_type max -max_paths 1]
        if {![llength $path]} {error "No timed path to board target: $label"}
        puts $f "$label\t[llength $pins]\t[get_property SLACK $path]\t[get_property STARTPOINT_PIN $path]\t[get_property ENDPOINT_PIN $path]"
        report_timing -to $pins -delay_type max -max_paths 10 -input_pins \
            -file [file join $reports target_${label}.rpt]
    }
    close $f
    puts "I1_BOARD_TARGET_PATHS_REPORTED $reports"
}
