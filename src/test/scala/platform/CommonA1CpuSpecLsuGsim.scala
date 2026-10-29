package platform

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._
import soc.platform._

/** Component-only ownership fixture. Cancellation is test stimulus, not backend branch recovery. */
class CommonA1CpuSpecLsuGsim(owners: Int) extends Module {
    private val profile = CommonCpuProfile.A1
    val p = CommonA1CpuSpec.resolve(profile, None, Some(CommonA1CpuSpec(owners)), profile.boundary).coreParams
    require(p.memoryEntries == owners && p.dataReturnHandleBits == 0 && !p.canonicalVirtualStoreOverlap)
    val io = IO(new Bundle {
        val startValid = Input(Bool())
        val startReady = Output(Bool())
        val token = Input(new RobToken(p))
        val address = Input(UInt(64.W))
        val data = Input(UInt(64.W))
        val store = Input(Bool())
        val parallel = Input(Bool())
        val cancelOwner = Input(Valid(new RobToken(p)))
        val memory = new DataPort
        val requestOwner = Output(Valid(new RobToken(p)))
        val complete = Decoupled(new BackendCompletion(p))
        val liveMask = Output(UInt(owners.W))
        val busy = Output(Bool())
        val discarded = Output(Bool())
    })
    val lsu = Module(new ParallelLoadStoreUnit(p))
    lsu.io.start.valid := io.startValid
    lsu.io.start.bits := 0.U.asTypeOf(new MemoryOperation(p))
    lsu.io.start.bits.token := io.token
    lsu.io.start.bits.pc := "h1000".U
    lsu.io.start.bits.address := io.address
    lsu.io.start.bits.physicalAddress := io.address
    lsu.io.start.bits.data := io.data
    lsu.io.start.bits.size := 3.U
    lsu.io.start.bits.unsigned := true.B
    lsu.io.start.bits.store := io.store
    lsu.io.issueDestination.foreach(_ := 0.U.asTypeOf(Valid(UInt(p.physBits.W))))
    lsu.io.parallel := io.parallel
    for (i <- 0 until owners) {
        lsu.io.cancel(i) := io.cancelOwner.valid && lsu.io.live(i) &&
            lsu.io.owner(i).asUInt === io.cancelOwner.bits.asUInt
    }
    lsu.io.fastStoreRetire := false.B
    lsu.io.fastLoadRetire := false.B
    io.startReady := lsu.io.start.ready
    io.memory <> lsu.io.memory
    io.requestOwner := lsu.io.requestOwner
    io.complete <> lsu.io.complete
    io.liveMask := lsu.io.live.asUInt
    io.busy := lsu.io.busy
    io.discarded := lsu.io.discarded
}

object CommonA1CpuSpecLsuGsimMain extends App {
    require(args.length == 2, "output-directory owners-2-or-4")
    ChiselStage.emitCHIRRTLFile(new CommonA1CpuSpecLsuGsim(args(1).toInt), Array("--target-dir", args(0)))
}
