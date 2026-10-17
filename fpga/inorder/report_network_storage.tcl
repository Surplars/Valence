# Read-only diagnostics for exact existing constrained checkpoints.
if {$argc != 3} { error "usage: report_network_storage.tcl BASELINE_DCP CURRENT_DCP NEW_OUTPUT" }
lassign $argv baseline current output
foreach name {baseline current output} { set $name [file normalize [set $name]] }
if {[file exists $output]} { error "preserve previous storage timing evidence" }
file mkdir $output
set_param general.maxThreads 8
set result [open [file join $output result.json] w]
puts $result "\{"
set separator ""
foreach {label checkpoint} [list baseline $baseline current $current] {
    open_checkpoint $checkpoint
    if {[get_property TOP [current_design]] ne "I1NetworkFpgaShell" ||
        abs([get_property PERIOD [get_clocks orbital_i1_cpu]] - 3.333) > 0.0006} {
        error "exact network CPU300MHz checkpoint required"
    }
    set folder [file join $output $label]
    file mkdir $folder
    set registers [all_registers]
    set ram [get_cells -quiet -hierarchical -filter \
        {NAME =~ soc/core/icache/coherent/cache/*data* && REF_NAME =~ RAMB*}]
    if {[llength $ram] == 0} { error "real instruction BRAM missing" }
    foreach cell $ram {
        puts "I1_STORAGE_BRAM_PORTS name=$label cell=$cell READ_WIDTH_A=[get_property READ_WIDTH_A $cell] READ_WIDTH_B=[get_property READ_WIDTH_B $cell]"
    }
    set ram_read [get_pins -quiet -of_objects $ram -filter \
        {REF_PIN_NAME =~ ADDRARDADDR* || REF_PIN_NAME =~ ADDRBWRADDR* ||
         REF_PIN_NAME == ENARDEN || REF_PIN_NAME == ENBWREN}]
    set payload [get_cells -quiet -hierarchical -filter \
        {IS_SEQUENTIAL == 1 && NAME =~ soc/fabric/bridge/slots_*/payloadBanks*}]
    set victims [get_cells -quiet -hierarchical -filter \
        {IS_SEQUENTIAL == 1 && NAME =~ soc/core/icache/coherent/cache/victimAddress*}]
    set pending [get_cells -quiet -hierarchical -filter \
        {IS_SEQUENTIAL == 1 && NAME =~ soc/peripherals/plic/pending*}]
    set ex [get_cells -quiet -hierarchical -filter \
        {IS_SEQUENTIAL == 1 && NAME =~ soc/core/core/addrPacket_result*}]
    puts $result "$separator\"$label\":\{"
    set comma ""
    foreach {family starts ends} [list \
        instruction_bram_inputs $registers $ram_read \
        ddr_payload_capture $registers $payload \
        instruction_victim $registers $victims \
        plic_live_csr $pending $ex] {
        if {[llength $starts] == 0 || [llength $ends] == 0} {
            error "missing actual storage timing endpoints: $family"
        }
        set paths [get_timing_paths -from $starts -to $ends -delay_type max -max_paths 1]
        if {[llength $paths] != 1} { error "missing real storage timing path: $family" }
        set slack [get_property SLACK $paths]
        puts $result "$comma\"[set family]_wns_ns\":$slack"
        set comma ","
        report_timing -from $starts -to $ends -delay_type max -max_paths 5 -nworst 1 \
            -file [file join $folder setup_$family.rpt]
        puts "I1_STORAGE_CHECKPOINT_COMPARE name=$label family=$family wns=$slack checkpoint=$checkpoint"
    }
    puts $result "\}"
    set separator ","
    close_design
}
puts $result "\}"
close $result
puts "I1_STORAGE_REPORT_ONLY_DONE TWO_EXISTING_DCPS NO_SYNTHESIS NO_CONSTRAINT_CHANGES NO_ROUTE"
