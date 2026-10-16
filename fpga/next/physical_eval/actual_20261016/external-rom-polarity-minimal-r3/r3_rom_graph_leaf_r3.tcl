# Versioned diagnostic-only ROM graph export, observed 2026-10-16 topology.
# 58 RAMB36E2 clock pins + 6 selector clock pins; every actual leaf is checked.
# No netlist/constraint mutation. Original r1 package remains immutable.
# Source after r3_common.tcl; configure only with verify_local_rom.py output.
namespace eval rom_leaf_r3 {
    variable contract {}
    proc fail {message} {error "ROM_LEAF_R3: $message"}
    proc one {objects label} {
        if {[llength $objects] != 1} {fail "Expected one $label, got $objects"}
        return [lindex $objects 0]
    }
    proc exact {query name} {
        # Literal filter avoids glob expansion of bus brackets and hierarchy names.
        set escaped [string map [list "\\" "\\\\" "\"" "\\\""] $name]
        set object [one [$query -quiet -hier -filter "NAME == \"$escaped\""] $name]
        if {[get_property NAME $object] ne $name} {fail "Nonexact object $name"}
        return $object
    }
    proc boolean {value label} {
        if {$value in {1 TRUE true 1'b1}} {return 1}
        if {$value in {0 FALSE false 1'b0}} {return 0}
        fail "Unknown boolean $label=$value"
    }
    proc names {objects} {set result {}; foreach o $objects {lappend result [get_property NAME $o]}; return [lsort -unique $result]}
    proc segments {pin} {
        return [names [get_nets -quiet -segments -of_objects $pin]]
    }
    proc configure {value} {
        variable contract
        foreach {key expected} {
            schema rom-leaf-clock-r3
            source_commit 50cb0c5d4b17318904d6cf818ad23829821d5d93
            wrapper_sha256 2ff5598b214b31506231b6de198d49c843a6d897abf77ab8a9d7a65270ca3028
            vendor_dcp_sha256 6f86eef783b3cb795fd4c2c2d99870e0215f4d8d523f883f2e95fbfc624cc0bc
            expected_leaf_clocks 64
            expected_bram_clocks 58
            expected_selector_clocks 6
            local_asset_status PASS_HASHED_ROM_ASSETS_AND_IMAGE
        } {
            if {![dict exists $value $key] || [dict get $value $key] ne $expected} {
                fail "Contract mismatch $key"
            }
        }
        set contract $value
    }
    proc clock_polarity {cell pin ref inversion} {
        # Actual logical pin inversion is the authority (UG912/UG903 2025.1).
        # Empty FDRE cell metadata is observed vendor behavior, never a zero.
        if {"IS_INVERTED" ni [list_property $pin]} {fail "Missing actual pin polarity $pin"}
        set pinraw [get_property IS_INVERTED $pin]
        set pinvalue [boolean $pinraw $pin/IS_INVERTED]
        if {$pinvalue} {fail "Inverted actual leaf clock $pin"}
        if {$inversion ni [list_property $cell]} {fail "Missing secondary cell property $cell/$inversion"}
        set cellraw [get_property $inversion $cell]
        if {$cellraw eq "" && $ref eq "FDRE"} {
            set status unknown_empty_observed_fdre
        } else {
            set cellvalue [boolean $cellraw $cell/$inversion]
            if {$cellvalue != $pinvalue} {fail "Contradictory clock polarity $pin versus $cell/$inversion"}
            set status agrees_with_actual_pin
        }
        return [dict create primary_object $pin primary_property IS_INVERTED primary_raw $pinraw \
            primary_value $pinvalue secondary_object $cell secondary_property $inversion \
            secondary_raw $cellraw secondary_status $status]
    }
    proc audit {} {
        variable contract
        if {$contract eq {}} {fail "Verified local ROM contract not configured"}
        set memory $::V_ROM_ROOT/memory
        set object [exact get_cells $memory]
        if {[get_property REF_NAME $object] ne "blk_mem_gen_0" &&
            [get_property ORIG_REF_NAME $object] ne "blk_mem_gen_0"} {fail "Wrong memory instance"}
        set clock [exact get_pins $::V_ROM_ROOT/clock]
        if {[get_property DIRECTION $clock] ne "IN"} {fail "Wrapper clock direction"}
        set reference [segments $clock]
        if {![llength $reference]} {fail "Disconnected wrapper clock"}
        set cpu [exact get_pins $::V_SOC_ROOT/clock]
        if {[get_property DIRECTION $cpu] ne "IN" || [segments $cpu] ne $reference} {fail "ROM wrapper is not on the actual CPU clock net"}
        set netobjects {}; set nettypes {}
        foreach n $reference {
            set net [exact get_nets $n]
            set type [get_property TYPE $net]
            if {$type ni {SIGNAL GLOBAL_CLOCK}} {fail "Unsupported/constant ROM clock type $n=$type"}
            dict set nettypes $n $type
            lappend netobjects $net
        }
        set drivers [names [get_pins -quiet -leaf -of_objects $netobjects -filter {DIRECTION == OUT}]]
        set ports [names [get_ports -quiet -of_objects $netobjects -filter {DIRECTION == IN}]]
        if {[llength $drivers]+[llength $ports] != 1} {fail "ROM clock has no unique real driver: $drivers $ports"}
        set boundary {}; set disconnected {}
        foreach pin [get_pins -quiet -of_objects $object] {
            set name [get_property NAME $pin]
            if {![string equal -length [string length "$memory/"] "$memory/" $name]} {fail "Foreign boundary $name"}
            set rel [string range $name [string length "$memory/"] end]
            if {[dict exists $boundary $rel]} {fail "Duplicate boundary $rel"}
            set ns [segments $pin]
            if {![llength $ns]} {
                if {$rel ne "clkb"} {fail "Disconnected ROM boundary pin $name"}
                lappend disconnected $rel
            }
            dict set boundary $rel [dict create object $pin direction [get_property DIRECTION $pin] segments $ns]
        }
        set expected {clka clkb ena enb}
        foreach side {a b} {
            for {set i 0} {$i < 15} {incr i} {lappend expected [format {addr%s[%d]} $side $i]}
            for {set i 0} {$i < 32} {incr i} {lappend expected [format {dout%s[%d]} $side $i]}
        }
        if {[lsort [dict keys $boundary]] ne [lsort $expected]} {fail "Missing/extra ROM boundary pin inventory"}
        foreach rel $expected {
            set direction [expr {[string match dout* $rel] ? "OUT" : "IN"}]
            if {[dict get $boundary $rel direction] ne $direction} {fail "Wrong boundary direction $rel"}
        }
        foreach rel {clka clkb} {
            set ns [dict get $boundary $rel segments]
            if {[llength $ns] && $ns ne $reference} {fail "Foreign boundary clock $rel"}
        }
        set cells [get_cells -quiet -hier -filter "NAME =~ $memory/* && IS_PRIMITIVE == 1"]
        if {![llength $cells]} {fail "Missing ROM primitive inventory"}
        set leaves {}; set brams 0; set bramclocks 0; set selectorclocks 0
        foreach cell [lsort -dictionary $cells] {
            set name [get_property NAME $cell]; set ref [get_property REF_NAME $cell]
            if {![boolean [get_property IS_PRIMITIVE $cell] $name]} {fail "Nonprimitive inventory $name"}
            if {$ref eq "RAMB36E2"} {
                set spec {CLKARDCLK IS_CLKARDCLK_INVERTED CLKBWRCLK IS_CLKBWRCLK_INVERTED}; incr brams
            } elseif {$ref in {FDRE FDCE FDSE FDPE}} {
                set spec {C IS_C_INVERTED}
            } elseif {[regexp {^(LUT[1-6]|INV|MUXF[789]|VCC|GND)$} $ref]} {
                set spec {}
            } else {fail "Unsupported ROM primitive $name $ref"}
            set actual {}
            foreach pin [get_pins -quiet -of_objects $cell] {
                if {[boolean [get_property IS_CLOCK $pin] "[get_property NAME $pin].IS_CLOCK"]} {
                    lappend actual [get_property REF_PIN_NAME $pin]
                }
            }
            set required {}; foreach {pin prop} $spec {lappend required $pin}
            if {[lsort $actual] ne [lsort $required]} {fail "Missing/extra actual leaf clock pins on $name: $actual expected $required"}
            foreach {pn inversion} $spec {
                set pin [exact get_pins $name/$pn]
                if {[get_property DIRECTION $pin] ne "IN" ||
                    ![boolean [get_property IS_LEAF $pin] $name/$pn]} {fail "Not an input leaf clock $name/$pn"}
                set polarity [clock_polarity $cell $pin $ref $inversion]
                set ns [segments $pin]
                if {![llength $ns] || $ns ne $reference} {fail "Disconnected/foreign leaf clock $name/$pn"}
                if {[dict exists $leaves $name/$pn]} {fail "Duplicate leaf clock $name/$pn"}
                dict set leaves $name/$pn [dict create ref $ref polarity positive polarity_evidence $polarity segments $ns]
                if {$ref eq "RAMB36E2"} {incr bramclocks} else {incr selectorclocks}
            }
        }
        if {!$brams || $bramclocks != [dict get $contract expected_bram_clocks] ||
            $selectorclocks != [dict get $contract expected_selector_clocks] ||
            [dict size $leaves] != [dict get $contract expected_leaf_clocks]} {
            fail "ROM leaf inventory count [dict size $leaves], BRAM clocks $bramclocks, selector clocks $selectorclocks, BRAM cells $brams"
        }
        return [dict create schema rom-leaf-clock-r3 status PASS_ACTUAL_LEAF_CONNECTIVITY \
            contract $contract memory $memory reference_pin $::V_ROM_ROOT/clock cpu_reference_pin $::V_SOC_ROOT/clock \
            reference_segments $reference reference_net_types $nettypes driver_pins $drivers driver_ports $ports \
            bram_clock_count $bramclocks selector_clock_count $selectorclocks leaf_clock_count [dict size $leaves] \
            boundary $boundary reconciled_boundary $disconnected leaves $leaves]
    }
}
proc r3_assert_rom_graph {} {return [rom_leaf_r3::audit]}
proc r3_rom_actual_dump {path} {
    # Complete audit before emitting a graph or reconciling any clock boundary.
    set audit [r3_assert_rom_graph]
    foreach output [list $path $path.graph.tsv $path.clock-proof.tcldict] {
        if {[file exists $output]} {error "Preserve previous ROM evidence $output"}
    }
    r3_rom_dump $path
    set memory [dict get $audit memory]
    set f [open $path.graph.tsv {WRONLY CREAT EXCL}]
    try {
        set seen {}
        dict for {relative record} [dict get $audit boundary] {
            set ns [dict get $record segments]
            if {![llength $ns]} {
                # Only the existing, disconnected clkb can arrive here; all 64
                # positive-edge leaves and retained clka were proved above.
                if {$relative ne "clkb" || $relative ni [dict get $audit reconciled_boundary]} {error "Unproved reconciliation"}
                set ns [dict get $audit reference_segments]
            }
            set net [lindex $ns 0]
            puts $f "PORT\t$relative\t[dict get $record direction]\t$net"
            if {$net ni $seen} {lappend seen $net; puts $f "NET\t$net\t[get_property TYPE [rom_leaf_r3::exact get_nets $net]]"}
        }
        foreach cell [lsort -dictionary [get_cells -quiet -hier -filter "NAME =~ $memory/* && IS_PRIMITIVE == 1"]] {
            set name [get_property NAME $cell]
            puts $f "CELL\t$name\t[get_property REF_NAME $cell]"
            foreach prop [lsort [list_property $cell]] {
                if {[regexp {^INIT$|^(INIT|INITP)_[0-9A-Fa-f]+$|^READ_WIDTH_[AB]$|^WRITE_WIDTH_[AB]$|^RAM_MODE$|^DO[AB]_REG$|^RAM_EXTENSION_[AB]$} $prop]} {puts $f "PROP\t$name\t$prop\t[get_property $prop $cell]"}
            }
            foreach pin [get_pins -quiet -of_objects $cell] {
                set ns [rom_leaf_r3::segments $pin]
                if {![llength $ns]} {
                    if {[rom_leaf_r3::boolean [get_property IS_CLOCK $pin] $pin]} {error "Clock disconnected after audit $pin"}
                    continue
                }
                set net [lindex $ns 0]
                puts $f "PIN\t$name\t[get_property REF_PIN_NAME $pin]\t[get_property DIRECTION $pin]\t$net"
                if {$net ni $seen} {lappend seen $net; puts $f "NET\t$net\t[get_property TYPE [rom_leaf_r3::exact get_nets $net]]"}
            }
        }
    } finally {close $f}
    set proof [open $path.clock-proof.tcldict {WRONLY CREAT EXCL}]
    puts $proof $audit; close $proof
    return $audit
}
