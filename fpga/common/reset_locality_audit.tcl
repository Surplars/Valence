# Read-only, exact-endpoint reset topology classification. Source common_cdc.tcl
# first. Nothing runs when this file is sourced; no timing exception or waiver is
# emitted. This does NOT establish recovery/removal timing, CDC safety, or a
# complete design-wide inventory. The caller must supply the reviewed native
# endpoint list; names/counts are never guessed from a CDC summary.
#
# reset_locality::audit release_specs local_sources endpoints
#   release_specs: dict final_Q -> dict with exactly these fields:
#     stages        three exact FDPE cell names in shift order
#     clock         expected local release clock name
#     assert_source exact registered, positive-asserting source Q pin
#     assert_clock  expected clock name of that source register
#   local_sources: dict exact downstream CLR/PRE pin -> required release final_Q
#   endpoints:     nonempty, duplicate-free list of exact reset-control pin names
#
# Only the explicitly named three-stage release PREs can be classified as
# ASYNC_ASSERTION_LOCAL_RELEASE. Other FDCE/CLR and FDPE/PRE controls, including
# ASYNC_REG synchronizer FFs, require their own local_sources entry, a validated
# release chain, correct clock, and positive assertion polarity. Only direct
# wiring and at most seven semantically checked LUT1 buffers/inverters are
# supported; longer/cyclic traces remain UNREVIEWED. Vendor
# RSTs, combinational reset qualification, and every unproved case remain
# UNREVIEWED. Constant/optimized-away reset controls are not implicitly accepted.
namespace eval reset_locality {}

