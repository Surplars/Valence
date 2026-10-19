# Checkpoint the completed physical optimization before any router operation.
set i1_physopt_root [file normalize [file join [file dirname [info script]] ..]]
if {![string match */orbital-i1-cpu300-board-* $i1_physopt_root]} {
    error "Only the explicit isolated I1 board may save this checkpoint"
}
write_checkpoint [file join $i1_physopt_root reports real_board_post_place_physopt.dcp]
