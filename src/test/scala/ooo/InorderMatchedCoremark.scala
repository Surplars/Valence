package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
import soc.core.inorder._

/** Matched bare integer OoO baseline, not a replacement or full VL100 board qualification.
  * Both benchmark cores use identical cache RTL and a shared host service law. A 64-bit IF word
  * supplies two RV64IM instructions when PC is 8-byte aligned, otherwise a contiguous one-word prefix.
  * No C/F/D/Sv39 or UART, but no changes to the two-issue OoO backend either.
  */
class InorderMatchedOooCoremark extends Module {
    val cp = FiveStageConfig(instructionCacheBytes = 2048, dataCacheBytes = 2048)
    val p = OooParams(renameWidth = 2, commitWidth = 2, completionWidth = 2,
        robEntries = 32, physicalRegs = 64, memoryEntries = 4, storeBufferEntries = 4,
        branchPredictorEntries = 64, speculativeRamBase = BigInt("80010000", 16),
        speculativeRamBytes = 8192, bufferedRamStores = true, machineSystem = true)
    val io = IO(new Bundle {
        val instructionMemory = new FiveStageBurstPort(cp)
        val dataMemory = new FiveStageBurstPort(cp)
        // Explicit ports: pinned GSIM's exported Vec getters lose the lane index.
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val exception = Output(Valid(new HeadException(p)))
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val instructionHit = Output(Bool())
        val instructionMiss = Output(Bool())
        val dataHit = Output(Bool())
        val dataMiss = Output(Bool())
        val debugFetchPc = Output(UInt(64.W))
        val debugRecovering = Output(Bool())
        val debugFenceFlush = Output(Bool())
        val debugOccupancy = Output(UInt(p.countBits.W))
        val debugMemoryBusy = Output(Bool())
    })
    val core = Module(new IntegerCore(p))
    val icache = Module(new FiveStageWordCache(cp, 2048, allowHitReplacement = true))
    val dcache = Module(new FiveStageWordCache(cp, 2048))
    io.instructionMemory <> icache.io.memory; io.dataMemory <> dcache.io.memory
    val invalidate = core.io.invalidateFetch || core.io.fenceIFlush.get
    icache.io.invalidate := invalidate
    dcache.io.invalidate := false.B
    core.io.commitEnable := true.B; core.io.inspectRegister := io.inspectRegister
    core.io.externalInterrupt.get := false.B; core.io.supervisorExternalInterrupt.get := false.B
    core.io.timerInterrupt.get := false.B; core.io.timeValue.get := 0.U
    core.io.imsic.get.request.ready := true.B
    core.io.imsic.get.response.valid := false.B
    core.io.imsic.get.response.bits := 0.U.asTypeOf(core.io.imsic.get.response.bits)
    io.commit0 := core.io.commit(0); io.commit1 := core.io.commit(1)
    // Machine mode consumes the bare head exception internally and publishes a precise trap.
    io.exception := core.io.trap.get; io.committedValue := core.io.committedValue
    io.debugFetchPc := core.io.fetchPc; io.debugRecovering := core.io.recovering
    io.debugFenceFlush := core.io.fenceIFlush.get; io.debugOccupancy := core.io.occupancy
    io.debugMemoryBusy := core.io.memoryBusy
    val bufferValid = RegInit(false.B)
    val bufferAddress = Reg(UInt(64.W))
    val bufferData = Reg(UInt(64.W))
    val bufferError = Reg(Bool())
    val pending = RegInit(false.B)
    val pendingAddress = Reg(UInt(64.W))
    val offerValid = RegInit(false.B)
    val offerAddress = Reg(UInt(64.W))
    val currentWord = (core.io.fetchPc >> 3) << 3
    val buffered = bufferValid && bufferAddress === currentWord
    val returning = pending && pendingAddress === currentWord && icache.io.response.valid
    val present = (buffered || returning) && !core.io.recovering && !invalidate
    val suppliedData = Mux(returning, icache.io.response.bits.data, bufferData)
    val suppliedError = Mux(returning, icache.io.response.bits.error, bufferError)
    icache.io.request.valid := offerValid || (!pending && !buffered && !core.io.recovering && !invalidate)
    core.io.fenceIFlushReady.get := !pending && !offerValid
    icache.io.request.bits := 0.U.asTypeOf(new FiveStageDataRequest(cp))
    icache.io.request.bits.address := Mux(offerValid, offerAddress, currentWord)
    icache.io.request.bits.size := 3.U
    when(icache.io.request.valid && !icache.io.request.ready && !offerValid) {
        offerValid := true.B; offerAddress := currentWord
    }
    when(icache.io.request.fire) {
        pending := true.B; pendingAddress := icache.io.request.bits.address; offerValid := false.B
    }
    icache.io.response.ready := pending
    when(icache.io.response.fire) {
        bufferValid := true.B; bufferAddress := pendingAddress; bufferData := icache.io.response.bits.data
        bufferError := icache.io.response.bits.error; pending := false.B
    }
    when(invalidate) { bufferValid := false.B }
    core.io.instructions(0).valid := present
    core.io.instructions(0).bits := Mux(core.io.fetchPc(2), suppliedData(63, 32), suppliedData(31, 0))
    core.io.instructions(1).valid := present && !core.io.fetchPc(2)
    core.io.instructions(1).bits := suppliedData(63, 32)
    core.io.instructionFaults.foreach(_ := suppliedError)
    core.io.instructionPageFaults.foreach(_ := false.B)
    dcache.io.request.valid := core.io.memory.request.valid
    core.io.memory.request.ready := dcache.io.request.ready
    dcache.io.request.bits.address := core.io.memory.request.bits.address
    dcache.io.request.bits.write := core.io.memory.request.bits.write
    dcache.io.request.bits.size := core.io.memory.request.bits.size
    dcache.io.request.bits.data := core.io.memory.request.bits.data
    dcache.io.request.bits.mask := core.io.memory.request.bits.mask
    core.io.memory.response.valid := dcache.io.response.valid
    dcache.io.response.ready := core.io.memory.response.ready
    core.io.memory.response.bits.data := dcache.io.response.bits.data
    core.io.memory.response.bits.error := dcache.io.response.bits.error
    core.io.memory.response.bits.pageFault := false.B
    when(core.io.memory.request.fire) {
        assert(!core.io.memory.request.bits.atomic && !core.io.memory.request.bits.virtualized &&
            !core.io.memory.request.bits.uncached, "benchmark adapter only supports ordinary physical memory")
    }
    io.instructionHit := icache.io.hit; io.instructionMiss := icache.io.miss
    io.dataHit := dcache.io.hit; io.dataMiss := dcache.io.miss
}

object InorderMatchedOooCoremarkMain extends App {
    ChiselStage.emitCHIRRTLFile(new InorderMatchedOooCoremark, Array("--target-dir", args.head))
}
