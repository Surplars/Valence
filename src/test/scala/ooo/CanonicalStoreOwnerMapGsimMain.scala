package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo._

object CanonicalStoreOwnerMapGsimMain extends App {
    require(args.length == 1)
    ChiselStage.emitCHIRRTLFile(new CanonicalStoreOwnerMapGsim(), Array("--target-dir", args.head))
}

object CanonicalStoreOwnerMapBackendGsimMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)))
    ChiselStage.emitCHIRRTLFile({
        val dut = new CanonicalStoreOwnerMapBackendGsim(args(1) == "1")
        require(dut.backend.p == dut.p && dut.backend.ledger.p == dut.p)
        PostedBoardConfiguration.writeCore(dut.p, args.head)
        println(s"CANONICAL_OWNER_MAP shared=${dut.backend.shareCanonicalStoreOwnerMatch} " +
            s"staged=${dut.backend.registerCanonicalStoreEvent} tagBits=${dut.p.tagBits} rob=${dut.p.robEntries}")
        dut
    }, Array("--target-dir", args.head))
}

/** Export the actual production backend, without observation ports or assertions,
  * for matched native structural comparison. No whole-CPU run is implied.
  */
object CanonicalStoreOwnerMapNativeMain extends App {
    require(args.length == 5 && args.slice(1, 4).forall(Set("0", "1").contains))
    require(Set("legacy", "frontier", "pending", "disabled").contains(args(4)))
    val original = args(4) match {
        case "legacy" => _root_.ooo.CanonicalVirtualStoreBackendFixture.params(true, 4)
        case "frontier" => _root_.ooo.MemoryProofFrontierFixture.params()
        case "pending" => Lane1OwnerBackendProfile.params(true).copy(
            directRank1MemorySourceIds = true, directRegisteredExecutionOperands = true)
        case "disabled" => _root_.ooo.CanonicalVirtualStoreBackendFixture.params(false, 4)
    }
    require(args(4) != "disabled" || (args(1) == "0" && args(2) == "0"),
        "disabled canonical overlap requires both owner sharing and registered canonical events off")
    val p = original.copy(registeredCanonicalStoreEvent = args(2) == "1",
        reconstructIssueTokenIndex = args(3) == "1",
        sharedCanonicalStoreOwnerMatch = args(1) == "1")
    ChiselStage.emitCHIRRTLFile(new IntegerBackend(p,
        registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent), Array("--target-dir", args.head))
    PostedBoardConfiguration.writeCore(p, args.head)
}
