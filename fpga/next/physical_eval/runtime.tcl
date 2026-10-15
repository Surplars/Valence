# Explicit runtime inputs. Sourcing this file never invokes Vivado.
proc r3_load_config {root} {
    source [file join $root physical-config.tcl]
    foreach key {threads part python_mode python_command wsl_command wsl_distribution rom_sha256 padded_sha256} {
        if {![dict exists $::r3_config $key]} {error "Missing runtime key $key"}
    }
    set threads [dict get $::r3_config threads]
    if {![regexp {^[0-9]+$} $threads] || $threads<1} {
        error "Thread count must be a positive integer"
    }
}
proc r3_apply_threads {stage} {
    if {![regexp {^[a-z_]+$} $stage]} {error "Invalid thread-manifest stage"}
    set requested [dict get $::r3_config threads]
    set rejected [catch {set_param general.maxThreads $requested} reason]
    set actual unknown
    catch {set actual [get_param general.maxThreads]}
    set status [expr {$rejected ? "REJECTED" : ($actual eq $requested ? "APPLIED" : "MISMATCH")}]
    set tool [string map [list \t " " \n " " \r " "] [version -short]]
    set path [file join [pwd] threads.tsv]
    set fresh [expr {![file exists $path]}]
    set handle [open $path a]
    if {$fresh} {puts $handle "stage\trequested_threads\tconfigured_threads\tstatus\tvivado_version"}
    puts $handle "$stage\t$requested\t$actual\t$status\t$tool"
    close $handle
    if {$rejected} {error "Installed Vivado rejected general.maxThreads=$requested: $reason"}
    if {$status ne "APPLIED"} {error "Thread readback differs: requested=$requested actual=$actual"}
    puts "R3_THREADS stage=$stage requested=$requested configured=$actual"
}
proc r3_configure_python {out} {
    if {[dict get $::r3_config python_mode] eq "native"} {
        valence_native_mac_configure_python native [dict get $::r3_config python_command]
    } else {
        valence_native_mac_configure_python wsl [dict get $::r3_config wsl_distribution] \
            [dict get $::r3_config wsl_command] [file join $out python-stderr]
    }
}
proc r3_python_path {path} {
    if {[dict get $::r3_config python_mode] eq "native"} {return $path}
    set command [concat [dict get $::r3_config wsl_command] \
        [list -d [dict get $::r3_config wsl_distribution] -- wslpath -u $path]]
    return [string trim [valence_mac_session::run_wsl $command]]
}
proc r3_verify_rom {root dump} {
    set args [list -B [r3_python_path [file join $root scripts verify_rom_graph.py]] \
        [r3_python_path $root] [r3_python_path $dump] \
        --rom-sha256 [dict get $::r3_config rom_sha256] \
        --padded-sha256 [dict get $::r3_config padded_sha256]]
    if {[dict get $::r3_config python_mode] eq "native"} {
        return [exec {*}[dict get $::r3_config python_command] {*}$args]
    }
    return [valence_mac_session::run_wsl [concat [dict get $::r3_config wsl_command] \
        [list -d [dict get $::r3_config wsl_distribution] --] \
        [dict get $::r3_config python_command] $args]]
}
