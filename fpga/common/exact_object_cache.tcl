# Lookup-only recovery overlay. No clocks, exceptions, budgets or proof results
# are cached. Do not source the old recovery mapper to enable this helper.
namespace eval common_exact_cache {
    variable valid 0
    variable generation 0
    variable cells {}
    variable pins {}
    variable banks {}
    variable owners {}
    variable design {}
    variable traces 0
}
proc common_exact_cache::invalidate {args} {
    variable valid; variable generation
    set valid 0; incr generation
}
proc common_exact_cache::validate {objects expected class} {
    if {[llength $objects]!=[llength $expected]} {error "EXACT_CACHE missing/duplicate $class objects"}
    set names [get_property NAME $objects]
    set classes [get_property CLASS $objects]
    if {[llength $names]!=[llength $expected] || [llength $classes]!=[llength $expected] ||
        [lsort $names] ne [lsort $expected] || [llength [lsort -unique $names]]!=[llength $names]} {
        error "EXACT_CACHE missing/duplicate/stale NAME collection"
    }
    foreach type $classes {if {$type ne $class} {error "EXACT_CACHE wrong object type: $type expected $class"}}
}
proc common_exact_cache::identity {} {
    set d [current_design -quiet]
    if {[llength $d]!=1} {error "EXACT_CACHE requires one open design"}
    return [list $d [get_property NAME $d]]
}
proc common_exact_cache::rebuild {} {
    variable valid; variable cells; variable pins; variable banks; variable owners; variable design
    invalidate
    set cells {};set pins {};set banks {};set owners {}
    set design [identity]
    # The only whole-design hierarchy query in a cache generation.
    set all [get_cells -quiet -hierarchical]
    if {![llength $all]} {error "EXACT_CACHE open design has no cells"}
    set names [get_property NAME $all]
    validate $all $names cell
    foreach object $all name $names {
        dict set cells $name $object
        if {[regexp {^(.*)\[[0-9]+\]$} $name -> prefix]} {dict lappend banks $prefix $name}
    }
    set valid 1
    puts "EXACT_CACHE_REBUILT generation=$::common_exact_cache::generation cells=[dict size $cells] LOOKUPS_ONLY_NO_PROOF_CACHING"
}
proc common_exact_cache::guard {} {
    variable valid; variable design
    if {!$valid || [identity] ne $design} {error "EXACT_CACHE stale/inactive design generation; rebuild required"}
}
proc common_exact_cache::objects {kind names} {
    variable cells;variable pins;variable owners
    guard
    set expected [lsort -unique $names]
    if {![llength $expected]} {error "EXACT_CACHE empty exact collection"}
    if {$kind ni {get_cells get_pins}} {error "EXACT_CACHE unsupported object kind $kind"}
    set found {}
    foreach name $expected {
        if {$kind eq {get_cells}} {
            if {![dict exists $cells $name]} {error "EXACT_CACHE missing exact cell $name"}
            lappend found [dict get $cells $name]
        } else {
            set slash [string last / $name]
            if {$slash<1} {error "EXACT_CACHE invalid full pin name $name"}
            set owner [string range $name 0 [expr {$slash-1}]]
            if {![dict exists $cells $owner]} {error "EXACT_CACHE missing pin owner $owner"}
            if {![dict exists $owners $owner]} {
                set c [dict get $cells $owner]
                validate [list $c] [list $owner] cell
                # One bounded owner-local query, no global regexp/hierarchy scan.
                set local [get_pins -quiet -of_objects $c]
                set localNames [get_property NAME $local]
                validate $local $localNames pin
                foreach p $local n $localNames {
                    if {[file dirname $n] ne $owner} {error "EXACT_CACHE wrong pin owner $n"}
                    if {[dict exists $pins $n]} {error "EXACT_CACHE duplicate cached pin $n"}
                    dict set pins $n $p
                }
                dict set owners $owner 1
            }
            if {![dict exists $pins $name]} {error "EXACT_CACHE missing exact pin $name"}
            lappend found [dict get $pins $name]
        }
    }
    validate $found $expected [expr {$kind eq {get_cells} ? {cell} : {pin}}]
    return $found
}
proc common_exact_cache::one {kind name} {
    set found [objects $kind [list $name]]
    if {[llength $found]!=1} {error "EXACT_CACHE ambiguous exact object $name"}
    return [lindex $found 0]
}
proc common_exact_cache::bank {prefix width} {
    variable banks
    guard
    set expected {};for {set i 0} {$i<$width} {incr i} {lappend expected [format {%s[%d]} $prefix $i]}
    set actual {};if {[dict exists $banks $prefix]} {set actual [dict get $banks $prefix]}
    if {[lsort $actual] ne [lsort $expected]} {error "COMMON_CDC bank shape changed: $prefix expected=$width found=$actual"}
    objects get_cells $expected
    return $expected
}
proc common_exact_cache::install {} {
    # Sources may redefine original helpers. Install only these lookup APIs;
    # clocks, connectivity, topology, constants and timing proofs stay original.
    foreach ns {::common_cdc ::valence_fifo_payload} {
        foreach name {one objects} {
            if {[llength [info commands ${ns}::$name]]} {
                proc ${ns}::$name {kind names} [format {return [::common_exact_cache::%s $kind $names]} $name]
            }
        }
    }
    if {[llength [info commands ::common_cdc::bank]]} {
        proc ::common_cdc::bank {prefix width} {return [::common_exact_cache::bank $prefix $width]}
    }
}
proc common_exact_cache::after_source {command code result op} {
    if {$code==0} {install}
}
proc common_exact_cache::after_mutation {command code result op} {
    if {$code==0 && [llength [current_design -quiet]]==1} {rebuild;install}
}
proc common_exact_cache::enable {} {
    variable traces
    if {!$traces} {
        # Invalidate BEFORE mutation, including failed mutations. Never reuse
        # handles from a previous open/opt design even if its name is unchanged.
        foreach command {open_checkpoint open_run open_design close_design close_project opt_design synth_design link_design read_checkpoint place_design phys_opt_design route_design update_design read_edif} {
            if {[llength [info commands ::$command]]} {
                trace add execution ::$command enter ::common_exact_cache::invalidate
                if {$command ni {close_design close_project}} {
                    trace add execution ::$command leave ::common_exact_cache::after_mutation
                }
            }
        }
        trace add execution ::source leave ::common_exact_cache::after_source
        set traces 1
    }
    rebuild
    install
}
