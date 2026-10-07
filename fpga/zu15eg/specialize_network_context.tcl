# Apply only independently proven parent-RTL constants/aliases inside the leaf.
if {$argc!=2} {error "Expected PRIVATE_ROOT TOP"}
lassign $argv root top
set root [file normalize $root]
if {$top ni {CoherentLineCache EthernetPacketDma}} {error "Unknown context partition"}
set out [file join $root partitions-context $top]
if {[file exists [file join $out leaf.edf]] || [file exists [file join $out leaf.dcp]]} {error "Preserve prior specialized netlist"}
file mkdir $out
set_param general.maxThreads 8
create_project -in_memory -part xczu15eg-ffvb1156-2-i
set named [file join $out ${top}.edf]
if {![file exists $named]} {file copy [file join $root partitions $top leaf_alias.edf] $named}
read_edif $named
link_design -top $top -part xczu15eg-ffvb1156-2-i -mode out_of_context
set f [open [file join $root context-proof $top.tcldict] r]
set rules [read $f]; close $f
foreach {reference suffix pin} {GND zero G VCC one P} {
    create_cell -reference $reference eco_context_$suffix
    create_net eco_context_${suffix}_net
    connect_net -net eco_context_${suffix}_net -objects [get_pins eco_context_$suffix/$pin]
}
set report [open [file join $out context_connections.txt] w]
dict for {name rule} $rules {
    lassign $rule mode value
    set port [get_ports -quiet $name]
    set nets [get_nets -quiet -of_objects $port]
    if {[llength $port]!=1} {error "Missing exact original OOC input port $name"}
    if {![llength $nets]} {puts $report "PROVEN_CONTEXT_UNUSED_OOC_PORT $name $mode $value"; continue}
    if {[llength $nets]!=1} {error "Ambiguous original OOC input net $name"}
    set sinks [get_pins -quiet -of_objects $nets -filter {DIRECTION == IN}]
    if {![llength $sinks]} {error "Expected functional original OOC loads for $name"}
    disconnect_net -net $nets -objects $port
    disconnect_net -net $nets -objects $sinks
    if {$mode eq "CONST"} {
        if {$value ni {0 1}} {error "Unknown constant"}
        set target [expr {$value eq "0" ? "eco_context_zero_net" : "eco_context_one_net"}]
    } elseif {$mode eq "ALIAS"} {
        set target [get_nets -of_objects [get_ports $value]]
        if {[llength $target]!=1} {error "Missing proven equivalent input $value"}
    } else {error "Unknown context operation"}
    connect_net -net $target -objects $sinks
    puts $report "PROVEN_CONTEXT $name $mode $value SINKS=$sinks"
}
close $report
write_edif [file join $out leaf.edf]
write_checkpoint [file join $out leaf.dcp]
puts "PASS_PARENT_RTL_SPECIALIZED_LEAF $top"
close_project
