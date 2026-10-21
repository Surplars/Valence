# Tcl-only lookup contract/query-count evidence; not native performance timing.
source [file join [file dirname [info script]] common_cdc.tcl]
source [file join [file dirname [info script]] exact_object_cache.tcl]
proc assert {condition why} {if {![uplevel 1 [list expr $condition]]} {error $why}}
set ::properties {};set ::cellObjects {};set ::pinObjects {};set ::names {}
for {set i 0} {$i<38} {incr i} {
    set c C$i;set p P$i;set n [format {root/capture_reg[%d]} $i]
    lappend ::cellObjects $c;lappend ::pinObjects $p;lappend ::names $n/D
    dict set ::properties $c [dict create NAME $n CLASS cell]
    dict set ::properties $p [dict create NAME $n/D CLASS pin]
}
set ::design design1
set ::failOpt 0
namespace eval valence_fifo_payload {}
proc valence_fifo_payload::one args {error ORIGINAL_NOT_REPLACED}
proc valence_fifo_payload::objects args {error ORIGINAL_NOT_REPLACED}
set ::globalQueries 0;set ::localQueries 0;set ::duplicate 0;set ::wrongType 0;set ::stale 0
proc current_design args {return $::design}
proc get_property {key objects} {
    set result {}
    foreach o $objects {
        if {$o eq $::design} {lappend result same_design_name;continue}
        if {$::stale && $o eq {P0}} {lappend result {};continue}
        if {$::wrongType && $o eq {P0} && $key eq {CLASS}} {lappend result cell;continue}
        lappend result [dict get $::properties $o $key]
    }
    if {[llength $objects]==1} {return [lindex $result 0]}
    return $result
}
proc get_cells args {
    incr ::globalQueries
    if {$::duplicate} {return [concat $::cellObjects C0]}
    return $::cellObjects
}
proc get_pins args {
    set pos [lsearch -exact $args -of_objects]
    if {$pos>=0} {
        incr ::localQueries
        set owner [lindex $args [expr {$pos+1}]]
        return P[string range $owner 1 end]
    }
    incr ::globalQueries
    set patterns [lindex $args end];set found {}
    foreach p $::pinObjects {
        foreach pattern $patterns {
            if {[regexp $pattern [dict get $::properties $p NAME]]} {lappend found $p;break}
        }
    }
    return $found
}
proc opt_design args {if {$::failOpt} {error MUTATION_FAILED}}
proc close_design args {set ::design {}}
proc open_checkpoint args {set ::design design1}
# Same repeated exact 38-pin requests: baseline uses a full hierarchy scan each.
for {set i 0} {$i<20} {incr i} {common_cdc::objects get_pins $::names}
assert {$::globalQueries==20} {baseline query accounting changed}
set before $::globalQueries
common_exact_cache::enable
for {set i 0} {$i<20} {incr i} {common_cdc::objects get_pins $::names}
assert {$::globalQueries-$before==1 && $::localQueries==38} {cache did not bound queries}
assert {[llength [valence_fifo_payload::objects get_pins $::names]]==38} {FIFO helper not cached}
assert {[valence_fifo_payload::one get_pins {root/capture_reg[0]/D}] eq {P0}} {FIFO one helper changed}
puts "EXACT_CACHE_QUERY_EVIDENCE repeated_38_pin_requests=20 baseline_global_scans=20 cached_global_scans=1 owner_local_queries=38 subsequent_global_scans=0"
assert {[common_cdc::bank root/capture_reg 38] eq [lmap n $::names {file dirname $n}]} {bank ordering changed}
assert {[catch {common_cdc::one get_pins {root/capture_reg[0]/MISSING}} why]} {missing endpoint accepted}
assert {[string match {*missing exact pin*} $why]} {wrong missing diagnostic}
set ::wrongType 1
assert {[catch {common_cdc::one get_pins {root/capture_reg[0]/D}} why]} {wrong object type accepted}
assert {[string match {*wrong object type*} $why]} {wrong type diagnostic}
set ::wrongType 0;set ::stale 1
assert {[catch {common_cdc::one get_pins {root/capture_reg[0]/D}} why]} {stale object accepted}
set ::stale 0
common_exact_cache::invalidate
assert {[catch {common_cdc::one get_cells {root/capture_reg[0]}} why]} {invalidated generation accepted}
assert {[string match {*stale/inactive*} $why]} {wrong stale generation diagnostic}
set ::duplicate 1
assert {[catch {common_exact_cache::rebuild} why]} {duplicate names accepted}
set ::duplicate 0
common_exact_cache::rebuild
set generation $::common_exact_cache::generation
opt_design
assert {$::common_exact_cache::generation>$generation && $::common_exact_cache::valid} {opt did not rebuild generation}
set ::failOpt 1
assert {[catch {opt_design} why]} {failed mutation expected}
assert {!$::common_exact_cache::valid} {failed mutation reused stale cache}
set ::failOpt 0
common_exact_cache::rebuild
close_design
assert {!$::common_exact_cache::valid} {close did not invalidate}
open_checkpoint other.dcp
assert {$::common_exact_cache::valid} {open did not rebuild}
set ::design design2
assert {[catch {common_cdc::one get_cells {root/capture_reg[0]}} why]} {changed design identity accepted}
set ::design design1
# A freshly sourced original helper must be intercepted before its next call.
source [file join [file dirname [info script]] common_cdc.tcl]
assert {[string match {*common_exact_cache::objects*} [info body common_cdc::objects]]} {source redefinition lost cache wrapper}
puts EXACT_CACHE_MISSING_DUPLICATE_TYPE_STALE_LIFECYCLE_AND_SOURCE_GUARDS_PASS
