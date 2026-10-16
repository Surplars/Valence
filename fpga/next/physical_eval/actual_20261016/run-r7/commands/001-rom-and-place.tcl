# Resume the actual retained current DCP; no synthesis or reload.
if {[get_property TOP [current_design]] ne {soc_top_fpga_next_ddr} || [get_property PART [current_design]] ne {xczu15eg-ffvb1156-2-i}} {error {Wrong current retained top/part}}
source [file join $pkg network export board native-mac-mode.tcl]
valence_native_mac_configure_python wsl Ubuntu-24.04 [list C:/Windows/System32/wsl.exe] [file join $out python-stderr]
set identity [valence_native_mac_verify_export]
if {$identity ne {a25f9cb85ef22c6c50df514ac2986f5e597e19e5743fd0e606d14263e759c615}} {error {Retained export identity changed}}
set invocation [list -top soc_top_fpga_next_ddr -generic [list NATIVE_MAC_LOCAL_PAD_RESET_RELEASE=1 NATIVE_MAC_REGISTER_SELECTED_HALF=1] -part xczu15eg-ffvb1156-2-i -flatten_hierarchy none]
valence_mac_session::seal $identity $invocation synth
diag_event recovery current_source_session_restored {ORIGINAL_PID22028_RAW_SHA256_EXTERNAL_PROOF_RETAINED_PID_NO_NEW_SYNTHESIS}
diag_save recovered_synthesis post-synth-unconstrained.dcp
source [file join $root orchestration diagnostic-place-r7.tcl]
diag_event diagnostic complete {PLACED_DIAGNOSTIC_NO_ROUTE_NO_BIT_REVIEW_REQUIRED}
