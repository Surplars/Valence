package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

class StoreBufferGsim(entries: Int = 4, registeredLocalResponses: Boolean = false,
    registeredOwners: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val upstream  = Flipped(new DataPort)
        val fastStore = Flipped(Decoupled(new DataRequest))
        val memory    = new DataPort
        val busy      = Output(Bool())
        val forwarded = Output(Bool())
    })
    val buffer = Module(
        new StoreBuffer(
            OooParams(
                bufferedRamStores = true,
                registeredLocalStoreResponses = registeredLocalResponses,
                registeredStoreResponseOwners = registeredOwners,
                storeBufferEntries = entries,
                speculativeRamBase = 4096,
                speculativeRamBytes = 256
            )
        )
    )
    buffer.io.upstream <> io.upstream
    buffer.io.fastStore <> io.fastStore
    io.memory <> buffer.io.memory
    io.busy      := buffer.io.busy
    io.forwarded := buffer.io.forwarded
}
object StoreBufferGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(
        new StoreBufferGsim(if (args.length > 1) args(1).toInt else 4,
            args.drop(2).contains("registered-local-response"),
            args.drop(2).contains("registered-owners")),
        Array("--target-dir", args.head)
    )
}
