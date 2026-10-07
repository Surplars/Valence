# Recover the exact old ROM reference from a preserved SoC checkpoint.
# Useful when the original project IP output products have been moved/deleted.
if {$argc != 2} {error "Expected SOC_DCP OUTPUT_ROM_DCP"}
lassign $argv soc out
open_checkpoint $soc
set rom [get_cells -quiet platform/rom/memory]
if {[llength $rom] != 1 || [get_property IS_BLACKBOX $rom]} {error "Missing implemented native ROM"}
write_checkpoint -cell $rom $out
close_design
puts "ROM_EXTRACT: complete $out"
