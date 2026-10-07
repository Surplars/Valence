# Refresh ONLY the two small IP checkpoints; never launch synth_1 or impl_1.
source [file join [file dirname [info script]] configure_project.tcl]
set refresh_close_project 0
if {[current_project -quiet] eq ""} {
    open_project $board_project
    set refresh_close_project 1
}
foreach name {blk_mem_gen_0_synth_1 clk_wiz_0_synth_1} {
    if {[llength [get_runs -quiet $name]] != 1} {error "Missing IP run: $name"}
    reset_run $name
}
launch_runs {blk_mem_gen_0_synth_1 clk_wiz_0_synth_1} -jobs 2
foreach name {blk_mem_gen_0_synth_1 clk_wiz_0_synth_1} {
    wait_on_run $name
    set status [get_property STATUS [get_runs $name]]
    puts "BOARD40: $name -> $status"
    if {![string match *Complete* $status]} {error "IP synthesis failed: $name"}
}
puts "BOARD40: CPU synthesis needs refresh=[get_property NEEDS_REFRESH [get_runs synth_1]]"
puts "BOARD40: IP checkpoint refresh finished; CPU synthesis/implementation NOT launched"
if {$refresh_close_project} {close_project}
