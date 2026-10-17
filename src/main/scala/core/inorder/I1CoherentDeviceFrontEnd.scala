package soc.core.inorder

import chisel3._
import soc.ip.bus.RegisterPort

/** Four credits per originating adapter, existing eight-owner arbitration.
  * Optional native beat cuts do not add CPU MSHRs or DDR transaction slots.
  * Replies remain ordered per device and require actual downstream completion.
  */
class I1CoherentDeviceFrontEnd(timingCuts: Boolean, compactHandoff: Boolean = false) extends Module {
    require(!compactHandoff || timingCuts)
    val io = IO(new Bundle {
        val network = Flipped(new RegisterPort)
        val loader = Flipped(new RegisterPort)
        val memory = new I1DataPort
    })
    val network = Module(new I1DmaRegisterDataAdapter)
    val loader = Module(new I1DmaRegisterDataAdapter)
    network.io.registers <> io.network; loader.io.registers <> io.loader
    val devices = Module(new I1SharedDataArbiter(registerResponseOwners = true))
    for ((port, i) <- Seq(network.io.data, loader.io.data).zipWithIndex) {
        if (timingCuts) {
            val deviceCut = Module(new I1RegisteredDataBoundary)
            deviceCut.io.upstream <> port
            devices.io.clients(i) <> deviceCut.io.downstream
        } else devices.io.clients(i) <> port
    }
    if (timingCuts && !compactHandoff) {
        val exclusionCut = Module(new I1RegisteredDataBoundary)
        exclusionCut.io.upstream <> devices.io.memory
        io.memory <> exclusionCut.io.downstream
    } else io.memory <> devices.io.memory
}
