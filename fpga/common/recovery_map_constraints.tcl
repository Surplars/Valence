# Fresh-netlist diagnostic application of official common post_synth/post_opt entries.
# No saved DCP, implementation or qualification is produced by this diagnostic.
set valence(root) [file normalize [lindex $argv 0]]
set valence(out) [file normalize [lindex $argv 1]]
set target [file normalize [lindex $argv 2]]
set valence(profile_sha256) [lindex $argv 3]
set valence(control_lemma) 1
set valence(phase) recovery_r1_post_synth_diagnostic
set valence(diagnostic_families) [expr {[llength $argv]>4 && [lindex $argv 4] eq {1}}]
set valence(diagnostic_implementation) [expr {[llength $argv]==7 && [lindex $argv 6] eq {DIAGNOSTIC_IMPLEMENT_NO_BIT}}]
set ::board_prep_failures {}
cd $valence(out)
set_param general.maxThreads 8
foreach cmd {synth_design opt_design place_design phys_opt_design route_design write_bitstream upgrade_ip generate_target} {
 if {$valence(diagnostic_implementation) && $cmd in {opt_design place_design phys_opt_design route_design}} {continue}
 rename $cmd forbidden_$cmd
 proc $cmd {args} {error {BOARD_CONSTRAINT_PREPARATION_ONLY}}
}
rename write_checkpoint board_prep_save_checkpoint
proc write_checkpoint {args} {error {BOARD_CONSTRAINT_DIAGNOSTIC_NO_QUALIFIED_CHECKPOINT}}
proc common_json {s} {return "\"[string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t] $s]\""}
proc common_log {name text} {set f [open [file join $::valence(out) $name] w];puts $f $text;close $f}
namespace eval board_prep {}
proc board_prep::diagnostic_gate {coverage} {
 set f [open $coverage];set text [read $f];close $f
 foreach key {no_clock unconstrained_internal_endpoints multiple_clock generated_clocks loops latch_loops constant_clock} {
  set pattern [format {checking %s \(([0-9]+)\)} $key]
  set values [regexp -all -inline $pattern $text]
  if {![llength $values]} {error "Unknown check_timing format: $key"}
  foreach {whole count} $values {if {$count!=0} {error "Diagnostic implementation blocked: $key=$count"}}
 }
 # External serial inputs are asynchronous: retain the real pad-to-first max
 # bounds and report the tool's max-only classification. No invented min delay.
 foreach {port endpoint budget second} {uart_rxd u_soc/peripherals/uart/sampledRx_meta_reg/D 20.0 u_soc/peripherals/uart/sampledRx_reg eth_mdio {u_soc/peripherals/gmac/mdio_io_mdioIn_sync/stages_reg[0]/D} 10.0 {u_soc/peripherals/gmac/mdio_io_mdioIn_sync/stages_reg[1]}} {
  set first [string range $endpoint 0 end-2]
  set clock [common_cdc::clock $first/C]
  common_cdc::ff $first $clock 1;common_cdc::ff $second $clock 1
  if {[common_cdc::drivers $second/D] ne [list $first/Q] || [common_cdc::loads $first/Q] ne [list $second/D]} {error "Non-direct async IO synchronizer $port"}
  set paths [get_timing_paths -quiet -from [get_ports $port] -to [common_cdc::one get_pins $endpoint] -delay_type max -max_paths 1]
  if {[llength $paths]!=1} {error "Missing actual async serial input bound $port"}
  set req [get_property REQUIREMENT $paths]
  if {![string is double -strict $req] || $req<=0 || $req>$budget+0.001} {error "Wrong actual async input bound $port"}
  set exception [string tolower [string map {_ {} - {} { } {}} [get_property EXCEPTION $paths]]]
  if {![string match maxdelay* $exception]} {error "Async input does not have an explicit max-delay bound: $port"}
 }
 set active {};set bodies {};set counts {}
 foreach line [split $text \n] {
  if {[regexp {checking\s+(no_input_delay|partial_input_delay|no_output_delay|partial_output_delay)\s+\(([0-9]+)\)} $line -> key count]} {
   set active $key;dict set bodies $key {};dict set counts $key $count
  } elseif {[regexp {^[0-9]+\. checking } $line]} {set active {}
  } elseif {$active ne {}} {dict append bodies $active "$line\n"}
 }
 set f [open diagnostic-io-classification.tcllist w]
 try {
  foreach {key allowed} {no_input_delay {button_n sys_rst_n} partial_input_delay {uart_rxd eth_mdio} no_output_delay {c0_ddr4_reset_n eth_txc} partial_output_delay {}} {
   if {![dict exists $counts $key]} {error "Missing diagnostic IO category $key"}
   set found {}
   foreach port [get_property NAME [get_ports]] {
    if {[regexp -line "^[common_cdc::quote $port]$" [dict get $bodies $key]]} {lappend found $port}
   }
   if {[llength $found]!=[dict get $counts $key]} {error "Incomplete diagnostic IO listing $key"}
   foreach port $found {if {$port ni $allowed} {error "Unreviewed diagnostic IO category $key: $port"}}
   puts $f [list category $key actual_ports $found qualification DIAGNOSTIC_ONLY_FINAL_IO_REVIEW_PENDING]
  }
 } finally {close $f}
 set clock [get_clocks -quiet -of_objects [get_ports eth_txc]]
 if {[llength $clock]!=1 || [get_property NAME $clock] ne {phy_tx_capture}} {error {Missing actual forwarded RGMII capture clock}}
 set top [get_nets -quiet -segments -of_objects [get_ports c0_ddr4_reset_n]]
 set mig [get_nets -quiet -segments -of_objects [get_pins u_ddr/c0_ddr4_reset_n]]
 set same 0;foreach n $mig {if {[lsearch -exact $top $n]>=0} {set same 1}}
 if {!$same} {
  # A normal top-level OBUF may separate the logical MIG output from its pad.
  # Prove that exact single buffer, rather than accepting arbitrary board logic.
  set driver [get_pins -quiet -leaf -of_objects $top -filter {DIRECTION == OUT}]
  if {[llength $driver]==1 && [get_property REF_PIN_NAME $driver] eq {O}} {
   set owner [get_cells -of_objects $driver]
   if {[llength $owner]==1 && [get_property REF_NAME $owner] eq {OBUF}} {
    set input [get_pins -of_objects $owner -filter {REF_PIN_NAME == I}]
    foreach n [get_nets -quiet -segments -of_objects $input] {if {[lsearch -exact $mig $n]>=0} {set same 1}}
   }
  }
 }
 if {!$same} {error {DDR reset output is not the original MIG output}}
 puts {DIAGNOSTIC_CLOCK_AND_IO_BINDINGS_READY_FINAL_RESET_IO_CDC_SIGNOFF_PENDING}
}
proc board_prep::cache {} {
 variable cells;variable pins;variable banks
 set cells {};set pins {};set banks {};set selected {}
 set all [get_cells -quiet -hier]
 foreach c $all name [get_property NAME $all] {
  dict set cells $name $c
  if {[regexp {^(.*)\[[0-9]+\]$} $name -> prefix]} {dict lappend banks $prefix $c}
  if {[regexp {^(u_soc/(crossing|peripherals)(/|$)|u_debug/|u_rgmii(/|$)|network_clock/|[^/]*reset_pipe_reg)} $name]} {lappend selected $c}
 }
 set p [get_pins -quiet -of_objects $selected]
 foreach object $p name [get_property NAME $p] {dict set pins $name $object}
 puts "BOARD_CACHE cells=[dict size $cells] pins=[dict size $pins]"
}
proc board_prep::objects {kind names} {
 variable cells;variable pins
 set names [lsort -unique $names]
 if {![llength $names]} {error {Empty exact formal collection}}
 set found {}
 foreach name $names {
  if {$kind eq {get_cells}} {
   if {![dict exists $cells $name]} {error "Missing cached exact formal object $kind $name"}
   lappend found [dict get $cells $name]
   continue
  } elseif {$kind eq {get_pins}} {
   if {![dict exists $pins $name]} {
    # Rare launch/reset objects outside the cached boundary: direct full-name
    # lookup, never a -hier traversal. Preserve exact NAME equality.
    set slash [string last / $name]
    set owner [string range $name 0 [expr {$slash-1}]]
    set tail [string range $name [expr {$slash+1}] end]
    if {![dict exists $cells $owner]} {error "Missing exact cached pin owner $owner"}
    set o [get_pins -quiet -of_objects [dict get $cells $owner] -filter "REF_PIN_NAME == $tail"]
    if {[llength $o]!=1 || [get_property NAME $o] ne $name} {error "Missing exact formal pin $name"}
    dict set pins $name [lindex $o 0]
   }
   lappend found [dict get $pins $name]
   continue
  } else {
   set o [$kind -quiet $name]
   if {[llength $o]!=1 || [get_property NAME $o] ne $name} {error "Missing exact object $kind $name"}
   lappend found {*}$o;continue
  }
 }
 if {[lsort -unique [get_property NAME $found]] ne $names} {error {Formal exact collection differs}}
 return $found
}
proc board_prep::one {kind name} {
 set result [objects $kind [list $name]]
 if {[llength $result]!=1} {error "Formal exact one mismatch: $name"}
 return [lindex $result 0]
}
proc board_prep::bank {prefix width} {
 variable banks
 set found {};if {[dict exists $banks $prefix]} {set found [get_property NAME [dict get $banks $prefix]]}
 set expected {};for {set i 0} {$i<$width} {incr i} {lappend expected [format {%s[%d]} $prefix $i]}
 if {[lsort $found] ne [lsort $expected]} {error "COMMON_CDC bank shape changed: $prefix expected=$width found=$found"}
 return $expected
}
proc board_prep::progress {command op} {puts "FORMAL_ENTER $command";flush stdout}
proc board_prep::net_types {p} {
 if {![llength $p]} {return MISSING}
 set n [get_nets -quiet -segments -of_objects $p]
 if {![llength $n]} {return DISCONNECTED}
 return [lsort -unique [get_property TYPE $n]]
}
proc board_prep::cached_pin {name} {
 variable pins
 if {[dict exists $pins $name]} {return [dict get $pins $name]}
 return {}
}
proc board_prep::lane_evidence {} {
 variable cells;variable evidence_saved
 if {[info exists evidence_saved]} {return}
 set evidence_saved 1
 set h u_soc/crossing/crossing/empty_fifo
 set f [open inactive-lane-evidence.tcllist w]
 foreach tail {source_valid source_ready destination_valid destination_ready sourceClock destinationClock} {
  puts $f [list port $h/$tail net_types [net_types [cached_pin $h/$tail]]]
 }
 set bits [get_pins -quiet -of_objects [dict get $cells $h] -filter {REF_PIN_NAME =~ destination_bits*}]
 puts $f [list data_bits [llength $bits] net_types [net_types $bits]]
 dict for {n c} $cells {
  if {[string first $h/ $n]!=0 || [get_property IS_PRIMITIVE $c] ni {1 TRUE true}} {continue}
  set ref [get_property REF_NAME $c]
  if {[string match FD* $ref]} {
   set d [cached_pin $n/D];set nets [get_nets -quiet -segments -of_objects $d];set drivers {}
   if {[llength $nets]} {set p [get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}];if {[llength $p]} {set drivers [get_property NAME $p]}}
   puts $f [list cell $n ref $ref init [get_property INIT $c] async [get_property ASYNC_REG $c] Dtypes [net_types $d] Ddrivers $drivers CEtypes [net_types [cached_pin $n/CE]]]
  } else {puts $f [list cell $n ref $ref]}
 }
 close $f
}
proc board_prep::install_cache_helpers {} {
 cache
 lane_evidence
 # Equivalent exact-name collection lookups; every original shape/clock/driver proof remains.
 foreach ns {::common_cdc ::valence_fifo_payload} {
  foreach name {one objects} {
   if {[llength [info commands ${ns}::$name]]} {
    if {[llength [info commands ${ns}::uncached_$name]]} {rename ${ns}::uncached_$name {}}
    rename ${ns}::$name ${ns}::uncached_$name
    proc ${ns}::$name {kind names} [format {return [::board_prep::%s $kind $names]} $name]
    puts "FORMAL_CACHE_HELPER_INSTALLED ${ns}::$name"
   }
  }
 }
 if {[llength [info commands ::common_cdc::uncached_bank]]} {rename ::common_cdc::uncached_bank {}}
 rename ::common_cdc::bank ::common_cdc::uncached_bank
 proc ::common_cdc::bank {prefix width} {return [::board_prep::bank $prefix $width]}
 # Limit traversal to precisely the prefix already checked by the unchanged body.
 foreach {procname before after} {
  ::common_cdc::inactive {[get_cells -quiet -hier -filter {IS_PRIMITIVE == TRUE}]} {[get_cells -quiet -hier -filter "IS_PRIMITIVE == TRUE && NAME =~ $fifo/*"]}
  ::common_cdc::collect {[get_cells -quiet -hier]} {[get_cells -quiet -hier -filter "NAME =~ $root/*"]}
 } {
  set body [info body $procname]
  if {[string first $before $body]<0} {error "Missing exact traversal in $procname"}
  set arglist {}
  foreach arg [info args $procname] {if {[info default $procname $arg value]} {lappend arglist [list $arg $value]} else {lappend arglist $arg}}
  proc $procname $arglist [string map [list $before $after] $body]
 }
 foreach procname {::common_cdc::gray ::common_cdc::payload ::common_cdc::level ::common_cdc::mailbox} {
  trace add execution $procname enter board_prep::progress
 }
}
proc board_prep::entry {path install} {
 set f [open $path];set text [read $f];close $f
 set command {};set installed 0
 foreach line [split $text \n] {
  if {$command eq {} && ([string trim $line] eq {} || [string match {#*} [string trim $line]])} {continue}
  append command $line \n
  if {[info complete $command]} {
   if {$install && !$installed && [string match {common_media_apply*} [string trim $command]]} {install_cache_helpers;set installed 1}
   if {!$install && !$installed && [string match {valence_native_mac_assert_mode*} [string trim $command]]} {install_cache_helpers;set installed 1}
   puts "FORMAL_COMMAND [string trim $command]";flush stdout
   if {[catch {uplevel #0 $command} reason options]} {
    # Diagnostic-only: retain the failed common gate while checking independent
    # management/post_opt families. This mode always exits blocked, never PASS.
    if {$::valence(diagnostic_families) && [string trim $command] eq {common_cdc::constrain}} {
     lappend ::board_prep_failures [list phase $::valence(phase) reason $reason]
     common_log common-failure-$::valence(phase).txt "$reason\n[dict get $options -errorinfo]"
     puts "COMMON_GATE_BLOCKED_DIAGNOSTIC_CONTINUES_INDEPENDENT_FAMILIES $reason"
    } else {return -options $options $reason}
   }
   set command {}
  }
 }
 if {$command ne {} || !$installed} {error {Formal entry parse or cache-install anchor differs}}
}
puts "PREPARATION_TOOL [version -short]"
open_checkpoint $target
puts "FRESH_MAPPING_TARGET $target"
if {[catch {
 if {[llength $argv] ni {6 7}} {error {Required original IP implementation-constraint inventory missing}}
 if {[lindex $argv 5] eq {REUSE_HASH_VERIFIED_IP_RESTORED_CHECKPOINT}} {
  if {[file tail $target] ne {ip-restored-unqualified.dcp}} {error {Wrong restored-IP checkpoint name}}
  puts {REUSE_HASH_VERIFIED_IP_RESTORED_CHECKPOINT_NO_IP_REPLAY}
 } else {
 source [file normalize [lindex $argv 5]]
 foreach row $recovery_ip_xdc {
  lassign $row path ref cells order
  set options {}
  if {$ref ne {}} {
   set instances [get_cells -quiet -hier -filter "REF_NAME == $ref"]
   set adapted 0
   if {![llength $instances]} {
    set alternatives [get_cells -quiet -hier -filter "ORIG_REF_NAME == $ref"]
    if {[llength $alternatives]!=1} {error "Original IP reference absent/ambiguous, including ORIG_REF_NAME: $ref"}
    set instances $alternatives;set adapted 1
    puts "IP_SCOPE_ADAPTED original_ref=$ref actual_ref=[get_property REF_NAME $instances] actual_instance=[get_property NAME $instances] evidence=exact_unique_ORIG_REF_NAME"
   }
   foreach instance $instances {
    if {$cells ne {} && ![llength [get_cells -quiet [get_property NAME $instance]/$cells]]} {error "Original IP constraint child absent: $instance/$cells"}
   }
   if {$adapted} {
    set target_instance [get_property NAME $instances]
    if {$cells ne {}} {append target_instance / $cells}
    lappend options -cells $target_instance
   } else {
    lappend options -ref $ref
    if {$cells ne {}} {lappend options -cells $cells}
   }
  }
  puts "RESTORE_ORIGINAL_IP_XDC order=$order ref=$ref cells=$cells path=$path"
  read_xdc {*}$options $path
 }
 board_prep_save_checkpoint ip-restored-unqualified.dcp
 }
 update_timing
 report_clocks -file restored-clocks-before-media.rpt
 # Check the real functional UART clock. Synthesis specializes its redundant
 # top rawUartClock input to GND; it is not a functional clock endpoint.
 foreach {pin expected} {u_soc/cpuClock 3.333 u_soc/fabricClock 4.0 u_soc/peripherals/uart/uart/clock 20.0 u_soc/alwaysOnClock 20.0 u_ddr/c0_ddr4_ui_clk 4.0} {
  set p [get_pins -quiet $pin]
  if {[llength $p]!=1} {error "Restored actual clock pin absent/ambiguous: $pin"}
  set c [get_clocks -quiet -of_objects $p]
  if {![llength $c]} {set c [get_clocks -quiet -of_objects [get_nets -quiet -segments -of_objects $p]]}
  if {[llength $c]!=1} {
   set nets [get_nets -quiet -segments -of_objects $p]
   set drivers [get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}]
   set clock_evidence [list pin $pin clock_count [llength $c]]
   if {[llength $nets]} {lappend clock_evidence nets [get_property NAME $nets] types [get_property TYPE $nets]}
   if {[llength $drivers]} {lappend clock_evidence drivers [get_property NAME $drivers]}
   common_log missing-clock-evidence.tcllist $clock_evidence
   error "Restored actual clock absent/ambiguous at $pin count=[llength $c]"
  }
  if {abs([get_property PERIOD $c]-$expected)>0.002} {error "Restored actual clock differs at $pin actual=[get_property PERIOD $c] expected=$expected"}
  puts "ACTUAL_CLOCK_CONTRACT pin=$pin name=[get_property NAME $c] period=[get_property PERIOD $c]"
 }
 set alias_pin [get_pins -quiet u_soc/rawUartClock]
 if {[llength $alias_pin]==1 && ![llength [get_clocks -quiet -of_objects $alias_pin]]} {
  set alias_nets [get_nets -quiet -segments -of_objects $alias_pin]
  if {![llength $alias_nets] || [lsort -unique [get_property TYPE $alias_nets]] ne {GROUND}} {error {Unclocked raw-UART input is not the proved constant specialization}}
  puts {UNUSED_RAW_UART_INPUT_SPECIALIZED_GND_FUNCTIONAL_UART_CLOCK_VERIFIED_20NS}
 }
 source [file join $valence(root) fpga common debug_hub_clock.tcl]
 common_restore_debug_hub_clock zu15eg-existing-user1-debug-hub-tck50ns
 report_io -file restored-io.rpt
 board_prep::entry [file join $valence(root) fpga common post_synth.tcl] 1
 check_timing -verbose -file post-synth-coverage.rpt
 report_clocks -file post-synth-clocks.rpt
 write_xdc -force post-synth-memory-constraints.xdc
 if {$valence(diagnostic_implementation)} {
  if {[llength $::board_prep_failures]} {error {Incomplete actual CDC constraints; diagnostic optimization blocked}}
  board_prep::diagnostic_gate post-synth-coverage.rpt
  board_prep_save_checkpoint post-synth-constrained-diagnostic.dcp
  report_drc -ruledeck opt_checks -file diagnostic-preopt-drc.rpt
  if {[llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]} {error {Native opt DRC errors; see diagnostic-preopt-drc.rpt}}
  puts {DIAGNOSTIC_START_OPT_DESIGN_FINAL_SIGNOFF_PENDING};flush stdout
  opt_design
  set valence(phase) recovery_r1_actual_post_opt_diagnostic
 } else {set valence(phase) recovery_r1_post_opt_entry_diagnostic_without_opt}
 board_prep::entry [file join $valence(root) fpga common post_opt.tcl] 0
 check_timing -verbose -file post-opt-coverage.rpt
 report_clocks -file post-opt-clocks.rpt
 report_cdc -details -file post-opt-cdc.rpt
 write_xdc -force post-opt-memory-constraints.xdc
 if {$valence(diagnostic_implementation)} {
  if {[llength $::board_prep_failures]} {error {Incomplete actual post-opt CDC constraints}}
  board_prep::diagnostic_gate post-opt-coverage.rpt
  board_prep_save_checkpoint post-opt-constrained-diagnostic.dcp
  report_drc -file diagnostic-preplace-drc.rpt
  if {[llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]} {error {Native pre-place DRC errors; see diagnostic-preplace-drc.rpt}}
  puts {DIAGNOSTIC_START_PLACE_DESIGN_FINAL_SIGNOFF_PENDING};flush stdout
  place_design
  board_prep_save_checkpoint placed-diagnostic.dcp
  phys_opt_design
  puts {DIAGNOSTIC_START_ROUTE_DESIGN_FINAL_SIGNOFF_PENDING};flush stdout
  route_design
  board_prep_save_checkpoint routed-diagnostic-unqualified.dcp
  report_timing_summary -delay_type min_max -report_unconstrained -file diagnostic-timing.rpt
  report_utilization -file diagnostic-utilization.rpt
  report_route_status -file diagnostic-route.rpt
  report_bus_skew -delay_type min_max -file diagnostic-bus-skew.rpt
  report_cdc -details -file diagnostic-cdc.rpt
  report_drc -file diagnostic-drc.rpt
  check_timing -verbose -file diagnostic-coverage.rpt
  foreach {domain pin} {cpu u_soc/cpuClock fabric u_soc/fabricClock uart u_soc/peripherals/uart/uart/clock} {
   set clock [get_clocks -of_objects [get_pins $pin]]
   report_timing -from $clock -to $clock -delay_type max -max_paths 10 -file diagnostic-$domain-setup.rpt
   report_timing -from $clock -to $clock -delay_type min -max_paths 10 -file diagnostic-$domain-hold.rpt
  }
  set qsource [common_cdc::one get_pins {u_soc/peripherals/gmac/rxQuiesceRaw_sync/stages_reg[1]/C}]
  set qtarget [common_cdc::one get_pins u_soc/peripherals/gmac/agent_1/request_REG_reg/D]
  foreach kind {max min} {
   set path [get_timing_paths -quiet -from $qsource -to $qtarget -delay_type $kind -max_paths 1]
   if {[llength $path]!=1} {error "Missing normal shared-quiesce $kind timing path"}
   puts "QUIESCE_NORMAL_STA kind=$kind requirement=[get_property REQUIREMENT $path] slack=[get_property SLACK $path] exception=[get_property EXCEPTION $path]"
   report_timing -from $qsource -to $qtarget -delay_type $kind -max_paths 5 -file diagnostic-shared-quiesce-$kind.rpt
  }
  puts {DIAGNOSTIC_ROUTE_REPORTS_SAVED_NOT_BOARD_SIGNOFF_NO_BITSTREAM};flush stdout
 }
} reason options]} {
 common_log failure.txt "$reason\n[dict get $options -errorinfo]"
 puts "FORMAL_PREPARATION_BLOCKED $reason"
 catch {check_timing -verbose -file blocked-coverage.rpt}
 catch {report_clocks -file blocked-clocks.rpt}
 close_design
 exit 2
}
if {[llength $::board_prep_failures]} {
 common_log blocked-common-scopes.tcllist [join $::board_prep_failures \n]
 puts {FULL_BOARD_PREPARATION_BLOCKED_COMMON_GATE_RETAINED_NO_IMPLEMENTATION_PERMISSION}
 close_design
 exit 2
}
puts {FORMAL_ENTRIES_APPLIED_IN_MEMORY_ONLY_NO_PHYSICAL_QUALIFICATION_POST_OPT_MUST_REPEAT_AFTER_OPT}
close_design
exit 0
