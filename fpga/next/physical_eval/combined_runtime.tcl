# Keep raw stderr separate: a successful WSL process may print UTF-16 warnings.
proc combined_exec {command} {
    if {![info exists ::combined_stderr_serial]} {set ::combined_stderr_serial 0}
    set base [expr {[info exists ::combined_runtime_root] ? $::combined_runtime_root : [pwd]}]
    set directory [file join $base combined-runtime-stderr]
    file mkdir $directory
    set path [file join $directory [format {stderr-%s-%s-%s.bin} [pid] [clock clicks] [incr ::combined_stderr_serial]]]
    set channel [open $path {WRONLY CREAT EXCL}]
    fconfigure $channel -translation binary
    set code [catch {exec {*}$command 2>@ $channel} output options]
    close $channel
    set status [open $path.status {WRONLY CREAT EXCL}]
    puts $status [list tcl_code $code errorcode [expr {[dict exists $options -errorcode] ? [dict get $options -errorcode] : {NONE}}]]
    close $status
    if {$code} {return -options $options "$output\nRaw subprocess stderr retained at $path"}
    return $output
}

# Separate candidate identity gate. No project or tool run is started by sourcing.
proc combined_python {root script arguments} {
    set scriptPath [file join $root scripts $script]
    if {[info exists ::combined_recovery_options] && $script in {combined_stage_receipt.py verify_combined_rom_graph.py}} {
        set scriptPath [file join $::combined_recovery_validator fpga next physical_eval $script]
        if {$script eq "combined_stage_receipt.py"} {
            set arguments [concat $arguments $::combined_recovery_options]
        }
    }
    if {[dict get $::r3_config python_mode] eq "native"} {
        return [combined_exec [list {*}[dict get $::r3_config python_command] -B $scriptPath {*}$arguments]]
    }
    set prefix [concat [dict get $::r3_config wsl_command] [list -d [dict get $::r3_config wsl_distribution] --]]
    set path [string trim [combined_exec [list {*}$prefix wslpath -u $scriptPath]]]
    return [combined_exec [list {*}$prefix {*}[dict get $::r3_config python_command] -B $path {*}$arguments]]
}
proc combined_root_path {root} {
    if {[dict get $::r3_config python_mode] eq "native"} {return $root}
    return [string trim [combined_exec [list {*}[dict get $::r3_config wsl_command] -d [dict get $::r3_config wsl_distribution] -- wslpath -u $root]]]
}
proc combined_gate {root} {
    set ::combined_runtime_root $root
    source [file join $root scripts runtime.tcl]
    r3_load_config $root
    puts [combined_python $root verify_combined_package.py [list [combined_root_path $root] --vivado-version [version -short]]]
}
proc combined_verify_rom {root dump report} {
    set actualDump [combined_root_path $dump]
    return [combined_python $root verify_combined_rom_graph.py [list [combined_root_path $root] $actualDump \
        --rom-sha256 [dict get $::r3_config rom_sha256] --padded-sha256 [dict get $::r3_config padded_sha256] --report [combined_root_path $report]]]
}
proc combined_project_inputs {root} {
    if {![info exists ::env(XILINX_VIVADO)]} {error "Missing actual Vivado installation root"}
    set listing [file join [pwd] project-inputs.txt]
    set handle [open $listing {WRONLY CREAT EXCL}]
    foreach file [lsort -unique [get_files -all -quiet]] {puts $handle [combined_root_path [file normalize $file]]}
    close $handle
    puts [combined_python $root combined_project_inputs.py [list [combined_root_path $root] \
        [combined_root_path $listing] [combined_root_path $::env(XILINX_VIVADO)]]]
}

# Evaluate hierarchy-bound bytes with the original sealed script's source context.
# Nested source commands then retain normal Tcl info script behavior; restore it
# even when the bound script returns an error. The transformed bytes stay logged.
proc combined_source_bound {path} {
    set path [file normalize $path]
    set f [open $path];set body [read $f];close $f
    set pairs [list u_soc/board/nativeBank/gmac $::V_GMAC_ROOT u_soc/board/nativeBank $::V_BANK_ROOT u_soc/board/platform/rom $::V_ROM_ROOT u_soc $::V_SOC_ROOT u_rgmii $::V_RGMII_ROOT]
    set actual [string map $pairs $body]
    set f [open [file join [pwd] bound-[file tail $path]] w]
    puts -nonewline $f $actual;close $f
    set previous [info script]
    info script $path
    set code [catch {uplevel #0 $actual} result options]
    info script $previous
    return -options $options $result
}
