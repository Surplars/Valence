source [file join $valence(root) fpga common producer_common.tcl]
open_checkpoint [file join $valence(root) local-run synthesis synthesized.dcp]
common_design_step opt_design
source $valence(post_opt_constraints)
common_design_step place_design
common_design_step phys_opt_design
common_design_step route_design
write_checkpoint routed.dcp
report_utilization -file utilization.rpt
# No bit here. Complete same-checkpoint signoff is a separate mandatory stage.
common_receipt
close_design
