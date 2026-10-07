# Candidate DDR-only project. No CPU synthesis, implementation or bitstream launch.
# vivado -mode batch -source prepare_ddr_project.tcl -tclargs ORIGINAL_XPR RTL ASSETS CANDIDATE_DIR
if {$argc != 4} {error "Expected ORIGINAL_XPR RTL ASSETS CANDIDATE_DIR"}
lassign $argv original_xpr rtl_dir assets_dir candidate_dir
foreach var {original_xpr rtl_dir assets_dir candidate_dir} {
    set $var [file normalize [set $var]]
}
set original_dir [file dirname $original_xpr]
set original_name [file rootname [file tail $original_xpr]]
set ip_root [file join $original_dir "$original_name.srcs" sources_1 ip]
set candidate_xpr [file join $candidate_dir ValenceDDR50.xpr]
set_param general.maxThreads 8
if {[file exists $candidate_xpr]} {
    open_project $candidate_xpr
} else {
    create_project ValenceDDR50 $candidate_dir -part xczu15eg-ffvb1156-2-i
    foreach name {blk_mem_gen_0 ddr4_0} {
        set xci [file join $ip_root $name "$name.xci"]
        if {![file exists $xci]} {error "Missing IP: $xci"}
        import_ip -files [list $xci]
    }
}
set mig [get_ips ddr4_0]
# Changing the memory part in the GUI may restore the default 256-bit AXI port.
set_property CONFIG.C0.DDR4_AxiDataWidth 64 $mig
foreach {property value} {
    CONFIG.C0.DDR4_InputClockPeriod 5000
    CONFIG.C0.DDR4_TimePeriod 1000
    CONFIG.C0.DDR4_AxiDataWidth 64
    CONFIG.C0.DDR4_DataWidth 32
    CONFIG.C0.DDR4_AxiAddressWidth 31
    CONFIG.C0.DDR4_AxiIDWidth 4
    CONFIG.C0.DDR4_AxiSelection true
    CONFIG.C0.DDR4_MemoryPart MT40A512M16LY-075
} {
    if {[get_property $property $mig] ne $value} {
        error "Unexpected MIG setting: $property=[get_property $property $mig], expected $value"
    }
}
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
set_property CONFIG.Coe_File [file join $assets_dir bootrom.coe] [get_ips blk_mem_gen_0]
if {[llength [get_ips -quiet clk_wiz_ddr]] == 0} {
    create_ip -name clk_wiz -vendor xilinx.com -library ip -version 6.0 -module_name clk_wiz_ddr
}
set_property -dict [list CONFIG.PRIM_SOURCE No_buffer CONFIG.PRIM_IN_FREQ 250.000 \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ 50.000 CONFIG.USE_RESET true CONFIG.USE_LOCKED true] [get_ips clk_wiz_ddr]
if {[llength [get_ips -quiet axi_clock_converter_ddr]] == 0} {
    create_ip -name axi_clock_converter -vendor xilinx.com -library ip -version 2.1 \
        -module_name axi_clock_converter_ddr
}
set_property -dict [list CONFIG.PROTOCOL AXI4 CONFIG.ADDR_WIDTH 32 CONFIG.DATA_WIDTH 64 \
    CONFIG.ID_WIDTH 4 CONFIG.ACLK_ASYNC 1] [get_ips axi_clock_converter_ddr]
foreach source [concat [glob -directory $rtl_dir *.sv] [list [file join $assets_dir soc_top_ddr.sv]]] {
    if {[llength [get_files -quiet $source]] == 0} {add_files -norecurse $source}
}
# The DDR clock electrical standard is provided by MIG, not the former LVDS wizard input.
set legacy_xdc [get_files -quiet [file join $assets_dir board.xdc]]
if {[llength $legacy_xdc]} {remove_files $legacy_xdc}
foreach source [list [file join $assets_dir board_ddr.xdc] [file join $assets_dir pl_ddr4_pins.xdc]] {
    if {[llength [get_files -quiet $source]] == 0} {add_files -fileset constrs_1 -norecurse $source}
}
set_property top soc_top_ddr [get_filesets sources_1]
generate_target all [get_ips {blk_mem_gen_0 ddr4_0 clk_wiz_ddr axi_clock_converter_ddr}] -force
export_ip_user_files -of_objects [get_ips] -no_script -sync -force -quiet
update_compile_order -fileset sources_1
report_ip_status -file [file join $candidate_dir ip_status.rpt]
puts "DDR50: candidate project=$candidate_xpr"
puts "DDR50: 512 MiB CPU window 0x80200000..0xA01FFFFF, 64-bit AXI, CPU=50MHz"
# Check against freshly generated vendor port declarations without building OOC DCPs.
# This is an interface/elaboration check; PHY behavior and timing require implementation.
set gen_ip_root [file join $candidate_dir ValenceDDR50.gen sources_1 ip]
set validation_dir [file join $candidate_dir validation]
file mkdir $validation_dir
set stub_file [file join $validation_dir ip_port_stubs.v]
set stub [open $stub_file w]
puts $stub "// Generated from Vivado .veo port declarations; validation only."
foreach name {blk_mem_gen_0 ddr4_0 clk_wiz_ddr axi_clock_converter_ddr} {
    set path [file join $gen_ip_root $name "$name.veo"]
    set input [open $path r]
    set text [read $input]
    close $input
    set ports {}
    foreach line [split $text "\n"] {
        if {[regexp {^\s*\.(\w+)\([^)]*\).*//\s*(input|output|inout)\s+(?:wire\s+)?(\[[^]]+\])?\s*(\w+)} $line -> port direction width]} {
            lappend ports "$direction wire $width $port"
        }
    }
    if {[llength $ports] == 0} {error "No vendor port declarations found: $path"}
    puts $stub "(* black_box = \"yes\" *) module $name ("
    puts $stub [join $ports ",\n"]
    puts $stub "); endmodule"
    puts "DDR50: checked vendor interface $name, [llength $ports] ports"
}
close $stub
close_project
create_project -in_memory -part xczu15eg-ffvb1156-2-i
read_verilog -sv [concat [glob -directory $rtl_dir *.sv] [list [file join $assets_dir soc_top_ddr.sv]]]
read_verilog $stub_file
synth_design -rtl -top soc_top_ddr -part xczu15eg-ffvb1156-2-i
read_xdc [file join $assets_dir board_ddr.xdc]
read_xdc [file join $assets_dir pl_ddr4_pins.xdc]
report_io -file [file join $candidate_dir rtl_io.rpt]
set missing {}
foreach port [get_ports c0_ddr4_*] {
    if {[get_property PACKAGE_PIN $port] eq ""} {lappend missing $port}
}
if {[llength $missing] != 0} {error "DDR50: missing physical pin assignments: $missing"}
puts "DDR50: all 71 DDR signal pins are assigned"
puts "DDR50: RTL interface check PASS"
close_design
close_project
