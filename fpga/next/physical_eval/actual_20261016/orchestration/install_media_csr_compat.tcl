# External exact-source/mapped-cone amendment. The mandatory three CDC chains
# and every original chain/reset/timing check remain in the original collector.
proc valence_mac::media_csr_merge_check_v1 {pin actual} {
    set root u_soc/board/nativeBank/gmac
    set expected {}
    foreach chain {txLink_sync rxLink_sync rawRxOpen_sync} {
        lappend expected [format {%s/%s/stages_reg[0]/D} $root $chain]
    }
    set expected [lsort $expected]
    if {$actual eq $expected} {return $actual}
    set extra $root/csr_i_3/I0
    if {$actual ne [lsort [concat $expected [list $extra]]]} {error {MAC mediaOpen has an unproved missing/extra load}}
    if {[valence_native_mac_verify_export] ne {a25f9cb85ef22c6c50df514ac2986f5e597e19e5743fd0e606d14263e759c615}} {error {CSR merge requires the exact source-proved diagnostic export}}
    set lut [one get_cells $root/csr_i_3]
    if {[get_property REF_NAME $lut] ne {LUT2} || [string tolower [get_property INIT $lut]] ne {4'h6}} {error {CSR merge must be exact two-input XOR}}
    same_net $pin $extra
    same_net $root/csr_i_3/I1 $root/media/io_linkUp_INST_0/O
    same_net $root/csr_i_3/I1 $root/media/io_linkUp
    same_net $root/csr_i_3/O [format {%s/csr/io_ports_0_events[5]} $root]
    set sink [format {%s/csr/pending_reg[5]/D} $root]
    set ends [names [all_fanout -flat -endpoints_only -from [one get_pins $root/csr_i_3/O]]]
    if {$ends ne [list $sink]} {error {CSR merge reaches an unexpected sequential/output endpoint}}
    set pending [one get_cells [format {%s/csr/pending_reg[5]} $root]]
    if {[get_property REF_NAME $pending] ne {FDCE}} {error {CSR event destination is not expected FDCE}}
    set sourceClock [clock $root/mediaOpen_reg/C]
    set targetClock [clock $pending/C]
    if {$sourceClock ne $targetClock || $sourceClock ne {clk_out1_clk_wiz_ddr} || abs([get_property PERIOD [get_clocks $sourceClock]]-10.0)>0.001} {error {CSR merge is not the same CPU100 domain}}
    foreach clockPin [list $root/mediaOpen_reg/C $pending/C] {
        if {[get_property IS_INVERTED [one get_pins $clockPin]] ni {0 FALSE false 1'b0}} {error {CSR merge clock polarity changed}}
    }
    puts {MAC_PROVED_MEDIAOPEN_PREVIOUSLINK_MERGE_THREE_CDC_CHAINS_PLUS_SAME_CPU_EVENT_ONLY}
    return $actual
}
# Replace only the known exact expected-load comparison, preserving all other
# collector checks. No load is hidden or removed from the observed load list.
set media_original {        if {[loads $root/mediaOpen_reg/Q] ne [lsort $media_loads]} {error "MAC mediaOpen is not exactly three destination chains"}}
set media_body [info body valence_mac::collect]
if {[llength [split $media_body "\n"]] < 2 || [string first $media_original $media_body] < 0 || [string first $media_original $media_body] != [string last $media_original $media_body]} {error {Unknown collector expected-load gate; refusing patch}}
set media_replacement {        set media_loads [media_csr_merge_check_v1 $root/mediaOpen_reg/Q [loads $root/mediaOpen_reg/Q]]
        if {[loads $root/mediaOpen_reg/Q] ne [lsort $media_loads]} {error "MAC mediaOpen proved-load set changed during collection"}}
proc valence_mac::collect {contract binding output mbps} [string map [list $media_original $media_replacement] $media_body]
unset media_original media_body media_replacement
