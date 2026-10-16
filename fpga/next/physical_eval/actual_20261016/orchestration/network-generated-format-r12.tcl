set body [info body valence_quarter_tx_clocks]
set body [string map [list {%s/phase_reset_reg} {%sphase_reset_reg}] $body]
proc valence_quarter_tx_clocks {hier} $body
set body [info body valence_trispeed_clock_reset_audit]
set body [string map [list {rx_capture_pair/enabled/} {rx_capture_pair/enabled.}] $body]
proc valence_trispeed_clock_reset_audit [info args valence_trispeed_clock_reset_audit] $body
diag_event network_clock generated_formats_adapted {ACTUAL_PHASE_RESET_AND_RX_FALLING_PAIR_NAMES}
