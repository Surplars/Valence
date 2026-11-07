package soc.platform

import chisel3._
import soc.ip.bus.{RegisterPort, TwoMasterRegisterArbiter}
import soc.ip.interrupt.{Aplic, AplicParams, ImsicParams}

/** One shared machine/supervisor APLIC pair and MSI arbiter.
  * IMSIC files and their CSR authorization remain with the selected CPU tile.
  * All ports here belong to the fabric clock. If the tile clock differs, MSI
  * requests AND real responses require the selected CPU-boundary CDC transport.
  * Existing callers may still instantiate this at their single platform clock.
  */
class CommonInterruptFabric(
    aplicParams: AplicParams = AplicParams(),
    imsicParams: ImsicParams = ImsicParams()
) extends Module {
    require(aplicParams.msiBase == imsicParams.machineBase)
    require(aplicParams.identities == imsicParams.identities)
    val io = IO(new Bundle {
        val sources = Input(UInt(aplicParams.sources.W))
        val machineRegisters = Flipped(new RegisterPort)
        val supervisorRegisters = Flipped(new RegisterPort)
        val msi = new RegisterPort
        val msiError = Output(Bool())
    })
    private val machine = Module(new Aplic(aplicParams, hasChild = true,
        childMsiBase = imsicParams.supervisorBase, childGuestFiles = imsicParams.guestFiles,
        coordinatedGenmsi = true))
    private val supervisor = Module(new Aplic(
        aplicParams.copy(base = aplicParams.base + 16384, msiBase = imsicParams.supervisorBase,
            guestFiles = imsicParams.guestFiles),
        hasParent = true, coordinatedGenmsi = true))
    private val arbitration = Module(new TwoMasterRegisterArbiter(lockRequests = true, resetRoundRobin = true))
    machine.io.mmio <> io.machineRegisters
    supervisor.io.mmio <> io.supervisorRegisters
    machine.io.sources := io.sources
    supervisor.io.sources := machine.io.childSources
    supervisor.io.parentEnabled.get := machine.io.childEnabled
    // genmsi orders all earlier MSIs from the combined APLIC to this hart,
    // including the other domain's already-forwarded outgoing queue. Accept
    // the write normally, then freeze only NEW ordinary forwarding until the
    // old queues and real downstream replies drain. Do not stop MMIO, requests,
    // replies, or pending-state updates. This adds no ordinary MSI stage.
    def generating(port: RegisterPort, base: BigInt): Bool = {
        val request = port.request
        request.valid && request.bits.write && request.bits.address === (base + 0x3000).U &&
            request.bits.size === 2.U && request.bits.byteEnable === 15.U
    }
    val pause = machine.io.genmsiBusy || supervisor.io.genmsiBusy ||
        generating(io.machineRegisters, aplicParams.base) ||
        generating(io.supervisorRegisters, aplicParams.base + 16384)
    val drained = machine.io.msiDrained && supervisor.io.msiDrained
    machine.io.pauseForwarding.get := pause
    supervisor.io.pauseForwarding.get := pause
    machine.io.allowGenerated.get := drained
    supervisor.io.allowGenerated.get := drained
    arbitration.io.masters(0) <> machine.io.msi
    arbitration.io.masters(1) <> supervisor.io.msi
    io.msi <> arbitration.io.downstream
    io.msiError := machine.io.msiError || supervisor.io.msiError
}
