# Keep exact export byte verification and the unchanged semantic data/control
# role audit; substitute only the explicitly observed BOTH clock-tree profile.
proc valence_native_mac_assert_mode {{instance u_rgmii}} {
    valence_native_mac_verify_export
    source [file join $::valence_native_mac_mode::directory native_mac_roles.tcl]
    source [file join $::root orchestration mac-clock-profile-r13.tcl]
    return [valence_mac_roles::audit $instance 1 1]
}
diag_event network_clock semantic_profile_adapted {BOTH_PAD250_BUFFER_RAW125_DIV2_RETAIN_ALL_ENCODER_AND_SERIALIZER_CHECKS}
