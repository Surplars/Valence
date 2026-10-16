# External read-only Vivado2025.1 adapter. No property values are fabricated.
# Keep the reviewed r2 gate unchanged; normalize actual inversion using the
# primitive input pin, rejecting empty/unknown pin values and disagreements.
if {![llength [info commands ::rom_leaf_r2::exact]] || ![llength [info commands ::rom_leaf_r2::boolean]]} {error {Load the reviewed ROM r2 gate first}}
namespace eval rom_live_r7 {
    variable objects {}
    variable hits 0
    variable misses 0
    proc index {kind values} {
        variable objects
        foreach object $values {
            set name [get_property NAME $object]
            if {$name eq {}} {error {Actual object lacks NAME}}
            dict set objects $kind $name $object
        }
    }
    proc rebuild {} {
        variable objects;variable hits;variable misses
        set objects {};set hits 0;set misses 0
        set cells [get_cells -quiet -hier -filter "NAME =~ $::V_ROM_ROOT/memory/*"]
        lappend cells {*}[get_cells -quiet $::V_ROM_ROOT/memory]
        index get_cells $cells
        set pins [get_pins -quiet -of_objects $cells]
        lappend pins {*}[get_pins -quiet $::V_ROM_ROOT/clock] {*}[get_pins -quiet $::V_SOC_ROOT/clock]
        index get_pins $pins
        index get_nets [get_nets -quiet -segments -of_objects $pins]
        puts "ROM_LIVE_R7_FRESH_OBJECT_INDEX nets=[dict size [dict get $objects get_nets]] pins=[dict size [dict get $objects get_pins]]"
    }
    proc exact {query name} {
        variable objects;variable hits;variable misses
        if {[dict exists $objects $query $name]} {
            set object [dict get $objects $query $name]
            if {[get_property NAME $object] ne $name} {error "Actual cached object identity changed: $name"}
            incr hits
            return $object
        }
        incr misses
        return [::rom_leaf_r2::exact_original_r7 $query $name]
    }
    proc boolean {value label} {
        if {[regexp {^(.*)/(IS_C_INVERTED|IS_CLKARDCLK_INVERTED|IS_CLKBWRCLK_INVERTED)$} $label ignored cellName property]} {
            set cell [::rom_leaf_r2::exact get_cells $cellName]
            set ref [get_property REF_NAME $cell]
            if {$property eq {IS_C_INVERTED}} {
                if {$ref ni {FDRE FDCE FDSE FDPE}} {error "Unsupported selector primitive inversion semantics $cellName $ref"}
                set pn C
            } else {
                if {$ref ne {RAMB36E2}} {error "Unsupported BRAM inversion semantics $cellName $ref"}
                set pn [expr {$property eq {IS_CLKARDCLK_INVERTED} ? {CLKARDCLK} : {CLKBWRCLK}}]
            }
            set pin [::rom_leaf_r2::exact get_pins $cellName/$pn]
            if {{IS_INVERTED} ni [list_property $pin]} {error "Missing actual clock pin inversion property $pin"}
            set observed [::rom_leaf_r2::boolean_original_r7 [get_property IS_INVERTED $pin] "$pin.IS_INVERTED"]
            if {$value ne {}} {
                set parameter [::rom_leaf_r2::boolean_original_r7 $value $label]
                if {$parameter!=$observed} {error "Cell/pin inversion disagreement $label value=$value pin=$observed"}
            } elseif {$property ne {IS_C_INVERTED}} {error "Missing BRAM cell inversion property $label"}
            return $observed
        }
        return [::rom_leaf_r2::boolean_original_r7 $value $label]
    }
}
rename ::rom_leaf_r2::exact ::rom_leaf_r2::exact_original_r7
proc ::rom_leaf_r2::exact {query name} {return [::rom_live_r7::exact $query $name]}
rename ::rom_leaf_r2::boolean ::rom_leaf_r2::boolean_original_r7
proc ::rom_leaf_r2::boolean {value label} {return [::rom_live_r7::boolean $value $label]}
