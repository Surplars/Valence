# Source in an IDLE existing custom-BSCAN OpenOCD console. No init/reset/scans.
# An uncertain transport must be drained or board-reset/OpenOCD-restarted first.
if {![info exists ::VALENCE_RAM_BACKEND] || $::VALENCE_RAM_BACKEND ne "bscan"} {
    error "Load the verified board/custom BSCAN configuration first; this upgrade does not configure an adapter"
}
set valence_upgrade_directory [file dirname [info script]]
source [file join $valence_upgrade_directory ram-loader.tcl]
source [file join $valence_upgrade_directory ram-loader-bscan.tcl]
::valence_ram::validate_xczu15eg_configuration
unset valence_upgrade_directory
::valence_ram::say "Fast host loader loaded; no board action performed, adapter speed unchanged. Reset board before a new download."
::valence_ram::say "valence_download_and_run FILE ENTRY ?fast|safe?; full readback and single COMMIT retained."
