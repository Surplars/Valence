package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.ooo.{CoherentLineHomeModule, DataPort}
import soc.ip.tilelink.LineGrant

/** Protocol-only shared I/D Home fixture. The host supplies both clients and RAM.
  * Full geometry is 1024 lines / 4 ways / 256 sets; M2 and W2 remain independent.
  */
class CommonHomeClientsGsim(wholeGrant: Boolean = false) extends Module {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3, sinkBits = 1)
    val io = IO(new Bundle {
        val clients = Vec(2, Flipped(new TLBundle(params)))
        val grants = Vec(2, Decoupled(new LineGrant(params)))
        val line = new TLBundle(params)
        val upstream = Flipped(new DataPort)
        val downstream = new DataPort
        val upstreamRequestCpu = Input(Bool())
        val drainRequest = Input(Bool())
        val drainDone = Output(Bool())
    })
    val home = CoherentLineHomeModule.build(params, BigInt("80010000", 16), 0x20000,
        nClients = 2, trackedLines = 1024, trackedWays = 4, acquireEntries = 2,
        writebackEntries = 2, mixedReadWrite = true, internalLineGrant = wholeGrant)
    home.io.clients <> io.clients
    io.line <> home.io.line
    home.io.upstream <> io.upstream
    io.downstream <> home.io.downstream
    home.io.upstreamRequestCpu := io.upstreamRequestCpu
    home.io.drainRequest := io.drainRequest
    io.drainDone := home.io.drainDone
    if (wholeGrant) io.grants <> home.io.lineGrants.get
    else for (grant <- io.grants) {
        grant.valid := false.B
        grant.bits := 0.U.asTypeOf(grant.bits)
    }
}

object CommonHomeClientsGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new CommonHomeClientsGsim(args.lift(1).contains("1")),
        Array("--target-dir", args.head))
}
