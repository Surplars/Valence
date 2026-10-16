set root [file normalize [lindex $argv 0]]
set V_SOC_ROOT u_soc
set out [file join $root run-postroute-physopt-r1]
proc diag_event {stage status {detail {}}} {
 set stamp [clock format [clock seconds] -gmt 1 -format {%Y-%m-%dT%H:%M:%SZ}]
 set f [open events.tsv a];puts $f [join [list $stamp [pid] $stage $status $detail] \t];close $f
 puts "DIAG_EVENT $stamp PID=[pid] $stage $status $detail";flush stdout
}
source [file join $root run-r28-scenario-100 report-procedures.tcl]
if {[catch {source [file join $root orchestration postroute-physopt-r1.tcl]} why options]} {
 if {![file isdirectory $out]} {file mkdir $out}
 cd $out
 set f [open entry-failure.txt w];puts $f $why;puts $f [dict get $options -errorinfo];close $f
 diag_event postroute_session failed_retained $why
}
file mkdir [file join $out commands]
cd $out
while {![file exists SESSION_EXIT.txt]} {
 foreach command [lsort [glob -nocomplain commands/*.tcl]] {
  if {[file exists ${command}.started]} {continue}
  set f [open ${command}.started w];puts $f [clock seconds];close $f
  diag_event command begin $command
  if {[catch {source $command} why options]} {
   set f [open ${command}.error.txt w];puts $f $why;puts $f [dict get $options -errorinfo];close $f
   diag_event command failed $why
  } else {diag_event command complete $command}
 }
 after 1000
}
exit 0
