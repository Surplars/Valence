package ooo

import chisel3._
import chisel3.util.experimental.BoringUtils
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class FixedPmpWalkerGsim(maxLevels: Int, decodedPmp: Boolean = false) extends Module {
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
        val pmpCfg1 = Input(UInt(8.W))
        val pmpAddr1 = Input(UInt(54.W))
        val rawPteAddress = Output(UInt(64.W))
        val rawPmpDenied = Output(Bool())
    })
    val walker = Module(new SvPageTableWalker(maxLevels, decodedNaturalPmp = decodedPmp))
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
    pmp.cfg(1) := io.pmpCfg1
    pmp.addr(1) := io.pmpAddr1
    PmpState.decodeRegions(pmp)
    walker.io.pmpState := pmp
    val previous = Module(new FixedCallerReferenceWalker(maxLevels))
    previous.io.start.valid := walker.io.start.valid
    previous.io.start.bits := walker.io.start.bits
    previous.io.complete.ready := io.completeReady
    previous.io.memory.request.ready := io.pteReady
    previous.io.memory.response.valid := io.pteReplyValid
    previous.io.memory.response.bits := walker.io.memory.response.bits
    previous.io.pmpState := pmp
    assert(walker.io.start.ready === previous.io.start.ready &&
        walker.io.complete.valid === previous.io.complete.valid &&
        walker.io.memory.request.valid === previous.io.memory.request.valid &&
        walker.io.memory.response.ready === previous.io.memory.response.ready,
        "fixed PMP walker peer handshake mismatch")
    when(walker.io.complete.valid) {
        assert(walker.io.complete.bits.asUInt === previous.io.complete.bits.asUInt,
            "fixed PMP walker peer completion mismatch")
    }
    when(walker.io.memory.request.valid) {
        assert(walker.io.memory.request.bits === previous.io.memory.request.bits,
            "fixed PMP walker peer valid PTE request mismatch")
    }
    io.rawPteAddress := BoringUtils.bore(walker.pteAddress)
    io.rawPmpDenied := BoringUtils.bore(walker.pmpDenied)
    val referenceAddress = BoringUtils.bore(previous.pteAddress)
    val referenceDenied = BoringUtils.bore(previous.pmp.io.denied)
    assert(io.rawPteAddress === referenceAddress && io.rawPmpDenied === referenceDenied,
        "fixed PMP walker raw address/permission mismatch")
}

object FixedPmpWalkerGsimMain extends App {
    require(args.length == 2)
    ChiselStage.emitCHIRRTLFile(new FixedPmpWalkerGsim(args(1).toInt), Array("--target-dir", args(0)))
}
