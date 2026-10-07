package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class SvWalkerGsim(maxLevels: Int) extends Module {
    val io = IO(new Bundle {
        val startValid     = Input(Bool())
        val startReady     = Output(Bool())
        val virtualAddress = Input(UInt(64.W))
        val rootPpn        = Input(UInt(44.W))
        val mode           = Input(UInt(4.W))
        val privilege      = Input(UInt(2.W))
        val access         = Input(UInt(2.W))
        val sum            = Input(Bool())
        val mxr            = Input(Bool())
        val completeValid  = Output(Bool())
        val completeReady  = Input(Bool())
        val physicalAddress = Output(UInt(64.W))
        val pageFault      = Output(Bool())
        val accessFault    = Output(Bool())
        val level          = Output(UInt(3.W))
        val global         = Output(Bool())
        val pbmt           = Output(UInt(2.W))
        val pteValid       = Output(Bool())
        val pteReady       = Input(Bool())
        val pteAddress     = Output(UInt(64.W))
        val pteReplyValid  = Input(Bool())
        val pteReplyReady  = Output(Bool())
        val pteData        = Input(UInt(64.W))
        val pteError       = Input(Bool())
        val pmpCfg         = Input(UInt(8.W))
        val pmpAddr        = Input(UInt(54.W))
    })
    val walker = Module(new SvPageTableWalker(maxLevels))
    walker.io.start.valid := io.startValid
    walker.io.start.bits.virtualAddress := io.virtualAddress
    walker.io.start.bits.rootPpn := io.rootPpn
    walker.io.start.bits.mode := io.mode
    walker.io.start.bits.privilege := io.privilege
    walker.io.start.bits.access := io.access
    walker.io.start.bits.sum := io.sum
    walker.io.start.bits.mxr := io.mxr
    io.startReady := walker.io.start.ready
    walker.io.complete.ready := io.completeReady
    io.completeValid := walker.io.complete.valid
    io.physicalAddress := walker.io.complete.bits.physicalAddress
    io.pageFault := walker.io.complete.bits.pageFault
    io.accessFault := walker.io.complete.bits.accessFault
    io.level := walker.io.complete.bits.level
    io.global := walker.io.complete.bits.global
    io.pbmt := walker.io.complete.bits.pbmt
    io.pteValid := walker.io.memory.request.valid
    walker.io.memory.request.ready := io.pteReady
    io.pteAddress := walker.io.memory.request.bits
    walker.io.memory.response.valid := io.pteReplyValid
    io.pteReplyReady := walker.io.memory.response.ready
    walker.io.memory.response.bits.data := io.pteData
    walker.io.memory.response.bits.error := io.pteError
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.pmpCfg
    pmp.addr(0) := io.pmpAddr
    PmpState.decodeRegions(pmp)
    walker.io.pmpState := pmp
}

object SvWalkerGsimMain extends App {
    require(args.length == 2)
    ChiselStage.emitCHIRRTLFile(new SvWalkerGsim(args(1).toInt), Array("--target-dir", args(0)))
}
