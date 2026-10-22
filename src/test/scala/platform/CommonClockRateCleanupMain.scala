package platform

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.clock._
import soc.ip.bus.CdcResetRelease
import soc.platform._

/** Adds observation ports in the inherited module context, without changing the r10 fixture. */
class CommonI1RuntimeCleanupFixture extends CommonI1RuntimeCdcFixture {
    val drainDeadline = IO(Output(Bool()))
    val proofObserved = IO(Output(Bool()))
    drainDeadline := runtime.io.drainDeadline
    proofObserved := runtime.io.proofObserved
}

/** Failure-only real controller integration. Boot gate/lock inputs are explicitly
  * a test model; full drain ACKs are absent and no runtime gate/program action is
  * permitted. Real r10 AON timeout, real tile/fabric owners and retirement are DUT.
  */
class CommonClockRateCleanupFixture extends RawModule {
    val cpuClock = IO(Input(Clock()))
    val fabricClock = IO(Input(Clock()))
    val alwaysOnClock = IO(Input(Clock()))
    val commonColdReset = IO(Input(AsyncReset()))
    val fixture = Module(new CommonI1RuntimeCleanupFixture)
    fixture.cpuClock := cpuClock; fixture.fabricClock := fabricClock
    fixture.alwaysOnClock := alwaysOnClock; fixture.commonColdReset := commonColdReset
    val io = IO(chiselTypeOf(fixture.io))
    io <> fixture.io
    val control = IO(new Bundle {
        val submit = Input(Vec(2, Valid(UInt(32.W))))
        val responseCommitted = Input(UInt(2.W))
        val holdTerminal = Input(UInt(2.W))
        val busy = Output(UInt(2.W))
        val quiesce = Output(UInt(2.W))
        val clockEnable = Output(UInt(2.W))
        val state = Output(Vec(2, UInt(4.W)))
        val completed = Output(Vec(2, UInt(32.W)))
        val errors = Output(Vec(2, UInt(32.W)))
        val success = Output(UInt(2.W))
        val requestError = Output(Vec(2, UInt(32.W)))
        val requestFire = Output(UInt(2.W))
        val terminalFire = Output(UInt(2.W))
        val retired = Output(UInt(2.W))
        val deadline = Output(Bool())
        val proofObserved = Output(Bool())
    })
    val release = Module(new CdcResetRelease)
    release.clockIn := alwaysOnClock; release.asyncReset := commonColdReset
    withClockAndReset(alwaysOnClock, release.resetOut) {
        val p = ClockRateParams(points = Seq(ClockRatePoint(55000000L,
            physicalLegal = true, componentTested = true, socSignedOff = true)),
            timeoutCycles = 64, stableCycles = 3)
        val controls = Seq.fill(2)(Module(new ClockRateControl(p, externalDrainLease = true)))
        val adapter = Module(new CommonClockRateEpochAdapter(fixture.boundary))
        fixture.io.requests <> adapter.io.requests
        fixture.io.resume <> adapter.io.resume
        fixture.io.cancel <> adapter.io.cancel
        adapter.io.held := fixture.io.held
        adapter.io.result <> fixture.io.result
        adapter.io.busy := fixture.io.busy
        adapter.io.activeLane := fixture.io.activeLane
        adapter.io.activeEpoch := fixture.io.activeEpoch
        adapter.io.activeToken := fixture.io.activeToken
        adapter.io.drainDeadline := fixture.drainDeadline
        adapter.io.timeoutSelected := fixture.io.timeoutSelected
        adapter.io.cleanupFault := fixture.io.cleanupFault
        control.deadline := fixture.drainDeadline
        control.proofObserved := fixture.proofObserved
        for (i <- 0 until 2) {
            val c = controls(i)
            c.io.submit := control.submit(i)
            c.io.responseCommitted := control.responseCommitted(i)
            c.io.clearErrors := 0.U
            c.io.endpoint.present := true.B
            c.io.endpoint.locked := true.B
            c.io.endpoint.gateOpen := true.B
            c.io.endpoint.gateClosed := false.B
            c.io.endpoint.resumed := true.B
            c.io.endpoint.drainAcks := 0.U
            c.io.endpoint.program.ready := false.B
            c.io.endpoint.result.valid := false.B
            c.io.endpoint.result.bits := 0.U.asTypeOf(c.io.endpoint.result.bits)
            adapter.io.clients(i) <> c.io.lease.get
            c.io.lease.get.terminal.valid := adapter.io.clients(i).terminal.valid && !control.holdTerminal(i)
            adapter.io.clients(i).terminal.ready := c.io.lease.get.terminal.ready && !control.holdTerminal(i)
            control.state(i) := c.io.state
            control.completed(i) := c.io.completed
            control.errors(i) := c.io.errors
            control.requestError(i) := c.io.requestError
            when(!release.resetOut.asBool && c.io.state =/= 5.U && c.io.state =/= 6.U && c.io.state =/= 7.U) {
                assert(c.io.endpoint.clockEnable, "cleanup controller stopped old clock")
            }
            assert(!c.io.endpoint.program.valid, "failure-only cleanup fixture attempted rate programming")
            assert(c.io.state =/= 3.U && c.io.state =/= 4.U,
                "failure-only cleanup fixture attempted runtime gate close")
        }
        control.busy := VecInit(controls.map(_.io.busy)).asUInt
        control.quiesce := VecInit(controls.map(_.io.endpoint.quiesce)).asUInt
        control.clockEnable := VecInit(controls.map(_.io.endpoint.clockEnable)).asUInt
        control.success := VecInit(controls.map(_.io.lastSuccess)).asUInt
        control.requestFire := VecInit(adapter.io.requests.map(_.fire)).asUInt
        control.terminalFire := VecInit(controls.map(_.io.lease.get.terminal.fire)).asUInt
        control.retired := VecInit(controls.map(_.io.lease.get.retired.fire)).asUInt
    }
}
object CommonClockRateCleanupNativeMain extends App {
    require(args.length == 1)
    ChiselStage.emitSystemVerilogFile(new CommonClockRateCleanupFixture, Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
