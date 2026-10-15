package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Both real implementations; the C++ oracle independently selects then compares.
  * Deliberately inconsistent request/accept and priority collisions are legal here.
  * Mutations affect only this verification fixture, never production hardware.
  */
class PreselectedRedirectGsim extends Module {
    private val p = OooParams(robEntries = 16, tagBits = 64)
    val io = IO(new Bundle {
        val localToken = Input(new RobToken(p))
        val systemToken = Input(new RobToken(p))
        val trapToken = Input(new RobToken(p))
        val localAccepted = Input(Bool())
        val systemAccepted = Input(Bool())
        val systemRequest = Input(Bool())
        val trapAccepted = Input(Bool())
        val query0 = Input(new RobToken(p))
        val query1 = Input(new RobToken(p))
        val mutation = Input(UInt(2.W))
        val baseline0 = Output(Bool())
        val baseline1 = Output(Bool())
        val candidate0 = Output(Bool())
        val candidate1 = Output(Bool())
    })
    val baseline = Module(new RedirectTokenQualification(p))
    baseline.io.local.valid := io.systemAccepted || io.localAccepted
    baseline.io.local.bits := Mux(io.systemAccepted, io.systemToken, io.localToken)
    baseline.io.trap.valid := io.trapAccepted
    baseline.io.trap.bits := io.trapToken
    baseline.io.queries(0) := io.query0
    baseline.io.queries(1) := io.query1
    val candidate = Module(new PreselectedRedirectTokenQualification(p))
    candidate.io.localToken := io.localToken
    candidate.io.systemToken := io.systemToken
    candidate.io.trapToken := io.trapToken
    candidate.io.localAccepted := io.localAccepted
    candidate.io.systemAccepted := Mux(io.mutation === 1.U, io.systemRequest, io.systemAccepted)
    candidate.io.trapAccepted := io.trapAccepted
    candidate.io.queries(0) := io.query0
    candidate.io.queries(1) := io.query1
    when(io.mutation === 2.U) { candidate.io.queries(0).tag := io.query0.tag ^ (BigInt(1) << 63).U }
    io.baseline0 := baseline.io.matches(0)
    io.baseline1 := baseline.io.matches(1)
    io.candidate0 := candidate.io.matches(0)
    io.candidate1 := candidate.io.matches(1)
    when(io.mutation === 3.U) {
        // Incorrect fallback after a valid but mismatching high-priority trap.
        io.candidate0 := candidate.io.matches(0) || (io.trapAccepted && io.localAccepted &&
            io.localToken.asUInt === io.query0.asUInt)
    }
}

object PreselectedRedirectGsimMain extends App {
    require(args.length == 1)
    ChiselStage.emitCHIRRTLFile(new PreselectedRedirectGsim, Array("--target-dir", args(0)))
}

object PreselectedRedirectBackendMain extends App {
    require(args.length == 2 && Set("0", "1").contains(args(1)))
    var actual: Option[OooParams] = None
    ChiselStage.emitCHIRRTLFile({
        val dut = new ReadyStoreQuery77BackendGsim(true, proofRows = 3,
            preselectRedirectTokenMatches = args(1) == "1")
        actual = Some(dut.backend.p)
        require(dut.backend.p == ThreeProofRowNativeProfile.config.coreParams)
        require(dut.backend.pendingStoreProof.get.state.length == 3)
        require(dut.backend.pendingStoreCredit.get.state.length == 2)
        dut
    }, Array("--target-dir", args(0)))
    java.nio.file.Files.writeString(java.nio.file.Paths.get(args(0), "actual-core.json"),
        PostedBoardConfiguration.json(actual.get) + "\n")
}
