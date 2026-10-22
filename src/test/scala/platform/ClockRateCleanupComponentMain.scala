package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.clock._
import soc.platform._

/** Test-only two real controllers/adapter with a public modeled boundary.
  * The allowed rate and boot gate/lock inputs are simulation fixtures, never
  * production qualification or evidence of physical gating/DRP.
  */
class ClockRateCleanupComponent extends Module {
    val p = CommonCpuTilePortParams(runtimeMaintenance = true, runtimeCancellation = true,
        runtimeInterruptHold = true)
    val io = IO(new Bundle {
        val submit = Vec(2, Flipped(Valid(UInt(32.W))))
        val responseCommitted = Input(Vec(2, Bool()))
        val clearErrors = Input(Vec(2, UInt(32.W)))
        val endpoint = Vec(2, new ClockRateEndpoint)
        val requestError = Output(Vec(2, UInt(32.W)))
        val state = Output(Vec(2, UInt(4.W)))
        val busy = Output(Vec(2, Bool()))
        val errors = Output(Vec(2, UInt(32.W)))
        val completed = Output(Vec(2, UInt(32.W)))
        val lastSuccess = Output(Vec(2, Bool()))
        val requests = Vec(2, Decoupled(UInt(32.W)))
        val resume = Vec(2, Decoupled(new CommonRuntimeAonStatus(p)))
        val cancel = Vec(2, Decoupled(new CommonRuntimeAonStatus(p)))
        val held = Vec(2, Flipped(Valid(new CommonRuntimeAonStatus(p))))
        val result = Vec(2, Flipped(Decoupled(new CommonRuntimeAonResult(p))))
        val boundaryBusy = Input(Bool())
        val activeLane = Input(UInt(1.W))
        val activeEpoch = Input(UInt(p.maintenanceEpochBits.W))
        val activeToken = Input(UInt(32.W))
        val drainDeadline = Input(Bool())
        val timeoutSelected = Input(Bool())
        val cleanupFault = Input(Bool())
    })
    val params = ClockRateParams(points = Seq(ClockRatePoint(100000000L, true, true, true)),
        timeoutCycles = 32, stableCycles = 3)
    val adapter = Module(new CommonClockRateEpochAdapter(p))
    for (i <- 0 until 2) {
        val control = Module(new ClockRateControl(params, externalDrainLease = true))
        control.io.submit <> io.submit(i)
        control.io.responseCommitted := io.responseCommitted(i)
        control.io.clearErrors := io.clearErrors(i)
        control.io.endpoint <> io.endpoint(i)
        control.io.lease.get <> adapter.io.clients(i)
        io.requestError(i) := control.io.requestError
        io.state(i) := control.io.state; io.busy(i) := control.io.busy
        io.errors(i) := control.io.errors; io.completed(i) := control.io.completed
        io.lastSuccess(i) := control.io.lastSuccess
    }
    io.requests <> adapter.io.requests
    io.resume <> adapter.io.resume
    io.cancel <> adapter.io.cancel
    adapter.io.held <> io.held
    adapter.io.result <> io.result
    adapter.io.busy := io.boundaryBusy
    adapter.io.activeLane := io.activeLane; adapter.io.activeEpoch := io.activeEpoch
    adapter.io.activeToken := io.activeToken; adapter.io.drainDeadline := io.drainDeadline
    adapter.io.timeoutSelected := io.timeoutSelected; adapter.io.cleanupFault := io.cleanupFault
}
object ClockRateCleanupComponentMain extends App {
    require(args.length == 1 && !java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitSystemVerilogFile(new ClockRateCleanupComponent, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
