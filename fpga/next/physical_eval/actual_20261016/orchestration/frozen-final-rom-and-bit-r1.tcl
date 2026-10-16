# Explicitly authorized local bit generation from the immutable final1000 DCP.
set out [file join $::root run-postroute-physopt-r1]
cd $out
set frozenDcp [file join $out postroute-final.dcp]
diag_event final_bit_preparation begin {USER_AUTHORIZED_BIT_LOCAL_ONLY_NO_PROGRAMMING_NO_NEW_IMPLEMENTATION}
puts [exec {D:/TOOLS/ENV/anaconda3/python.exe} -I -B [file join $::root orchestration verify_final_bit_timing.py] $::root]
close_project
open_checkpoint $frozenDcp
set cpuClock [get_clocks -of_objects [get_pins u_soc/clock]]
set uartClock [get_clocks -of_objects [get_pins u_soc/io_alwaysOnClock]]
if {abs([get_property PERIOD $cpuClock]-10.0)>0.001 || abs([get_property PERIOD $uartClock]-20.0)>0.001 || abs([get_property PERIOD [get_clocks phy_rx]]-8.0)>0.001} {error {Frozen bit input clocks mismatch}}
set pkg [file join $::root package combined-timing-repair-transfer-r1]
source [file join $pkg source fpga next physical_eval r3_common.tcl]
source [file join $::root external-rom-polarity-minimal-r3 r3_rom_graph_leaf_r3.tcl]
source [file join $::root rom-preflight-official-r3 local-rom-contract.tcl]
set V_ROM_ROOT [r3_ref InstructionRom]
diag_event rom_final_bit begin
set dump [file join $out rom-final-bit.tsv]
r3_rom_actual_dump $dump
set decoderRoot [string trim [exec {D:/TOOLS/ENV/anaconda3/python.exe} -I -B [file join $::root orchestration prepare_rom_decoder.py] $::root final-bit $frozenDcp]]
puts [exec {D:/TOOLS/ENV/anaconda3/python.exe} -I -B [file join $pkg source fpga next physical_eval verify_combined_rom_graph.py] $decoderRoot $dump --rom-sha256 ee7c2e5fb86d50dad55df532aeb7ccb1d0b91cb37b0b7042d03b446eee362d79 --padded-sha256 0d03f41230ed458e133d9503acba36edb34689f5aaa6cafd41ea2f81ec5879fd --report [file join $out rom-final-bit.json]]
diag_event rom_final_bit passed {ACTUAL64CLOCK_LEAVES_58BRAM_CLOCK_PINS_AND_32768_WORD_INIT_CHECK}
set bitDir [file join $::root bitstream-final-r1]
file mkdir $bitDir
set bitPath [file join $bitDir Valence-50cb-7dc9-cpu100-uart460800-user2.bit]
if {[file exists $bitPath]} {error {Preserve existing bit; refusing overwrite}}
set_param general.maxThreads 8
diag_event write_bitstream actual_begin [list command [list write_bitstream $bitPath] frozenDcpSha256 23a4edd50f0c4852f89ffb549f5ba9d2c51dc2019f546479b1dbe538ce102743]
write_bitstream $bitPath
diag_event write_bitstream actual_end [list path $bitPath LOCAL_ONLY_NOT_PROGRAMMED]
