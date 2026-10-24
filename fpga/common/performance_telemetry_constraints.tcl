# Mandatory feature-bound call from post_synth AND post_opt. Never infer that an
# expected monitor is disabled merely because its endpoints are missing.
source [file join $valence(root) fpga zu15eg performance-telemetry-constraints.tcl]
proc common_performance_telemetry_constraints {} {
    global valence
    set expected 0
    if {[info exists valence(performance_telemetry)]} {
        set expected $valence(performance_telemetry)
        if {$expected ni {0 1}} {error "Invalid explicit telemetry feature flag"}
    }
    set monitor [get_cells -quiet u_soc/monitor]
    if {!$expected} {
        if {[llength $monitor]} {error "Telemetry present but missing explicit enabled configuration"}
        puts "COMMON_TELEMETRY_DISABLED explicit_legacy_profile"
        return
    }
    if {[llength $monitor] != 1} {error "Expected telemetry monitor missing: u_soc/monitor"}
    set profile i1
    if {[info exists valence(telemetry_physical_profile)]} {
        set profile $valence(telemetry_physical_profile)
    }
    if {$profile ni {i1 a1-experimental}} {error "Invalid explicit telemetry physical profile"}
    if {$profile eq "i1"} {
        valence_performance_telemetry_constraints u_soc/monitor 3.0
    } else {
        valence_performance_telemetry_constraints u_soc/monitor 3.0 $profile
    }
    set banks [expr {$profile eq "i1" ? 16 : 17}]
    puts "COMMON_TELEMETRY_BOUNDED gray_banks=$banks width=32 register_bridge=1 budget_ns=3.0 profile=$profile"
}
