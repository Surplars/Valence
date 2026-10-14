package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

/** Exact A68 backend, all ordinary ports public; inspection disabled as on the
  * board. This is a backend structural census, not a whole-board export.
  */
class ResidentMemoryBackendNative(enabled: Boolean) extends Module {
    val p = ResidentMemoryEntryProfile.params(enabled)
    val backend = Module(new IntegerBackend(p,
        registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent,
        retirementSlotIdentity = p.retirementSlotIdentity))
    val io = IO(chiselTypeOf(backend.io))
    io <> backend.io
    backend.io.inspectRegister := 0.U
}

object ResidentMemoryBackendNativeMain extends App {
    require(args.length == 2 && Set("off", "on").contains(args(1)))
    ChiselStage.emitCHIRRTLFile(new ResidentMemoryBackendNative(args(1) == "on"),
        Array("--target-dir", args(0)))
}
