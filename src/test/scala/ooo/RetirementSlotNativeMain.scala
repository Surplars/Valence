package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Actual production interface with the unified profile/constructor flag audited. */
object RetirementSlotNativeMain extends App {
    require(args.length == 2 && Set("off", "on").contains(args(1)))
    val p = if (args(1) == "on") RetirementSlotTestProfile.on else RetirementSlotTestProfile.off
    RetirementSlotProfile.requirePair(RetirementSlotTestProfile.off, RetirementSlotTestProfile.on)
    ChiselStage.emitCHIRRTLFile({
        val backend = new IntegerBackend(p, registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent,
            retirementSlotIdentity = p.retirementSlotIdentity)
        require(backend.p == p && backend.ledger.p == p && backend.retirementSlotIdentity == p.retirementSlotIdentity &&
            backend.ledger.retirementSlotIdentity == p.retirementSlotIdentity)
        Files.createDirectories(Paths.get(args(0)))
        Files.writeString(Paths.get(args(0), "actual-retirement-slot-constructor.json"), PostedBoardConfiguration.json(Map(
            "schema" -> "retirement-slot-constructor-v1", "coreFields" -> backend.p.productArity,
            "profileFlag" -> backend.p.retirementSlotIdentity, "backendFlag" -> backend.retirementSlotIdentity,
            "ledgerProfileFlag" -> backend.ledger.p.retirementSlotIdentity,
            "ledgerFlag" -> backend.ledger.retirementSlotIdentity)) + "\n")
        backend
    }, Array("--target-dir", args(0)))
    RetirementSlotTestProfile.writeParameters(args(0))
}
