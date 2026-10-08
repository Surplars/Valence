package ip

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.ip.dma.EthernetTxDescriptorQueue

/** Queue-only event fixture. Independent engine inputs make exact concurrency
  * witnesses deterministic; full DMA/GMAC wrappers separately test the payload.
  */
class EthernetTxQueueEventGsim extends EthernetTxDescriptorQueue(
    4, BigInt("80200000", 16), BigInt(2147483648L), 2048) {
    val postLaunchCount = IO(Output(UInt(32.W)))
    val completePopCount = IO(Output(UInt(32.W)))
    val postLaunch = RegInit(0.U(32.W))
    val completePop = RegInit(0.U(32.W))
    when(post && io.launch.valid) { postLaunch := postLaunch + 1.U }
    when(pop && io.consumeDone) { completePop := completePop + 1.U }
    postLaunchCount := postLaunch
    completePopCount := completePop
}
object EthernetTxQueueEventGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetTxQueueEventGsim, Array("--target-dir", args.head))
}
