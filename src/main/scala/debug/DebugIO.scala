package soc.debug

import chisel3._

class DebugIO extends Bundle {
    val pc = Output(UInt(64.W))
    val instr = Output(UInt(32.W))
    val retire = Output(Bool())
    val stall = Output(Bool())
    val ifetchStall = Output(Bool())
    val frontendStarved = Output(Bool())
    val frontendQueueFull = Output(Bool())
    val frontendQueueEmpty = Output(Bool())
    val lsuStall = Output(Bool())
    val lsuLoadStall = Output(Bool())
    val lsuStoreStall = Output(Bool())
    val lsuMmioStall = Output(Bool())
    val lsuAtomicStall = Output(Bool())
    val lsuFenceStall = Output(Bool())
    val fenceIActive = Output(Bool())
    val branchValid = Output(Bool())
    val branchTaken = Output(Bool())
    val branchRedirect = Output(Bool())
    val branchPredTaken = Output(Bool())
    val branchPredCorrect = Output(Bool())
    val commitPc = Output(UInt(64.W))
    val commitInstr = Output(UInt(32.W))
    val commitInstrLen = Output(UInt(2.W))
    val commitWen = Output(Bool())
    val commitWdest = Output(UInt(5.W))
    val commitWdata = Output(UInt(64.W))
    val commitSkip = Output(Bool())
}

class DebugCacheControl extends Bundle {
    val dcacheReq = Output(Bool())
    val icacheReq = Output(Bool())
    val dcacheAck = Input(Bool())
    val icacheAck = Input(Bool())
    val dcacheBusy = Input(Bool())
    val icacheBusy = Input(Bool())
    val dcacheErr = Input(Bool())
    val icacheErr = Input(Bool())
}
