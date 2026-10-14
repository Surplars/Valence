package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** Observation-only direct fixture: both instances are the actual production LSU.
  * The host owns the accepted-operation/response ledger and observes the next
  * edge's real phase, result and full owner token without using any ready row.
  */
class LoadReadyDirectLane(p: OooParams) extends Bundle {
    val startValid = Input(Bool())
    val startReady = Output(Bool())
    val token = Input(new RobToken(p))
    val pc = Input(UInt(64.W))
    val address = Input(UInt(64.W))
    val data = Input(UInt(64.W))
    val size = Input(UInt(2.W))
    val unsignedLoad = Input(Bool())
    val store = Input(Bool())
    val atomic = Input(Bool())
    val atomicOp = Input(UInt(5.W))
    val accessDenied = Input(Bool())
    val virtualized = Input(Bool())
    val forwardValid = Input(Bool())
    val forwardData = Input(UInt(64.W))
    val memory = new DataPort
    val complete = Decoupled(new BackendCompletion(p))
    val cancel = Input(Bool())
    val capture = Output(Bool())
    val phase = Output(UInt(2.W))
    val busy = Output(Bool())
    val issueAvailable = Output(Bool())
    val registeredCancelled = Output(Bool())
    val owner = Output(new RobToken(p))
    val discarded = Output(Bool())
    val forwarded = Output(Bool())
    val forwardStore = Output(Valid(new StoreForward(p)))
    val fastLoadPreview = Output(Valid(new BackendCompletion(p)))
}

class LoadReadyDirectGsim(enabled: Boolean) extends Module {
    val p = LoadReadyP1Params(enabled)
    val io = IO(new Bundle {
        val enabled = Output(Bool())
        val lane0 = new LoadReadyDirectLane(p)
        val lane1 = new LoadReadyDirectLane(p)
    })
    io.enabled := enabled.B
    for ((port, registered) <- Seq((io.lane0, false), (io.lane1, true))) {
        val lsu = Module(new LoadStoreUnit(p, registerStart = registered))
        lsu.io.start.valid := port.startValid
        lsu.io.start.bits := 0.U.asTypeOf(new MemoryOperation(p))
        lsu.io.start.bits.token := port.token
        lsu.io.start.bits.pc := port.pc
        lsu.io.start.bits.address := port.address
        lsu.io.start.bits.data := port.data
        lsu.io.start.bits.size := port.size
        lsu.io.start.bits.unsigned := port.unsignedLoad
        lsu.io.start.bits.store := port.store
        lsu.io.start.bits.atomic := port.atomic
        lsu.io.start.bits.atomicOp := port.atomicOp
        lsu.io.start.bits.accessDenied := port.accessDenied
        lsu.io.start.bits.virtualized := port.virtualized
        lsu.io.start.bits.forward.valid := port.forwardValid
        lsu.io.start.bits.forward.bits := port.forwardData
        lsu.io.cancel := port.cancel
        lsu.io.fastStoreRetire := false.B
        lsu.io.fastLoadRetire := false.B
        port.startReady := lsu.io.start.ready
        port.memory <> lsu.io.memory
        port.complete <> lsu.io.complete
        port.capture := lsu.io.successfulLoadResultCapture.getOrElse(false.B)
        port.phase := lsu.io.phase
        port.busy := lsu.io.busy
        port.issueAvailable := lsu.io.issueAvailable
        port.registeredCancelled := BoringUtils.bore(lsu.cancelled)
        port.owner := lsu.io.owner
        port.discarded := lsu.io.discarded
        port.forwarded := lsu.io.forwarded
        port.forwardStore := lsu.io.forwardStore
        port.fastLoadPreview := lsu.io.fastLoadPreview
    }
}

object LoadReadyDirectGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)), "output-directory feature-0-or-1")
    LoadReadyP1Params.write(args(0), args(1) == "1")
    ChiselStage.emitCHIRRTLFile(new LoadReadyDirectGsim(args(1) == "1"), Array("--target-dir", args(0)))
}
