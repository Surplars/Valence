package debug

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** A real executing core and production coherent DMA route, with synchronous DMI only. */
class JtagBootGsim extends Module {
    private val p = OooParams(robEntries = 16, physicalRegs = 48, memoryEntries = 2,
        branchPredictorEntries = 16, speculativeRamBase = BigInt("80020000", 16),
        speculativeRamBytes = 1024 * 1024, bufferedRamStores = true)
    val platform = Module(new MachinePlatform(p, romWords = 128, programmable = true,
        tileLinkMemory = true, tileLinkFetch = true, ramBytes = 1024 * 1024,
        translationService = true, coreDataTranslation = true, coreInstructionTranslation = true,
        registerPhysicalResponseOwners = true, stagedMemoryFabric = true,
        coherentLineCache = true, coherentLineCacheLines = 8, instructionLineCacheLines = 4,
        instructionLineCachePrefetch = false, jtagRamDownload = true))
    val io = IO(new Bundle {
        val hold = Input(Bool())
        val romWrite = Input(Bool())
        val romIndex = Input(UInt(7.W))
        val romData = Input(UInt(32.W))
        val ramWrite = Input(Bool())
        val ramIndex = Input(UInt(17.W))
        val ramData = Input(UInt(64.W))
        val dmi = Flipped(new soc.ip.debug.DebugDmiPort(7))
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val trap = Output(Valid(new HeadException(p)))
        val fetchPc = Output(UInt(64.W))
        val probeFire = Output(Bool())
        val probeOpcode = Output(UInt(3.W))
        val probeParam = Output(UInt(3.W))
        val probeAddress = Output(UInt(64.W))
        val probeData = Output(UInt(64.W))
        val invalidateFetch = Output(Bool())
        val lineFill = Output(Bool())
        val lineFillAddress = Output(UInt(64.W))
    })
    platform.io.timerTick := false.B
    platform.io.sources := 0.U
    platform.io.uartRx := true.B
    platform.io.commitEnable := true.B
    platform.io.translationFlush.get := false.B
    platform.io.jtagLinkUp.get := true.B
    platform.io.jtagDmi.get <> io.dmi
    platform.io.inspectRegister := io.inspectRegister
    platform.io.program.get.hold := io.hold
    platform.io.program.get.write := io.romWrite
    platform.io.program.get.index := io.romIndex
    platform.io.program.get.data := io.romData
    platform.io.ramProgram.get.write := io.ramWrite
    platform.io.ramProgram.get.index := io.ramIndex
    platform.io.ramProgram.get.data := io.ramData
    io.committedValue := platform.io.committedValue
    io.commit0 := platform.io.commit(0)
    io.commit1 := platform.io.commit(1)
    io.trap := platform.io.trap
    io.fetchPc := platform.io.fetchPc
    private val cache = platform.privateCache.get
    io.probeFire := BoringUtils.bore(cache.io.tl.c.valid) && BoringUtils.bore(cache.io.tl.c.ready)
    io.probeOpcode := BoringUtils.bore(cache.io.tl.c.bits.opcode)
    io.probeParam := BoringUtils.bore(cache.io.tl.c.bits.param)
    io.probeAddress := BoringUtils.bore(cache.io.tl.c.bits.address)
    io.probeData := BoringUtils.bore(cache.io.tl.c.bits.data)
    io.invalidateFetch := BoringUtils.bore(platform.core.io.invalidateFetch)
    io.lineFill := platform.io.activity.get.fetchGetFire && platform.io.activity.get.fetchGetSize === 6.U
    io.lineFillAddress := platform.io.activity.get.fetchGetAddress
}

object JtagBootGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new JtagBootGsim, Array("--target-dir", args.head))
}
