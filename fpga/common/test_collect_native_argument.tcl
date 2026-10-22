# Plain Tcl regression for original argument identity and scalar/list semantics.
# This detects reconstruction, not Vivado native handle qualification.
source [file join [file dirname [info script]] common_collect_session.tcl]
proc pointer {value} {
    if {![regexp {object pointer at ([^, ]+)} [tcl::unsupported::representation $value] -> p]} {error "No Tcl object pointer"}
    return $p
}
set expected {}; set calls 0
proc get_property {key objects} {
    incr ::calls
    if {[pointer $objects] ne $::expected} {error "RECONSTRUCTED_NATIVE_OBJECT_ARGUMENT"}
    set values {}; foreach object $objects {lappend values [list $key $object]}
    if {[llength $objects]==1} {return [lindex $values 0]}
    return $values
}
set scalar [binary format a* checkpoint_optimized-unqualified]
set expected [pointer $scalar]
common_collect_session::run {
    foreach key {NAME REF_NAME INIT PERIOD} {
        set first [common_cdc::get_property $key $scalar]
        if {$first ne [common_cdc::get_property $key $scalar]} {error "Scalar cache shape changed"}
    }
}
if {$calls!=4} {error "Miss/hit calls changed"}
set batch [list a b a]; set expected [pointer $batch]
common_collect_session::run {
    common_cdc::get_property NAME $batch
    set overlap [list b c b]; set expected [pointer $overlap]
    set first [common_cdc::get_property NAME $overlap]
    if {$first ne [common_cdc::get_property NAME $overlap]} {error "Partial batch shape changed"}
}
puts "COLLECT_ORIGINAL_ARGUMENT_PASS scalar_properties=4 overlapping_batches=2 MOCK_ONLY_NATIVE_UNRUN"