proc reset_locality::require {condition reason} {
    if {![uplevel 1 [list expr $condition]]} {error "RESET_LOCALITY $reason"}
}
proc reset_locality::boolean {value object} {
    if {$value in {0 FALSE false}} {return 0}
    if {$value in {1 TRUE true}} {return 1}
    error "RESET_LOCALITY unknown boolean at $object: $value"
}
proc reset_locality::pin {name direction refpin} {
    set p [common_cdc::one get_pins $name]
    require {[get_property DIRECTION $p] eq $direction} "wrong pin direction $name"
    require {[get_property REF_PIN_NAME $p] eq $refpin} "wrong pin kind $name"
    return $p
}
proc reset_locality::registered_source {source expected_clock} {
    set p [pin $source OUT Q]
    set cells [get_cells -quiet -of_objects $p]
    require {[llength $cells] == 1} "missing/ambiguous source cell $source"
    set name [get_property NAME $cells]
    require {$source eq "$name/Q"} "nonexact source Q $source"
    require {[get_property REF_NAME $cells] in {FDCE FDPE FDRE FDSE}} "unsupported reset source $source"
    common_cdc::ff $name $expected_clock
}
proc reset_locality::control_source {control expected_source} {
    # Bound the traversal and reject cycles. Unsupported LUT INITs, LUT2+,
    # multiple drivers and source polarity changes all fail closed.
    set p [common_cdc::one get_pins $control]
    set inverted [boolean [get_property IS_INVERTED $p] $control]
    set parity 0; set current $control; set seen {}
    for {set depth 0} {$depth < 8} {incr depth} {
        require {![dict exists $seen $current]} "cyclic reset logic $control"
        dict set seen $current 1
        set drivers [common_cdc::drivers $current]
        require {[llength $drivers] == 1} "missing/ambiguous reset driver $current"
        set source [lindex $drivers 0]
        if {$source eq $expected_source} {
            require {$parity == $inverted} "wrong assertion polarity $control"
            return $source
        }
        set output [common_cdc::one get_pins $source]
        set cells [get_cells -quiet -of_objects $output]
        require {[llength $cells] == 1} "missing reset driver cell $source"
        require {[get_property REF_NAME $cells] eq "LUT1" &&
            [get_property REF_PIN_NAME $output] eq "O" &&
            [get_property DIRECTION $output] eq "OUT"} "unreviewed reset logic/source $control: $source"
        set init [string tolower [get_property INIT $cells]]
        if {$init in {2'h1 2'b01 1 0x1}} {
            set parity [expr {$parity ^ 1}]
        } elseif {$init ni {2'h2 2'b10 2 0x2}} {
            error "RESET_LOCALITY unreviewed LUT1 function $source: $init"
        }
        set current [get_property NAME $cells]/I0
        pin $current IN I0
    }
    error "RESET_LOCALITY reset trace depth exceeded $control"
}
proc reset_locality::release {final spec} {
    set stages [dict get $spec stages]
    set clock [dict get $spec clock]
    set source [dict get $spec assert_source]
    registered_source $source [dict get $spec assert_clock]
    foreach cell $stages {
        require {$source ne "$cell/Q"} "self-asserting release $final"
    }
    foreach cell $stages {
        common_cdc::ff $cell $clock 1
        set c [common_cdc::one get_cells $cell]
        require {[get_property REF_NAME $c] eq "FDPE"} "release must be FDPE $cell"
        require {[string tolower [get_property INIT $c]] in {1 1'b1 1'h1 0x1}} "release INIT must be one $cell"
        pin $cell/Q OUT Q
        # IS_INVERTED is a PIN-object property (UG912), not an invented
        # IS_CE_INVERTED FDPE attribute. Missing/unknown values fail closed.
        set ce [pin $cell/CE IN CE]
        require {![boolean [get_property IS_INVERTED $ce] $cell/CE]} "inverted release enable $cell"
        set d [pin $cell/D IN D]
        require {![boolean [get_property IS_INVERTED $d] $cell/D]} "inverted release data $cell"
        pin $cell/PRE IN PRE
        control_source $cell/PRE $source
    }
    common_cdc::constant [lindex $stages 0]/D 0
    for {set i 1} {$i < 3} {incr i} {
        set previous [lindex $stages [expr {$i - 1}]]
        set next [lindex $stages $i]
        require {[common_cdc::drivers $next/D] eq [list $previous/Q]} "non-direct release interstage $next"
        require {[common_cdc::loads $previous/Q] eq [list $next/D]} "early release stage has extra/missing fanout $previous"
    }
    return [dict create classification RELEASE_TOPOLOGY_VERIFIED source $source clock $clock final $final]
}
proc reset_locality::endpoint {endpoint releases checked membership local_sources} {
    set p [common_cdc::one get_pins $endpoint]
    set cells [get_cells -quiet -of_objects $p]
    require {[llength $cells] == 1} "missing/ambiguous endpoint cell $endpoint"
    set cell [get_property NAME $cells]
    set ref [get_property REF_NAME $cells]
    set control [get_property REF_PIN_NAME $p]
    require {$endpoint eq "$cell/$control" && [get_property DIRECTION $p] eq "IN"} "nonexact reset endpoint $endpoint"
    require {($ref eq "FDCE" && $control eq "CLR") ||
        ($ref eq "FDPE" && $control eq "PRE")} "unsupported reset endpoint $endpoint ($ref/$control)"
    if {[dict exists $membership $endpoint]} {
        set final [dict get $membership $endpoint]
        require {![dict exists $local_sources $endpoint]} "release PRE mislabeled as downstream control $endpoint"
        set kind ASYNC_ASSERTION_LOCAL_RELEASE
    } else {
        require {[dict exists $local_sources $endpoint]} "missing exact local source contract $endpoint"
        set final [dict get $local_sources $endpoint]
        set kind LOCAL_RELEASE_CONTROL
    }
    set chain [dict get $checked $final]
    if {[dict get $chain classification] ne "RELEASE_TOPOLOGY_VERIFIED"} {
        error "RESET_LOCALITY unproved release $final: [dict get $chain reason]"
    }
    set clock [dict get $releases $final clock]
    # ASYNC_REG never bypasses these checks for functional/synchronizer controls.
    common_cdc::ff $cell $clock
    if {$kind eq "LOCAL_RELEASE_CONTROL"} {control_source $endpoint $final}
    set source [expr {$kind eq "LOCAL_RELEASE_CONTROL" ? $final : [dict get $releases $final assert_source]}]
    return [dict create endpoint $endpoint classification $kind source $source release $final clock $clock \
        async_reg [get_property ASYNC_REG $cells]]
}
proc reset_locality::audit {releases local_sources endpoints} {
    # Malformed caller contracts are fatal, rather than silently discarding
    # duplicate inventory entries, extra fields or conflicting release owners.
    require {[llength $endpoints] > 0} "empty exact endpoint inventory"
    require {[llength $endpoints] == [llength [lsort -unique $endpoints]]} "duplicate endpoint inventory"
    set membership {}; set owners {}
    dict for {final spec} $releases {
        require {[lsort [dict keys $spec]] eq {assert_clock assert_source clock stages}} "invalid release fields $final"
        set stages [dict get $spec stages]
        require {[llength $stages] == 3 && [llength [lsort -unique $stages]] == 3} "release must have three distinct ordered stages $final"
        require {$final eq "[lindex $stages 2]/Q"} "release final Q differs from third stage $final"
        foreach field {clock assert_source assert_clock} {
            require {[dict get $spec $field] ne ""} "empty $field for $final"
        }
        foreach cell $stages {
            require {![dict exists $owners $cell]} "overlapping release stage $cell"
            dict set owners $cell $final
            dict set membership $cell/PRE $final
        }
    }
    dict for {endpoint final} $local_sources {
        require {[lsearch -exact $endpoints $endpoint] >= 0} "local source contract outside endpoint inventory $endpoint"
        require {[dict exists $releases $final]} "unknown required release $final for $endpoint"
    }
    set checked {}; set unreviewed_releases 0
    dict for {final spec} $releases {
        if {[catch {release $final $spec} result]} {
            set result [dict create classification UNREVIEWED reason $result]
            incr unreviewed_releases
        }
        dict set checked $final $result
    }
    set rows {}; set unreviewed 0
    foreach endpoint $endpoints {
        if {[catch {endpoint $endpoint $releases $checked $membership $local_sources} result]} {
            set result [dict create endpoint $endpoint classification UNREVIEWED reason $result]
            incr unreviewed
        }
        lappend rows $result
    }
    return [dict create scope EXACT_CALLER_ENDPOINTS_ONLY timing UNCHECKED waiver NONE \
        releases $checked unreviewed_release_count $unreviewed_releases rows $rows \
        endpoint_count [llength $endpoints] unreviewed_count $unreviewed]
}
