# Read-only complete-board CDC facts. No exceptions, placement edits or bit.
# Structural checks are NOT a waiver for report_cdc findings or protocol proof.
if {$argc != 2} {error "Expected ROUTED_DCP FRESH_OUTPUT_DIRECTORY"}
lassign $argv checkpoint output
set checkpoint [file normalize $checkpoint]
set output [file normalize $output]
if {![file exists $checkpoint] || [file exists $output]} {error "Missing checkpoint or non-fresh output"}
file mkdir $output
set_param general.maxThreads 8
open_checkpoint $checkpoint
set facts [open [file join $output structural_facts.txt] w]
puts $facts "CHECKPOINT=$checkpoint"
puts $facts "PART=[get_property PART [current_design]]"

proc native_drivers {pin} {
    return [lsort [get_pins -quiet -leaf -of_objects [get_nets -segments -of_objects $pin] -filter {DIRECTION == OUT}]]
}
proc native_loads {pin} {
    return [lsort [get_pins -quiet -leaf -of_objects [get_nets -segments -of_objects $pin] -filter {DIRECTION == IN}]]
}
proc native_chain {prefix length preset phase_special} {
    global facts
    set shared {}
    set domain {}
    for {set n 0} {$n < $length} {incr n} {
        set name [format {%s[%d]} $prefix $n]
        # Vivado resolves literal indexed names before wildcard patterns.
        # Backslash-escaping [] instead returns no cell in this API.
        set cell [get_cells -quiet $name]
        if {[llength $cell]!=1 || [get_property NAME $cell] ne $name || ![get_property ASYNC_REG $cell]} {
            error "Missing/unmarked synchronizer $name"
        }
        set clk [get_clocks -quiet -of_objects [get_pins $cell/C]]
        if {[llength $clk]!=1} {error "Missing synchronizer clock $name"}
        if {$n==0} {set domain $clk}
        if {$clk ne $domain} {error "Chain crosses clocks internally $prefix"}
        set dp [get_pins $cell/D]
        if {$n==0 && $preset} {
            if {[get_property TYPE [get_nets -of_objects $dp]] ne "GROUND"} {error "Reset chain first D is not zero $name"}
        } elseif {$n>0} {
            set expected [format {%s[%d]/Q} $prefix [expr {$n-1}]]
            if {[native_drivers $dp] ne [list $expected]} {error "Indirect synchronizer stage $name"}
        }
        if {$preset} {
            set pin [get_pins $cell/PRE]
            if {[llength $pin]!=1} {error "Reset chain missing PRE $name"}
            set net [get_nets -of_objects $pin]
            if {$n==0} {set shared $net}
            if {$net ne $shared} {error "Reset assertion not common $prefix"}
        }
        if {$n<$length-1} {
            set expected [list [format {%s[%d]/D} $prefix [expr {$n+1}]]]
            if {$phase_special && $n==1} {
                lappend expected centered_tx_clock.clock_dut/raw_div/CLR
                if {[llength [get_cells -quiet centered_tx_clock.clock_dut/quarter_div]]} {
                    lappend expected centered_tx_clock.clock_dut/quarter_div/CLR
                } else {lappend expected centered_tx_clock.clock_dut/pad_div/CLR}
            }
            if {[native_loads [get_pins $cell/Q]] ne [lsort $expected]} {error "Unreviewed intermediate stage fanout $name"}
        }
        puts $facts "CHAIN $name CLOCK=$clk D_DRIVERS=[native_drivers $dp] Q_LOADS=[native_loads [get_pins $cell/Q]]"
    }
    puts $facts "CHAIN_DIRECT_PASS prefix=$prefix stages=$length async_assert=$preset"
}

