package ip

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.ip.bus._
import soc.ip.clock._
import soc.ip.dma.NetworkDmaConfig
import soc.ip.ethernet._

/** Actual production MAC/owner boundary. The SV bench bypasses only slow PHY
  * link/rate discovery, by forcing the media transaction's request inputs.
  * Clock policy, CDC, packet ownership, adapter and configuration are real.
  * BUFGCE has an explicit digital behavioral model, not vendor timing proof.
  */
class TriSpeedManagedBoundaryCdcTop(config: NetworkDmaConfig, slots: Int) extends RawModule {
    val sourceClock = IO(Input(Clock()))
    val alwaysOnClock = IO(Input(Clock()))
    val rawTxClock = IO(Input(Clock()))
    val rawRxClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val stop = IO(Input(Vec(2, Bool())))
    val registers = IO(Flipped(new RegisterPort))
    val streams = IO(new ManagedGmacStreams)
    val rawRgmiiRxRise = IO(Input(UInt(5.W)))
    val rawRgmiiRxFall = IO(Input(UInt(5.W)))
    val txClock = IO(Output(Clock()))
    val rxClock = IO(Output(Clock()))
    val stopped = IO(Output(Vec(2, Bool())))
    val fault = IO(Output(Vec(2, Bool())))
    val linkUp = IO(Output(Bool()))
    val appliedSpeed = IO(Output(UInt(2.W)))
    val mediaPending = IO(Output(Bool()))
    val gmac = Module(new TriSpeedManagedGmac(hardwareClocks = true,
        networkDmaConfig = config, txFrameSlots = slots))
    gmac.sourceClock := sourceClock
    gmac.rawTxClock := rawTxClock
    gmac.rawRxClock := rawRxClock
    gmac.commonReset := commonReset
    gmac.registers <> registers
    gmac.streams <> streams
    gmac.rawRgmiiRxRise := rawRgmiiRxRise
    gmac.rawRgmiiRxFall := rawRgmiiRxFall
    gmac.mdioIn := true.B
    txClock := gmac.txClock
    rxClock := gmac.rxClock
    linkUp := gmac.linkUp
    appliedSpeed := gmac.appliedSpeed
    mediaPending := gmac.mediaPending
    val release = Module(new CdcResetRelease)
    release.clockIn := alwaysOnClock
    release.asyncReset := commonReset
    for (n <- 0 until 2) {
        val policy = withClockAndReset(alwaysOnClock, release.resetOut) {
            Module(new PeripheralClockControl(16384)).suggestName(if (n == 0) "txPolicy" else "rxPolicy")
        }
        policy.io.stopRequest := stop(n)
        policy.io.wake := ManagedPeripheralSupport.level(gmac.control(n).wake, alwaysOnClock, release.resetOut)
        policy.io.domainAck := gmac.control(n).ack
        policy.io.clearFault := false.B
        gmac.control(n).clockEnable := policy.io.clockEnable
        gmac.control(n).quiesce := policy.io.quiesce
        gmac.control(n).isolate := policy.io.isolate
        gmac.control(n).allowAdmission := policy.io.allowAdmission
        stopped(n) := policy.io.stopped
        fault(n) := policy.io.fault
    }
    // Preserve exact launch taps for the independent-edge source-sample oracle.
    dontTouch(gmac.mediaOpen)
    dontTouch(gmac.ingressEmptySource)
    dontTouch(gmac.txWireDrainedSource)
}

object TriSpeedManagedBoundaryCdcMain extends App {
    val (positional, config) = NetworkDmaConfig.parseArgs(args)
    require(positional.length == 2, "usage: TriSpeedManagedBoundaryCdcMain <rtl-dir> <tx-slots> [network options]")
    ChiselStage.emitSystemVerilogFile(new TriSpeedManagedBoundaryCdcTop(config, positional(1).toInt),
        Array("--target-dir", positional(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization", "--preserve-values=named",
            "--lowering-options=disallowLocalVariables", "--default-layer-specialization=enable"))
}
