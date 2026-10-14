package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.bus.tilelink._
import soc.core.ooo.{FrozenInstructionTileLinkBridgeBeforePaD, InstructionPort, InstructionTileLinkBridge}

/** Four real bridge instances. Both production address modes are checked against
  * a frozen pre-change source peer and against each other. No CPU or ROM is built.
  * Payload equivalence is required whenever valid, including every stalled cycle.
  * Ready and valid are always compared, including when input payload is poison.
  */
class BridgeOwnerPairGsim extends Module {
    val p = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val fetch = Flipped(new InstructionPort)
        val tl = new TLBundle(p)
        val mutateCandidateData = Input(Bool())
        val interfaceEqual = Output(Bool())
        val genericEqual = Output(Bool())
        val parallelEqual = Output(Bool())
        val modeEqual = Output(Bool())
    })
    val baselineGeneric = Module(new FrozenInstructionTileLinkBridgeBeforePaD(p, parallelAddresses = false))
    val baselineParallel = Module(new FrozenInstructionTileLinkBridgeBeforePaD(p, parallelAddresses = true))
    val candidateGeneric = Module(new InstructionTileLinkBridge(p, parallelAddresses = false))
    val candidateParallel = Module(new InstructionTileLinkBridge(p, parallelAddresses = true))
    io.fetch <> candidateParallel.io.fetch
    io.tl <> candidateParallel.io.tl
    // The mutation changes only the candidate input, and is a separate negative test.
    candidateParallel.io.tl.d.bits.data := io.tl.d.bits.data ^ io.mutateCandidateData.asUInt
    for ((fetch, tl) <- Seq(
        (baselineGeneric.io.fetch, baselineGeneric.io.tl),
        (baselineParallel.io.fetch, baselineParallel.io.tl),
        (candidateGeneric.io.fetch, candidateGeneric.io.tl))) {
        fetch.request.valid := io.fetch.request.valid
        fetch.request.bits := io.fetch.request.bits
        fetch.requestMask := io.fetch.requestMask
        fetch.response.ready := io.fetch.response.ready
        tl.a.ready := io.tl.a.ready
        tl.b.valid := io.tl.b.valid
        tl.b.bits := io.tl.b.bits
        tl.c.ready := io.tl.c.ready
        tl.d.valid := io.tl.d.valid
        tl.d.bits := io.tl.d.bits
        tl.e.ready := io.tl.e.ready
    }
    def equalFetch(a: InstructionPort, b: InstructionPort): Bool = {
        a.request.ready === b.request.ready &&
        a.response.valid === b.response.valid &&
        (!a.response.valid || (a.response.bits === b.response.bits &&
            a.responseError === b.responseError && a.responsePageFault === b.responsePageFault))
    }
    def equalTl(a: TLBundle, b: TLBundle): Bool = {
        a.a.valid === b.a.valid && (!a.a.valid || a.a.bits.asUInt === b.a.bits.asUInt) &&
        a.d.ready === b.d.ready && a.b.ready === b.b.ready &&
        a.c.valid === b.c.valid && (!a.c.valid || a.c.bits.asUInt === b.c.bits.asUInt) &&
        a.e.valid === b.e.valid && (!a.e.valid || a.e.bits.asUInt === b.e.bits.asUInt)
    }
    io.genericEqual := equalFetch(baselineGeneric.io.fetch, candidateGeneric.io.fetch) &&
        equalTl(baselineGeneric.io.tl, candidateGeneric.io.tl)
    io.parallelEqual := equalFetch(baselineParallel.io.fetch, candidateParallel.io.fetch) &&
        equalTl(baselineParallel.io.tl, candidateParallel.io.tl)
    io.modeEqual := equalFetch(candidateGeneric.io.fetch, candidateParallel.io.fetch) &&
        equalTl(candidateGeneric.io.tl, candidateParallel.io.tl) &&
        equalFetch(baselineGeneric.io.fetch, baselineParallel.io.fetch) &&
        equalTl(baselineGeneric.io.tl, baselineParallel.io.tl)
    io.interfaceEqual := io.genericEqual && io.parallelEqual && io.modeEqual
    assert(io.interfaceEqual, "bridge frozen peer valid-interface mismatch")
}

object BridgeOwnerPairGsimMain extends App {
    require(args.length == 1, "usage: BridgeOwnerPairGsimMain <target-dir>")
    ChiselStage.emitCHIRRTLFile(new BridgeOwnerPairGsim, Array("--target-dir", args.head))
}
