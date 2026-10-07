# Configure sources and IP only. Does not launch CPU synthesis/implementation.
# Batch: vivado -mode batch -source configure_project.tcl -tclargs PROJECT RTL_DIR BOARD_DIR ?CLOCK_MHZ?
# GUI: set board_project ...; set board_rtl_dir ...; set board_asset_dir ...; source ...
if {![info exists board_project]} {
    set board_project {D:/TOOLS/projects/vivadoProjects/ZU15EG/ZU15EG.xpr}
}
if {![info exists board_rtl_dir]} {
    set board_rtl_dir {E:/VM/Share/Valence-rtl/board-40m}
}
if {![info exists board_asset_dir]} {
    set board_asset_dir [file join [file dirname $board_project] src board40]
}
if {[info exists argc] && $argc == 3} {
    lassign $argv board_project board_rtl_dir board_asset_dir
} elseif {[info exists argc] && $argc == 4} {
    lassign $argv board_project board_rtl_dir board_asset_dir board_clock_mhz
    # Four arguments are used only for an explicitly selected clock candidate.
}
if {[info exists board_clock_mhz]} {
    if {![string is double -strict $board_clock_mhz] ||
            $board_clock_mhz < 6.000 || $board_clock_mhz > 200.000} {
        error "board_clock_mhz must be in 6..200 MHz"
    }
}
foreach name {board_project board_rtl_dir board_asset_dir} {
    set $name [file normalize [set $name]]
}
set board_top_file [file join $board_asset_dir soc_top.sv]
set board_coe_file [file join $board_asset_dir bootrom.coe]
foreach required [list $board_project $board_top_file $board_coe_file \
        [file join $board_rtl_dir BoardSocTop.sv]] {
    if {![file exists $required]} {error "Missing required board input: $required"}
}
set board_sources [glob -nocomplain -directory $board_rtl_dir *.sv]
if {[llength $board_sources] < 5} {error "Incomplete board RTL export: $board_rtl_dir"}

set board_opened_here 0
if {[current_project -quiet] eq ""} {
    open_project $board_project
    set board_opened_here 1
} else {
    set active_xpr [file normalize [file join [get_property DIRECTORY [current_project]] \
        "[get_property NAME [current_project]].xpr"]]
    if {![string equal -nocase $active_xpr $board_project]} {
        error "A different Vivado project is open: $active_xpr"
    }
}
if {[get_property PART [current_project]] ne "xczu15eg-ffvb1156-2-i"} {
    error "Unexpected FPGA part; this profile is for xczu15eg-ffvb1156-2-i"
}
set board_rom [get_ips -quiet blk_mem_gen_0]
set board_clock [get_ips -quiet clk_wiz_0]
if {[llength $board_rom] != 1 || [llength $board_clock] != 1} {
    error "The project must already contain blk_mem_gen_0 and clk_wiz_0"
}
set_param general.maxThreads 8
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]

# Remove project references only, never delete snapshots, source files, or reports.
# Preserve all unrelated user HDL, XDC, and IP sources.
foreach source [get_files -quiet -of_objects [get_filesets sources_1]] {
    set normalized [string map {\\ /} [get_property NAME $source]]
    if {[string match -nocase */Valence-rtl/*.sv $normalized] ||
            [string equal -nocase [file tail $normalized] soc_top.sv]} {
        remove_files $source
    }
}
add_files -norecurse -fileset sources_1 $board_sources
add_files -norecurse -fileset sources_1 $board_top_file
set_property top soc_top [get_filesets sources_1]

# Both ROM ports share the SoC clock. Disable optional output registers:
# the Chisel adapter expects exactly one native ROM read cycle.
set_property -dict [list \
    CONFIG.Interface_Type Native \
    CONFIG.Memory_Type Dual_Port_ROM \
    CONFIG.Write_Width_A 32 CONFIG.Read_Width_A 32 \
    CONFIG.Write_Depth_A 32768 \
    CONFIG.Write_Width_B 32 CONFIG.Read_Width_B 32 \
    CONFIG.Enable_A Use_ENA_Pin CONFIG.Enable_B Use_ENB_Pin \
    CONFIG.Assume_Synchronous_Clk true \
    CONFIG.Register_PortA_Output_of_Memory_Primitives false \
    CONFIG.Register_PortB_Output_of_Memory_Primitives false \
    CONFIG.Register_PortA_Output_of_Memory_Core false \
    CONFIG.Register_PortB_Output_of_Memory_Core false \
    CONFIG.Use_REGCEA_Pin false CONFIG.Use_REGCEB_Pin false \
    CONFIG.Use_RSTA_Pin false CONFIG.Use_RSTB_Pin false \
    CONFIG.Load_Init_File true CONFIG.Coe_File $board_coe_file] $board_rom
if {[info exists board_clock_mhz]} {
    set_property CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $board_clock_mhz $board_clock
}
generate_target all [get_ips {blk_mem_gen_0 clk_wiz_0}] -force
export_ip_user_files -of_objects [get_ips {blk_mem_gen_0 clk_wiz_0}] -no_script -sync -force -quiet
update_compile_order -fileset sources_1
report_ip_status
puts "BOARD40: top=[get_property TOP [get_filesets sources_1]]"
puts "BOARD40: clock=[get_property CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $board_clock] MHz"
puts "BOARD40: ROM=128 KiB, 32768 x 32, dual native read ports, 1-cycle reads"
puts "BOARD40: ROM image=[get_property CONFIG.Coe_File $board_rom]"
puts "BOARD40: RAM=1 MiB at 0x80200000, XPM UltraRAM, 3-cycle reads"
puts "BOARD40: sources=$board_rtl_dir"
puts "BOARD40: CPU synthesis needs refresh=[get_property NEEDS_REFRESH [get_runs synth_1]]"
puts "BOARD40: configuration complete; no CPU synthesis or bitstream build was launched"
if {$board_opened_here} {close_project}
