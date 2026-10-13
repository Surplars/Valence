# Current GSIM board entries

Current board entry contract: the generic `fpga_next_board.py` runner is
preflight-only on this source. Execution fails before outputs or builds because
its historical emitter cannot select the required matching tri-speed/USER2
assembly. Use `ooo.CpuMatchingBoardProfileGsimMain` with the exact default52 or
optional53 vector; see [current board entries](../../fpga/next/README.md#current-board-entries).
The source-only entry repair preserves historical evidence and adds no hardware
qualification. Older experiment instructions retain their original source scope.
