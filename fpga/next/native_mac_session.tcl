# Explicit Python domain and finite synth/opt/checkpoint session binding.
# No checkpoint filename or generic pair can establish a consumed source export.
namespace eval valence_mac_session {
    variable directory; variable modes; variable config; variable session
    variable generation; variable serial; variable stderrLogs
    foreach {name initial} {directory {} modes {} config {} session {} generation 0 serial 0 stderrLogs {}} {
        if {![info exists $name]} {set $name $initial}
    }
}
proc valence_mac_session::invalidate {command operation} {
    # current_design without an argument is a read-only current-object query.
    if {[namespace tail [lindex $command 0]] eq "current_design" && [llength $command]==1} {return}
    variable generation; variable session
    incr generation; set session {}
    set ::valence_native_mac_mode::consumed 0
    set ::valence_native_mac_mode::optimized 0
}
proc valence_mac_session::watch {} {
    variable session
    # Finite supported flow: edits/reloads/design switches invalidate even when
    # their command subsequently fails. Required actual tools exist in Vivado.
    foreach name {synth_design opt_design open_checkpoint close_design read_checkpoint link_design
                  read_verilog read_vhdl read_edif read_ip add_files remove_files
                  create_project open_project close_project reset_design update_design
                  place_design route_design phys_opt_design power_opt_design current_design} {
        if {![llength [info commands ::$name]]} {continue}
        set wanted [list enter ::valence_mac_session::invalidate]
        if {$wanted ni [trace info execution ::$name]} {
            if {$session ne ""} {invalidate missing_lifecycle_trace enter; error "A live design command changed after synthesis: $name"}
            trace add execution ::$name enter ::valence_mac_session::invalidate
        }
    }
}
proc valence_mac_session::bind {path selectedModes} {
    variable directory; variable modes
    set path [file normalize $path]
    if {$directory ne $path || $modes ne $selectedModes} {
        invalidate source_export enter
        set directory $path; set modes $selectedModes
    }
    watch
}
proc valence_mac_session::configure {mode selection {command {wsl.exe}} {stderrDirectory {}}} {
    variable config
    if {$mode eq "native"} {
        if {$::tcl_platform(platform) ne "unix" || ![llength $selection]} {
            error "Native Python is supported only with an explicit verified Unix command; use the reviewed WSL route in Windows Vivado"
        }
        set next [dict create mode native command $selection]
    } elseif {$mode eq "wsl"} {
        if {$selection eq "" || [regexp {[\r\n\x00]} $selection] || ![llength $command] || $stderrDirectory eq ""} {
            error "Provide the verified WSL distribution, command and Windows stderr-log directory"
        }
        set logDirectory [file normalize $stderrDirectory]
        file mkdir $logDirectory
        set next [dict create mode wsl distro $selection command $command stderr_directory $logDirectory]
    } else {error "Use explicit native or wsl Python domain"}
    if {$config ne $next} {invalidate configure_python enter}
    set config $next
    return $config
}
proc valence_mac_session::run_wsl {command} {
    variable config; variable serial; variable stderrLogs
    set directory [dict get $config stderr_directory]
    for {set attempt 0} {$attempt<100} {incr attempt} {
        set path [file join $directory [format {wsl-stderr-%s-%s-%s.log} [pid] [clock clicks] [incr serial]]]
        set opened [catch {open $path {WRONLY CREAT EXCL}} channel options]
        if {!$opened} {break}
        if {![dict exists $options -errorcode] || [lrange [dict get $options -errorcode] 0 1] ne {POSIX EEXIST}} {return -options $options $channel}
    }
    if {$opened} {error "Could not create a fresh WSL stderr log"}
    lappend stderrLogs $path
    set code [catch {exec {*}$command 2>@ $channel} output options]
    close $channel
    if {$code} {return -options $options "$output\nWSL stderr retained at $path"}
    return $output
}
proc valence_mac_session::python {operation paths} {
    variable config; variable directory
    if {![dict exists $config mode]} {error "Configure the verified Python domain before consuming an export"}
    set helper [file join $directory native_mac_contract.py]
    if {[dict get $config mode] eq "wsl"} {
        set prefix [list {*}[dict get $config command] -d [dict get $config distro] --]
        set converted {}
        foreach path [list $helper {*}$paths] {
            set linux [string trimright [run_wsl [list {*}$prefix wslpath -u [file normalize $path]]] "\r\n"]
            if {$linux eq "" || [string index $linux 0] ne "/" || [regexp {[\r\n\x00]} $linux]} {error "WSL mapping must return one absolute Linux path"}
            lappend converted $linux
        }
        return [run_wsl [list {*}$prefix /usr/bin/python3 [lindex $converted 0] $operation {*}[lrange $converted 1 end]]]
    }
    return [exec {*}[dict get $config command] $helper $operation {*}$paths]
}
proc valence_mac_session::identity {} {
    variable directory
    set result [string trim [python --session-identity [list [file dirname $directory]]]]
    if {![regexp {^[0-9a-f]{64}$} $result]} {error "Malformed verified export session identity"}
    return $result
}
proc valence_mac_session::design {} {
    if {[llength [current_design]]!=1} {error "One live design is required"}
    set name [get_property NAME [current_design]]
    set part [get_property PART [current_design]]
    if {$name eq "" || $part eq ""} {error "Missing live design identity"}
    return [list $name $part]
}
proc valence_mac_session::seal {identity invocation stage} {
    variable session; variable generation; variable directory; variable modes
    if {$identity ne [valence_native_mac_verify_export]} {invalidate export_changed enter; error "Export changed during design operation"}
    set session [dict create identity $identity invocation $invocation stage $stage generation $generation \
                 directory $directory modes $modes design [design]]
    set ::valence_native_mac_mode::consumed 1
    set ::valence_native_mac_mode::optimized [expr {$stage eq "postopt"}]
}
proc valence_mac_session::assert {{stage any}} {
    variable session; variable generation; variable directory; variable modes
    watch
    if {[catch {set observed [valence_native_mac_verify_export]; set current [design]} why options]} {
        invalidate verification_failed enter
        return -options $options $why
    }
    if {$session eq "" || [dict get $session generation]!=$generation ||
        [dict get $session directory] ne $directory || [dict get $session modes] ne $modes ||
        [dict get $session identity] ne $observed || [dict get $session design] ne $current} {
        invalidate stale_session enter
        error "No matching successful source-bound live design session for this stage"
    }
    if {$stage ne "any" && [dict get $session stage] ne $stage} {error "Checkpoint stage does not match the successful live design stage"}
    return $session
}
