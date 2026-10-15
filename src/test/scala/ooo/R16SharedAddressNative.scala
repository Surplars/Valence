package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Component-only native census. All ordinary backend ports remain public. */
class R16SharedAddressNative(shared: Boolean) extends Module {
    val p = TimingReady73Profile.on.coreParams.copy(sharedMemoryAddressState = shared)
    ProfileAbi77.requireLive(p)
    require(!p.pendingReadyStoreQuery && p.productArity == 178 && p.robEntries == 16 && p.physicalRegs == 48 &&
        p.issueWidth == 2 && p.tagBits == 64 && !p.reconstructIssueTokenIndex && !p.memoryProofFrontier)
    val backend = Module(new IntegerBackend(p,
        registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent,
        retirementSlotIdentity = p.retirementSlotIdentity))
    require(backend.p == p && backend.ledger.p == p)
    val io = IO(chiselTypeOf(backend.io))
    io <> backend.io
}

object R16SharedAddressNativeMain extends App {
    require(args.length == 2 && Set("off", "on").contains(args(1)))
    val out = Paths.get(args(0))
    require(!Files.exists(out), "fresh output required")
    val shared = args(1) == "on"
    var actual: Option[OooParams] = None
    ChiselStage.emitSystemVerilogFile({
        val dut = new R16SharedAddressNative(shared)
        actual = Some(dut.backend.p)
        dut
    }, Array("--target-dir", out.toString), Array("--split-verilog", "-disable-all-randomization",
        "-strip-debug-info", "-default-layer-specialization=disable"))
    val p = actual.get
    Files.writeString(out.resolve("actual-core.json"), PostedBoardConfiguration.json(p) + "\n")
    Files.writeString(out.resolve("actual-constructor.json"), PostedBoardConfiguration.json(Map(
        "registerCanonicalStoreEvent" -> p.registeredCanonicalStoreEvent,
        "retirementSlotIdentity" -> p.retirementSlotIdentity,
        "fields" -> p.productArity, "onlyBackend" -> true,
        "simulationRun" -> false, "physicalQualification" -> false)) + "\n")
    println("PASS_R16_SHARED_ADDRESS_NATIVE " + args(1))
}
