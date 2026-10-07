# Audit the two board-local async-assert/sync-release reset chains before exceptions.
# Never apply a clock-group exception or cut a synchronizer's D/Q data paths.
proc audit_board_reset_cdc {report_file} {
    set stream [open $report_file w]
    set presets {}
    foreach {prefix clock_name} {reset_pipe_reg clk_out1_clk_wiz_ddr ui_reset_pipe_reg mmcm_clkout0} {
        set shared_preset {}
        for {set i 0} {$i < 3} {incr i} {
            set name [format {%s[%d]} $prefix $i]
            set cell [get_cells -quiet $name]
            if {[llength $cell] != 1 || [get_property REF_NAME $cell] ne "FDPE" ||
                ![get_property ASYNC_REG $cell]} {error "Unaudited reset synchronizer: $name"}
            set cp [get_pins [format {%s/C} $name]]
            set clock [get_clocks -quiet -of_objects $cp]
            if {[llength $clock] != 1 || [get_property NAME $clock] ne $clock_name} {
                error "Reset clock mismatch: $name"
            }
            set pp [get_pins [format {%s/PRE} $name]]
            set pn [get_nets -of_objects $pp]
            if {[llength $pn] != 1} {error "Missing asynchronous preset: $name"}
            set pn_name [get_property NAME $pn]
            if {$i == 0} {set shared_preset $pn_name}
            if {$pn_name ne $shared_preset} {error "Reset stages do not share asynchronous assertion"}
            set dp [get_pins [format {%s/D} $name]]
            set dn [get_nets -segments -of_objects $dp]
            if {$i == 0} {
                set constant [get_nets -of_objects $dp]
                if {[get_property TYPE $constant] ne "GROUND"} {error "Reset stage zero must shift in zero"}
            } else {
                set drivers [get_pins -quiet -leaf -of_objects $dn -filter {DIRECTION == OUT}]
                set expected [format {%s[%d]/Q} $prefix [expr {$i-1}]]
                if {[llength $drivers] != 1 || [get_property NAME $drivers] ne $expected} {
                    error "Reset release chain is not direct Q-to-D: $name ($drivers)"
                }
            }
            if {$i < 2} {
                set qp [get_pins [format {%s/Q} $name]]
                set qn [get_nets -segments -of_objects $qp]
                set loads [get_pins -quiet -leaf -of_objects $qn -filter {DIRECTION == IN}]
                set expected [format {%s[%d]/D} $prefix [expr {$i+1}]]
                if {[llength $loads] != 1 || [get_property NAME $loads] ne $expected} {
                    error "Metastable reset stage has functional fanout: $name ($loads)"
                }
            }
            lappend presets $pp
            puts $stream "$name: FDPE ASYNC_REG=TRUE clock=$clock_name shared PRE=$pn_name"
        }
    }
    if {[llength $presets] != 6} {error "Expected exactly six reset synchronizer PRE pins"}
    puts $stream "PASS: two three-stage asynchronous assertion / synchronous release chains."
    puts $stream "Only these six PRE pins may be excepted; all stage D/Q and functional reset paths remain timed."
    close $stream
    return $presets
}

# CPU reset must consume the synchronized UI reset, never raw MIG calibration/UI reset.
# all_fanin returns launching C pins for sequential startpoints.
proc audit_cpu_reset_gate {report_file} {
    set pin [get_pins -quiet {reset_pipe_reg[0]/PRE}]
    if {[llength $pin] != 1} {error "Missing CPU reset synchronization entry"}
    set sources [lsort [all_fanin -flat -startpoints_only -to $pin]]
    set expected [list {ui_reset_pipe_reg[2]/C}]
    if {$sources ne $expected} {error "CPU reset bypasses synchronized UI reset: $sources"}
    set presets [get_pins {reset_pipe_reg[0]/PRE reset_pipe_reg[1]/PRE reset_pipe_reg[2]/PRE}]
    foreach pp $presets {
        set drivers [get_pins -quiet -leaf -of_objects [get_nets -segments -of_objects $pp] -filter {DIRECTION == OUT}]
        if {[llength $drivers] != 1 || [get_property NAME $drivers] ne {ui_reset_pipe_reg[2]/Q}} {
            error "Combinational logic before CPU reset synchronization: $pp ($drivers)"
        }
    }
    set ui_sources [lsort [all_fanin -flat -startpoints_only -to [get_pins {ui_reset_pipe_reg[0]/PRE}]]]
    set expected_ui [lsort [list button_n sys_rst_n u_clk_wiz/inst/mmcme4_adv_inst/LOCKED \
        u_ddr/inst/div_clk_rst_r1_reg/C u_ddr/inst/u_ddr4_mem_intfc/u_ddr_cal_top/calDone_gated_reg/C]]
    if {$ui_sources ne $expected_ui} {error "UI reset qualification sources differ: $ui_sources"}
    set stream [open $report_file w]
    puts $stream "CPU reset startpoints: $sources"
    puts $stream "UI reset qualification startpoints: $ui_sources"
    puts $stream "PASS: board/UI/calibration/clock-unlock assert the UI chain asynchronously; UI stage 3 directly drives all CPU reset PRE pins."
    puts $stream "No raw MIG calibration/reset bypass; 3-stage CPU release and all CPU data paths unchanged."
    close $stream
}
