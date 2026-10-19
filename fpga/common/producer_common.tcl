# Helpers for the three explicit, hash-bound local producers. Not standalone.
foreach key {root out phase threads profile_sha256 rtl_filelist simulation_filelist mig_xci cpu
             post_synth_constraints post_opt_constraints media_scenarios simulation_suite rom_coe constraints} {
    if {![info exists valence($key)]} {error "Missing producer configuration: $key"}
}
if {![info exists ::env(VALENCE_WINDOWS_PYTHON)]} {error "Use native Windows PowerShell runner with explicit Python"}
set valence(python) $::env(VALENCE_WINDOWS_PYTHON)
proc common_json {s} {return "\"[string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t] $s]\""}
proc common_log {name text} {set f [open [file join $::valence(out) $name] w]; puts $f $text; close $f}
proc common_run {name command} {
    # Preserve nonzero tool status; never accept a stale pass marker/output.
    set log [file join $::valence(out) $name]
    puts "COMMON_EXEC $command"
    if {[catch {exec {*}$command > $log 2>@1} result options]} {
        error "Tool failed: $command; see $log; $result"
    }
    return $log
}
proc common_files {name} {
    set f [open $::valence($name) r]; set lines [split [string trim [read $f]] \n]; close $f
    return [lmap line $lines {file join $::valence(root) [string trim $line]}]
}
proc common_record {name command status effective evidence {reason {}}} {
    set commandJson [lmap word $command {common_json $word}]
    if {$effective eq ""} {set effective null}
    lappend ::common_records [format {%s:{"command":[%s],"requested_threads":%d,"effective_thread_limit":%s,"status":%s,"reason":%s,"evidence":{"path":%s}}} \
        [common_json $name] [join $commandJson ,] $::valence(threads) $effective [common_json $status] [common_json $reason] [common_json $evidence]]
}
proc common_design_step {name args} {
    set limit [get_param general.maxThreads]
    if {$limit < $::valence(threads)} {error "Thread setting was reduced before $name"}
    # general.maxThreads is an accepted maximum, not a promise of active workers.
    common_log $name-threads.txt "tool=$name requested=$::valence(threads) effective_configured_limit=$limit active_threads=UNMEASURED synthesis_effective_max=4 reference=https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/set_param vivado=[version -short]"
    $name {*}$args
    if {$name eq "synth_design"} {
        common_record $name [list $name {*}$args] unsupported 4 $name-threads.txt             "AMD UG835 documents synth_design effective maximum 4; general request remains >=8; active workers unmeasured"
    } elseif {$name eq "opt_design"} {
        common_record $name [list $name {*}$args] unsupported "" $name-threads.txt             "general.maxThreads requested/read back; no verified independent opt_design effective worker limit"
    } else {
        common_record $name [list $name {*}$args] configured $limit $name-threads.txt
    }
}
proc common_receipt {} {
    common_log tools.json "\{[join $::common_records ,]\}"
    puts [exec $::valence(python) [file join $::valence(root) fpga common producer.py] \
        --manifest $::valence(manifest) --phase $::valence(phase) --records [file join $::valence(out) tools.json]]
}
set ::common_records {}
