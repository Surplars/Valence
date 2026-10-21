source [file join $valence(root) fpga common producer_common.tcl]
# Independent public physical-boundary oracles. This is NOT a CPU boot/DDR model;
# matching affected common-platform GSIM evidence is separately mandatory.
if {$valence(simulation_suite) ne "common-physical-boundaries-v1"} {error "Unreviewed simulation suite"}
if {![info exists ::env(VALENCE_VIVADO_HOME)]} {error "Missing native Vivado installation"}
set bin [file join $::env(VALENCE_VIVADO_HOME) bin]
set vendor [file join $::env(VALENCE_VIVADO_HOME) data verilog src]
foreach tool {xvlog xelab xsim} {
    set executable($tool) [file join $bin $tool.bat]
    if {![file isfile $executable($tool)]} {error "Missing installed Windows tool $tool"}
    if {[catch {exec $executable($tool) -help 2>@1} help]} {
        if {![string match *Usage* $help] && ![string match *Options* $help]} {error "Cannot inspect $tool support: $help"}
    }
    common_log $tool-help.txt $help
    set supports_mt($tool) [regexp -- {(^|[[:space:]])--?mt([[:space:]]|$)} $help]
}
if {!$supports_mt(xelab)} {error "Installed xelab lacks required explicit -mt N support"}
# Pin the public test's actual FPGA vendor TAP identity; newer model bytes need review.
puts [exec $valence(python) [file join $valence(root) fpga common simulation_inputs.py] --root $valence(root) --vendor $vendor]
set command [list $executable(xvlog) -sv {*}[common_files simulation_filelist] [file join $vendor glbl.v]]
if {$supports_mt(xvlog)} {lappend command -mt $valence(threads)}
common_run xvlog-console.log $command
common_record xvlog $command [expr {$supports_mt(xvlog) ? "configured" : "unsupported"}] \
    [expr {$supports_mt(xvlog) ? $valence(threads) : ""}] xvlog-help.txt \
    "Requested threads retained; installed help determines support; active workers unmeasured"
set xelab_commands {}; set xsim_commands {}
foreach {name top marker reject parameters} {
    jtag_upstream i1_dual_tap_tb {PASS I1_DUAL_TAP} {} {SYS_HALF_PS=2000 DAP_UPSTREAM=1}
    jtag_downstream i1_dual_tap_tb {PASS I1_DUAL_TAP} {} {SYS_HALF_PS=2000 DAP_UPSTREAM=0}
    jtag_bad64 i1_dual_tap_tb {} CHAIN_CAPABILITY_ORACLE {SYS_HALF_PS=2000 DUT_SCAN_BITS=64}
    dci common_dci_startup_tb COMMON_DCI_STARTUP_PASS {} {}
    quarter common_trispeed_pad_tb TRISPEED_QUARTER_PAD_BEHAVIOR_PASS {} {}
} {
    set command [list $executable(xelab) $top glbl -L unisims_ver -L unimacro_ver -debug typical -mt $valence(threads) -s $name]
    foreach parameter $parameters {lappend command -generic_top $parameter}
    common_run $name-elab.log $command
    lappend xelab_commands $command
    set command [list $executable(xsim) $name -runall -onerror quit]
    lappend xsim_commands $command
    set logpath [file join $valence(out) $name-run.log]
    set failed [catch {exec {*}$command > $logpath 2>@1} result]
    set f [open $logpath]; set log [read $f]; close $f
    if {$reject eq ""} {
        if {$failed || [string first $marker $log] < 0 || [regexp -nocase {(^|\n)(FATAL|ERROR):} $log]} {error "Boundary simulation failed: $name"}
    } elseif {[string first $reject $log] < 0 || [string first {PASS I1_DUAL_TAP} $log] >= 0} {
        error "Negative control did not reject the 64-bit mismatch for the expected reason"
    }
}
common_log xelab-invocations.txt [join $xelab_commands \n]
common_log xsim-invocations.txt [join $xsim_commands \n]
common_record xelab [lindex $xelab_commands 0] configured $valence(threads) xelab-invocations.txt
common_record xsim [lindex $xsim_commands 0] unsupported "" xsim-help.txt \
    "Requested count retained; installed xsim runtime has no verified parallel execution thread-count option"
common_log smoke-result.txt "COMMON_PHYSICAL_BOUNDARIES_PASS JTAG_USER2_65_BOTH_ORDERS BAD64_REJECTED TRISPEED_PAD_10_100_1000 VENDOR_JTAG=1 PHY_BEHAVIORAL=1 BOARD=0 STA=0 CPU_BOOT_SCOPE=SEPARATE_GSIM_RECEIPT"
common_receipt