# Explicit board and common-release chains. Do not exclude functional reset
# sinks, CE pins or any data path to make these assertions pass.
foreach prefix {
    ui_reset_pipe_reg reset_pipe_reg delay_reset_pipe_reg phy_reset_pipe_reg rx_reset_pipe_reg
    software_phy.tx_release/tx_reset_pipe_reg
} {native_chain $prefix 3 1 0}
if {[llength [get_cells -quiet centered_tx_clock.clock_dut/quarter_div]]} {
    # Explicitly selected common word epoch, not an unreviewed missing chain.
    if {[llength [get_cells -quiet {software_phy.tx_release/tx_forward_reset_pipe_reg[*]}]]} {error "Unexpected duplicate quarter-TX reset chain"}
    # A single physical net has different names at hierarchy boundaries.
    # Require its actual sole leaf driver, not equality of segment names.
    set wordReset [list {software_phy.tx_release/tx_reset_pipe_reg[2]/Q}]
    set wordSinks {u_rgmii/tx_clock_ddr/RST u_rgmii/tx_control_ddr/RST u_rgmii/quarter_tx_boundary.phase_high_reg/PRE}
    for {set lane 0} {$lane<4} {incr lane} {
        lappend wordSinks [format {u_rgmii/lanes[%d].tx_ddr/RST} $lane]
    }
    foreach pin $wordSinks {
        set endpoint [get_pins -quiet $pin]
        if {[llength $endpoint]!=1 || [native_drivers $endpoint] ne $wordReset} {
            error "Quarter TX reset does not share word epoch: $pin"
        }
        puts $facts "QUARTER_WORD_RESET $pin DRIVER=$wordReset"
    }
    puts $facts "QUARTER_TX_COMMON_WORD_RESET_EPOCH_PASS"
} else {native_chain software_phy.tx_release/tx_forward_reset_pipe_reg 3 1 0}
native_chain centered_tx_clock.clock_dut/phase_reset_reg 3 1 1
set reset_count 0
foreach module [get_cells -quiet -hier -filter {REF_NAME =~ CdcResetRelease*}] {
    native_chain "$module/release_0_reg" 3 1 0
    incr reset_count
}
if {$reset_count<20} {error "Incomplete native common-reset boundary review"}
puts $facts "COMMON_RELEASE_MODULES=$reset_count"
set level_count 0
foreach module [get_cells -quiet -hier -filter {REF_NAME =~ CdcLevel*}] {
    native_chain "$module/stages_reg" 2 0 0
    set first [get_pins -quiet [format {%s/stages_reg[0]/D} $module]]
    puts $facts "LEVEL_LAUNCH $module STARTS=[all_fanin -flat -startpoints_only -to $first]"
    incr level_count
}
if {$level_count<20} {error "Incomplete native level boundary review"}
puts $facts "LEVEL_MODULES=$level_count"

