# External diagnostic amendment. Complete current encoder/parent/adapter equality
# independently reviewed and structurally lowered; no mapped proof is bypassed.
proc valence_install_actual_control_lemma_v1 {} {
    set expected a25f9cb85ef22c6c50df514ac2986f5e597e19e5743fd0e606d14263e759c615
    if {[valence_native_mac_verify_export] ne $expected} {error "Control lemma requires exact verified diagnostic source identity"}
    if {$::valence_native_mac_mode::t1 != 1 || $::valence_native_mac_mode::selected != 1} {error "Control lemma requires actual T1/selected1/1"}
    set ::valence_native_mac_mode::control_lemma 1
    puts "SOURCE_CONTROL_EQUALITY_LEMMA_BOUND_CURRENT_EXPORT MAPPED_LIVE_CHAIN_AND_TRANSITION_PROOFS_STILL_REQUIRED"
}
valence_install_actual_control_lemma_v1
