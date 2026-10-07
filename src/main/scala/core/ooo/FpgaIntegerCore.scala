package soc.core.ooo

import chisel3._
import chisel3.util._

/** FPGA-oriented synchronous instruction memory boundary; data memory remains an external ordered port. */
class FpgaIntegerCore(p: OooParams = OooParams()) extends Module {
    require(Set(2, 4).contains(p.renameWidth))
    require(p.virtualMemoryLevels == 0, "FPGA standalone wrapper has no translation service")
    private val fetchWords = if (p.compressedInstructions && p.renameWidth == 4) 4 else 2
    val io = IO(new Bundle {
        val fetch        = new InstructionPort(fetchWords)
        val memory       = new DataPort
        val commitEnable = Input(Bool())
        val commit       = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val exception    = Output(Valid(new HeadException(p)))
        val memoryBusy   = Output(Bool())
        val fetchWait    = Output(Bool())
    })
    val core     = Module(new IntegerCore(p))
    val frontend = Module(new SynchronousFetch(p.pmpEntries, p.compressedInstructions, p.frontendCacheSets,
        p.renameWidth, stableFaultMetadata = p.stableFetchFaultMetadata, alignedFetchPmp = p.alignedFetchPmp,
        rawFetchPresence = p.rawFetchPresence, parallelFetchTagLookup = p.parallelFetchTagLookup,
        parallelAlignment = p.parallelFetchAlignment, registeredWindow = p.registeredFetchWindow))
    frontend.io.pc     := core.io.fetchPc
    frontend.io.enable := !core.io.exception.valid
    frontend.io.invalidate := core.io.invalidateFetch
    frontend.io.pause := (if (p.pmpEntries > 0) core.io.pauseFetch.get else false.B)
    frontend.io.pmpState := (if (p.pmpEntries > 0) core.io.pmpState.get else 0.U.asTypeOf(new PmpState))
    frontend.io.privilege := (if (p.pmpEntries > 0) core.io.fetchPrivilege.get else 3.U)
    frontend.io.virtualized := false.B
    core.io.fetchQuiescent.foreach(_ := frontend.io.quiescent)
    io.fetch <> frontend.io.memory
    core.io.instructions := frontend.io.instructions
    core.io.instructionFaults := frontend.io.instructionFaults
    core.io.instructionPageFaults := frontend.io.instructionPageFaults
    core.io.instructionFaultAddresses.foreach(_ := frontend.io.instructionFaultAddresses)
    core.io.commitEnable    := io.commitEnable
    core.io.inspectRegister := 0.U
    io.memory <> core.io.memory
    io.commit     := core.io.commit
    io.exception  := core.io.exception
    io.memoryBusy := core.io.memoryBusy
    io.fetchWait  := !core.io.exception.valid && !frontend.io.instruction0.valid
}
