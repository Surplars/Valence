package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class SynchronousPlatformGsim extends Module {
    val p = OooParams(speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 4096, bufferedRamStores = true)
    val io = IO(new Bundle {
        val hostMode     = Input(Bool())
        val host         = Flipped(new DataPort)
        val write        = Input(Bool())
        val writeIndex   = Input(UInt(10.W))
        val writeData    = Input(UInt(32.W))
        val commitEnable = Input(Bool())
        val commit0      = Output(Valid(new CommitRecord(p)))
        val commit1      = Output(Valid(new CommitRecord(p)))
        val exception    = Output(Valid(new HeadException(p)))
        val memoryBusy   = Output(Bool())
        val fetchWait    = Output(Bool())
        val dataRequest  = Output(Valid(new DataRequest))
    })
    val core = Module(new FpgaIntegerCore(p))
    core.reset := reset.asBool || io.hostMode
    val rom = Module(new InstructionRom(1024, BigInt("80000000", 16), programmable = true))
    val ram = Module(new SynchronousDataRam())
    rom.io.fetch <> core.io.fetch
    rom.io.write.get.valid      := io.write
    rom.io.write.get.bits.index := io.writeIndex
    rom.io.write.get.bits.data  := io.writeData
    when(io.write) { assert(io.hostMode) }
    ram.io.port.request.valid     := Mux(io.hostMode, io.host.request.valid, core.io.memory.request.valid)
    ram.io.port.request.bits      := Mux(io.hostMode, io.host.request.bits, core.io.memory.request.bits)
    ram.io.port.response.ready    := Mux(io.hostMode, io.host.response.ready, core.io.memory.response.ready)
    io.host.request.ready         := io.hostMode && ram.io.port.request.ready
    io.host.response.valid        := io.hostMode && ram.io.port.response.valid
    io.host.response.bits         := ram.io.port.response.bits
    core.io.memory.request.ready  := !io.hostMode && ram.io.port.request.ready
    core.io.memory.response.valid := !io.hostMode && ram.io.port.response.valid
    core.io.memory.response.bits  := ram.io.port.response.bits
    core.io.commitEnable          := io.commitEnable
    io.commit0                    := core.io.commit(0)
    io.commit1                    := core.io.commit(1)
    io.exception                  := core.io.exception
    io.memoryBusy                 := core.io.memoryBusy || ram.io.busy
    io.fetchWait                  := core.io.fetchWait
    io.dataRequest.valid          := !io.hostMode && core.io.memory.request.fire
    io.dataRequest.bits           := core.io.memory.request.bits
}
object SynchronousPlatformGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new SynchronousPlatformGsim, Array("--target-dir", args.head))
}