foreach name {txConfig rxConfig txStats rxStats} {
    set hier u_soc/nativeBank/gmac/$name/mailbox
    set captures [get_pins -of_objects [get_cells -quiet "$hier/captured_reg*"] -filter {REF_PIN_NAME == D}]
    set held [get_cells -quiet "$hier/held_reg*"]
    if {[llength $captures]==0 || [llength $held]==0} {error "Missing native atomic payload $hier"}
    set paths [get_timing_paths -quiet -from $held -to $captures -delay_type max -max_paths 1000 -nworst 1]
    if {[llength $paths]!=[llength $captures]} {error "Held payload capture coverage incomplete $hier"}
    report_timing -from $held -to $captures -delay_type max -max_paths 1000 -nworst 1 -input_pins -file [file join $output ${name}_held_payload.rpt]
    foreach path $paths {
        puts $facts "HELD_PATH $name TO=[get_property ENDPOINT_PIN $path] REQUIREMENT=[get_property REQUIREMENT $path] SLACK=[get_property SLACK $path]"
    }
    foreach suffix {requestToggle_reg ackToggle_reg valid_reg token_reg} {
        set reg [get_cells -quiet $hier/$suffix]
        if {[llength $reg]!=1} {error "Missing atomic ownership register $hier/$suffix"}
        puts $facts "MAILBOX_OWNER $reg D_STARTS=[all_fanin -flat -startpoints_only -to [get_pins $reg/D]]"
    }
    foreach reg [get_cells -quiet "$hier/captured_reg*"] {
        puts $facts "MAILBOX_CAPTURE $reg D_STARTS=[all_fanin -flat -startpoints_only -to [get_pins $reg/D]] CE_STARTS=[all_fanin -flat -startpoints_only -to [get_pins $reg/CE]]"
    }
}
foreach name {txFifo rxFifo} {
    set hier u_soc/nativeBank/gmac/$name/fifo
    foreach prefix {readGraySync_stage writeGraySync_stage} {
        for {set bit 0} {$bit<5} {incr bit} {
            set s0 [get_cells -quiet [format {%s/%s0_reg[%d]} $hier $prefix $bit]]
            if {[llength $s0]!=1 || ![get_property ASYNC_REG $s0]} {
                error "Missing Gray first-stage synchronizer $hier/$prefix/$bit"
            }
            # Chisel names the returned second stage readGraySync/writeGraySync,
            # not *_stage1. Trace its actual sole D load instead of guessing.
            set loads [native_loads [get_pins $s0/Q]]
            if {[llength $loads]!=1 || [get_property REF_PIN_NAME $loads] ne "D"} {
                error "Gray first-stage functional/branched fanout $s0"
            }
            set s1 [get_cells -of_objects $loads]
            if {[llength $s1]!=1 || ![get_property ASYNC_REG $s1] || ![get_property IS_SEQUENTIAL $s1]} {
                error "Missing Gray two-stage synchronizer $hier/$prefix/$bit"
            }
            if {[get_clocks -of_objects [get_pins $s0/C]] ne [get_clocks -of_objects [get_pins $s1/C]]} {
                error "Gray stages do not use one destination clock $s0"
            }
            if {[native_drivers [get_pins $s1/D]] ne [list $s0/Q] || [native_loads [get_pins $s0/Q]] ne [list $s1/D]} {
                error "Gray first stage has indirect/functional fanout $s0"
            }
            puts $facts "GRAY_STAGE $s0 TO=$s1 LAUNCH=[native_drivers [get_pins $s0/D]]"
        }
    }
    set starts [get_pins -quiet -hier -filter "NAME =~ $hier/storage_ext/* && (REF_PIN_NAME == CLK || REF_PIN_NAME == WCLK)"]
    set captures [get_pins -of_objects [get_cells -quiet "$hier/output_0_reg*"] -filter {REF_PIN_NAME == D}]
    if {[llength $starts]==0 || [llength $captures]!=38} {error "FIFO physical payload mapping changed $hier"}
    set paths [get_timing_paths -quiet -from $starts -to $captures -delay_type max -max_paths 100 -nworst 1]
    if {[llength $paths]!=38} {error "FIFO physical payload has untimed captures $hier"}
    report_timing -from $starts -to $captures -delay_type max -max_paths 100 -nworst 1 -input_pins -file [file join $output ${name}_ram_payload.rpt]
    puts $facts "FIFO_PAYLOAD_PATHS $name COUNT=[llength $paths]"
}
foreach leaf {RIU_ADDR RIU_WR_DATA} {
    set exact [get_pins -quiet u_ddr/inst/*/*/*/*/*/*.u_xiphy_control/xiphy_control/${leaf}*]
    set expanded [get_pins -quiet -hier -filter "NAME =~ u_ddr/* && REF_PIN_NAME =~ ${leaf}*"]
    puts $facts "MIG_VENDOR_TARGET $leaf EXACT=[llength $exact] EXPANDED=[llength $expanded]"
    if {[llength $exact]==0 || [lsort $exact] ne [lsort $expanded]} {error "MIG target-set mismatch requires review $leaf"}
}
puts $facts "READ_ONLY_STRUCTURAL_FACTS_COMPLETE_NOT_CDC_SIGNOFF"
close $facts
close_design
puts "NATIVE_CDC_FACTS_COMPLETE NO_CONSTRAINTS_CHANGED NO_BIT"
