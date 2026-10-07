# Prove that a physical request grant can no longer feed the ordinary
# AtomicMemory CPU response combinationally. Same SoC/clock synthesis comparison;
# this is not a routed frequency measurement.
if {$argc != 3} {error "Expected BASELINE_SOC_DCP CANDIDATE_SOC_DCP OUT_DIRECTORY"}
lassign $argv baseline candidate out
file mkdir $out
foreach kind {baseline candidate} {
    open_checkpoint [set $kind]
    set grant [get_pins -quiet platform/physicalData_systemArbiter/io_clients_0_request_ready]
    set response [get_pins -quiet platform/shared/unit/io_cpu_response_valid]
    if {[llength $grant] != 1 || [llength $response] != 1} {
        error "Missing preserved physical-arbiter/atomic-module boundary"
    }
    set paths [get_timing_paths -quiet -through $grant -through $response -max_paths 1]
    if {$kind eq "baseline"} {
        if {[llength $paths] != 1} {error "Missing baseline AtomicMemory empty-owner bypass"}
        report_timing -through $grant -through $response -max_paths 10 \
            -file [file join $out baseline_atomic_bypass.rpt]
        puts "ATOMIC_OWNER_CUT: baseline bypass full delay=[get_property DATAPATH_DELAY $paths]"
    } else {
        if {[llength $paths]} {error "Candidate retains physical-grant -> atomic-response bypass"}
        puts "ATOMIC_OWNER_CUT: candidate has no physical-grant -> atomic-response bypass"
        report_timing -through $response -max_paths 10 \
            -file [file join $out candidate_atomic_response.rpt]
    }
    close_design
}
