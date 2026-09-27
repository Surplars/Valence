package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class AtomicCoreGsim(p: OooParams, cached: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val instruction0      = Input(Valid(UInt(32.W)))
        val instruction1      = Input(Valid(UInt(32.W)))
        val accepted0         = Output(Bool())
        val accepted1         = Output(Bool())
        val redirect          = Output(Valid(new FrontendRedirect(p)))
        val fetchPc           = Output(UInt(64.W))
        val commitEnable      = Input(Bool())
        val commit0           = Output(Valid(new CommitRecord(p)))
        val commit1           = Output(Valid(new CommitRecord(p)))
        val exception         = Output(Valid(new HeadException(p)))
        val memoryBusy        = Output(Bool())
        val memory            = new DataPort
        val dma               = Flipped(new DataPort)
        val clearReservation  = Input(Bool())
        val cpuRequest        = Output(Valid(new DataRequest))
        val cpuResponse       = Output(Bool())
        val decodeInstruction = Input(UInt(32.W))
        val decodeLegal       = Output(Bool())
        val decoded           = Output(new IntegerRequest)
    })
    val core   = Module(new IntegerCore(p))
    val memory = Module(new AtomicDataMemory(p.speculativeRamBase, p.speculativeRamBytes.toInt))
    memory.io.cpu <> core.io.memory
    memory.io.dma <> io.dma
    if (cached) {
        val cache = Module(new CachedDataMemory)
        cache.io.upstream <> memory.io.memory
        io.memory <> cache.io.memory
    } else io.memory <> memory.io.memory
    memory.io.clearReservation := io.clearReservation || core.io.exception.valid
    core.io.instructions(0)    := io.instruction0
    core.io.instructions(1)    := io.instruction1
    core.io.instructionFaults   := VecInit(Seq.fill(p.renameWidth)(false.B))
    core.io.instructionPageFaults := VecInit(Seq.fill(p.renameWidth)(false.B))
    core.io.commitEnable       := io.commitEnable
    core.io.inspectRegister    := 0.U
    io.accepted0               := core.io.accepted(0)
    io.accepted1               := core.io.accepted(1)
    io.redirect                := core.io.redirect
    io.fetchPc                 := core.io.fetchPc
    io.commit0                 := core.io.commit(0)
    io.commit1                 := core.io.commit(1)
    io.exception               := core.io.exception
    io.memoryBusy              := core.io.memoryBusy
    io.cpuRequest.valid        := memory.io.cpu.request.fire
    io.cpuRequest.bits         := memory.io.cpu.request.bits
    io.cpuResponse             := memory.io.cpu.response.fire
    val decode = Module(new IntegerDecode(enableAtomic = true))
    decode.io.instruction := io.decodeInstruction
    decode.io.pc          := 0.U
    io.decodeLegal        := decode.io.legal
    io.decoded            := decode.io.decoded
}
object AtomicCoreGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(
        new AtomicCoreGsim(
            OooParams(
                robEntries = args(1).toInt,
                physicalRegs = args(2).toInt,
                atomicMemory = true,
                speculativeRamBase = BigInt("80010000", 16),
                speculativeRamBytes = 4096,
                bufferedRamStores = true
            ),
            cached = args.lift(4).contains("cache")
        ),
        Array("--target-dir", args.head)
    )
}
