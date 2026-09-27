package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class FpgaFetchGsim(compressedCache: Boolean = false) extends Module {
    val p  = OooParams(robEntries = 8, physicalRegs = 36)
    val io = IO(new Bundle {
        val write        = Input(Bool())
        val writeIndex   = Input(UInt(8.W))
        val writeData    = Input(UInt(32.W))
        val rom          = Flipped(new InstructionPort)
        val pc           = Input(UInt(64.W))
        val enable       = Input(Bool())
        val invalidate   = Input(Bool())
        val pmpCfg0      = Input(UInt(8.W))
        val pmpAddr0     = Input(UInt(54.W))
        val privilege    = Input(UInt(2.W))
        val pause        = Input(Bool())
        val quiescent    = Output(Bool())
        val fetch        = new InstructionPort
        val instruction0 = Output(Valid(UInt(32.W)))
        val instruction1 = Output(Valid(UInt(32.W)))
        val instructionFault0 = Output(Bool())
        val instructionFault1 = Output(Bool())
        val bootHold     = Input(Bool())
        val commitEnable = Input(Bool())
        val commit0      = Output(Valid(new CommitRecord(p)))
        val commit1      = Output(Valid(new CommitRecord(p)))
        val exception    = Output(Valid(new HeadException(p)))
    })
    val rom = Module(new InstructionRom(256, BigInt("80000000", 16), programmable = true))
    rom.io.fetch <> io.rom
    val frontend = Module(new SynchronousFetch(16, compressed = compressedCache,
        cacheSets = if (compressedCache) 8 else 64))
    frontend.io.pc     := io.pc
    frontend.io.enable := io.enable
    frontend.io.invalidate := io.invalidate
    frontend.io.pause := io.pause
    val pmpState = WireDefault(0.U.asTypeOf(new PmpState))
    pmpState.cfg(0) := io.pmpCfg0
    pmpState.addr(0) := io.pmpAddr0
    frontend.io.pmpState := pmpState
    frontend.io.privilege := io.privilege
    frontend.io.virtualized := false.B
    io.quiescent := frontend.io.quiescent
    io.fetch <> frontend.io.memory
    io.instruction0 := frontend.io.instruction0
    io.instruction1 := frontend.io.instruction1
    io.instructionFault0 := frontend.io.instructionFaults(0)
    io.instructionFault1 := frontend.io.instructionFaults(1)
    val core = Module(new FpgaIntegerCore(p))
    core.reset := reset.asBool || io.bootHold
    val program = Module(new InstructionRom(256, BigInt("80000000", 16), programmable = true))
    program.io.fetch <> core.io.fetch
    for (m <- Seq(rom, program)) {
        m.io.write.get.valid      := io.write
        m.io.write.get.bits.index := io.writeIndex
        m.io.write.get.bits.data  := io.writeData
    }
    core.io.commitEnable          := io.commitEnable
    core.io.memory.request.ready  := false.B
    core.io.memory.response.valid := false.B
    core.io.memory.response.bits  := 0.U.asTypeOf(new DataResponse)
    io.commit0                    := core.io.commit(0)
    io.commit1                    := core.io.commit(1)
    io.exception                  := core.io.exception
}
object FpgaFetchGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FpgaFetchGsim(args.lift(1).contains("compressed-cache")),
        Array("--target-dir", args.head))
}
