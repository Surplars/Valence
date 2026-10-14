package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}
import soc.core.ooo._
import soc.isa.Compressed

/** Frozen A68 vector, independent of historical product-arity validators. */
object ResidentMemoryEntryProfile {
    val options: Seq[String] = Seq(
        "--selected",
        "--data-translation-entries=16",
        "--registered-pmp-regions",
        "--experimental-trispeed-ethernet",
        "--experimental-jtag-bscan=2",
        "--dma-line-transfers",
        "--dma-line-entries=4",
        "--prefetch-candidate-cycles=16",
        "--virtual-ram-load-precheck",
        "--lsu-entries=4",
        "--physical-load-ingress-flow",
        "--ddr-write-collection-flow",
        "--line-transfer-dispatch-flow",
        "--line-read-channel",
        "--dtlb-write-read-reuse",
        "--translation-hit-flow",
        "--independent-demand-admission",
        "--split-prefetch-tracking",
        "--read-prefetch-dirty-retry",
        "--read-prefetch-demand-adoption",
        "--load-order-older-retire",
        "--fetch-previous-packet",
        "--prepared-store-lookahead",
        "--store-next-line-prefetch",
        "--store-prefetch-mru-insertion",
        "--posted-store-merge",
        "--posted-prefetch-coexistence",
        "--posted-prefetch-head-offer",
        "--canonical-virtual-store-overlap",
        "--published-pmp-changes",
        "--frozen-store-proof-transport",
        "--pending-virtual-store-proof",
        "--pending-virtual-store-proof-slots=2",
        "--bound-head-store-overlap",
        "--read-prefetch-store-hold",
        "--pending-ready-store-bypass",
        "--durable-read-prefetch-candidate",
        "--read-prefetch-behind-store",
        "--pending-store-early-load-credits=2",
        "--tagged-store-returns",
        "--internal-line-grant",
        "--concurrent-read-store-prefetch",
        "--memory-schedule-overlap",
        "--registered-pending-store-query",
        "--aligned-fetch-permission-stage",
        "--registered-canonical-store-event",
        "--shared-lane1-owner-match",
        "--direct-rank1-memory-source-ids",
        "--direct-registered-execution-operands",
        "--local-payload-write-enable",
        "--shared-canonical-store-owner-match",
        "--local-payload-write-row",
        "--predecoded-head-drain",
        "--retirement-intent",
        "--fetch-address-before-pmp",
        "--queued-head-selection",
        "--aligned-next-line-pmp",
        "--register-probe-lookup",
        "--local-address-ranges",
        "--fetch-ready-data-clear",
        "--memory-preparation-head-mask",
        "--direct-rank0-memory-source-ids",
        "--retirement-slot-identity",
        "--local-cache-read-selection",
        "--fetch-accepted-prefix-validation",
        "--aligned-fetch-single-page",
        "--factor-checked-next-allowed",
        "--local-tagged-response-ready")
    require(options.size == 68 && options.distinct.size == 68)
    val baseline: OooParams = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false).coreParams
    def params(enabled: Boolean): OooParams = {
        val p = baseline.copy(residentMemoryPayloadReuse = enabled)
        require(p.copy(residentMemoryPayloadReuse = false) == baseline,
            "P2 OFF/ON may differ only in residentMemoryPayloadReuse")
        require(p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64 &&
            p.compressedInstructions && p.dataReturnHandleBits > 0)
        p
    }
}

/** P2 is a real backend entry test, not a CPU/VM/cache integration test.
  * M-mode physical loads use the actual backend/LSU with a host data responder.
  * Optional authorization ports offer no proof and no external busy condition.
  */
class ResidentMemoryEntryGsim(enabled: Boolean) extends Module {
    val p = ResidentMemoryEntryProfile.params(enabled)
    val io = IO(new Bundle {
        val instruction0 = Input(Valid(UInt(32.W)))
        val instruction1 = Input(Valid(UInt(32.W)))
        val pc0 = Input(UInt(64.W))
        val pc1 = Input(UInt(64.W))
        // Deliberately malformed direct-backend offer after the real decoder.
        val badSource20 = Input(Bool())
        val badSource21 = Input(Bool())
        val decoded0 = Output(new IntegerRequest)
        val decoded1 = Output(new IntegerRequest)
        val offered0 = Output(new IntegerRequest)
        val offered1 = Output(new IntegerRequest)
        val legal0 = Output(Bool())
        val legal1 = Output(Bool())
        val compressed0 = Output(Bool())
        val compressed1 = Output(Bool())
        val renamed0 = Output(Valid(new RenamedInstruction(p)))
        val renamed1 = Output(Valid(new RenamedInstruction(p)))
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val commitEnable = Input(Bool())
        val occupancy = Output(UInt(p.countBits.W))
        val memory = new DataPort(p.dataReturnHandleBits)
        val memoryBusy = Output(Bool())
        val lsuOffer = Output(Bool())
        val lsuFire = Output(Bool())
        val lsu = Output(new MemoryOperation(p))
        val lsuRequestFire = Output(Bool())
        val lsuRequestOwner = Output(Valid(new RobToken(p)))
        val headException = Output(Valid(new HeadException(p)))
        val trap = Output(Valid(new HeadException(p)))
        val redirect = Output(Valid(new FrontendRedirect(p)))
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
    })
    val backend = Module(new IntegerBackend(p,
        registerCanonicalStoreEvent = p.registeredCanonicalStoreEvent,
        retirementSlotIdentity = p.retirementSlotIdentity))
    val raw = Seq(io.instruction0, io.instruction1)
    val pcs = Seq(io.pc0, io.pc1)
    val malformed = Seq(io.badSource20, io.badSource21)
    val decoded = Seq(io.decoded0, io.decoded1)
    val offered = Seq(io.offered0, io.offered1)
    val legal = Seq(io.legal0, io.legal1)
    val compressed = Seq(io.compressed0, io.compressed1)
    for (lane <- 0 until 2) {
        val decoder = Module(new IntegerDecode(p.machineSystem, p.atomicMemory,
            p.parallelDecodeLegality, p.parallelBitLegality, p.fpEnabled, p.fpConfig))
        val isCompressed = raw(lane).bits(1, 0) =/= 3.U
        val (expanded, expansionLegal) = Compressed.expand(raw(lane).bits(15, 0),
            floatingDouble = p.fpEnabled && p.fpConfig.d && p.fpConfig.memory)
        decoder.io.instruction := Mux(isCompressed, Mux(expansionLegal, expanded, 0.U), raw(lane).bits)
        decoder.io.pc := pcs(lane)
        decoded(lane) := decoder.io.decoded
        compressed(lane) := isCompressed
        legal(lane) := decoder.io.legal && (!isCompressed || expansionLegal)
        val request = WireDefault(decoder.io.decoded)
        request.rename.instruction := raw(lane).bits
        when(malformed(lane)) { request.rename.rs2 := 5.U }
        offered(lane) := request
        backend.io.allocate(lane).valid := raw(lane).valid
        backend.io.allocate(lane).bits := request
        backend.io.rawDestinations.foreach(_(lane) := decoder.io.instruction(11, 7))
        backend.io.rawRequests.foreach(_(lane) := request.rename)
    }
    backend.io.fetchFaultMask.foreach(_ := 0.U)
    backend.io.commitEnable := io.commitEnable
    backend.io.recover := 0.U.asTypeOf(backend.io.recover)
    backend.io.inspectRegister := io.inspectRegister
    backend.io.imsic.foreach { imsic =>
        imsic.request.ready := true.B
        imsic.response.valid := false.B
        imsic.response.bits := 0.U.asTypeOf(imsic.response.bits)
    }
    backend.io.externalInterrupt.foreach(_ := false.B)
    backend.io.supervisorExternalInterrupt.foreach(_ := false.B)
    backend.io.timerInterrupt.foreach(_ := false.B)
    backend.io.timeValue.foreach(_ := 0.U)
    backend.io.emptyPc.foreach(_ := 0.U)
    backend.io.fetchQuiescent.foreach(_ := true.B)
    backend.io.fenceIFlushReady.foreach(_ := true.B)
    backend.io.vmFlushReady.foreach(_ := true.B)
    backend.io.externalPrefetchBusy.foreach(_ := false.B)
    backend.io.loadPrecheck.foreach { query =>
        query.response := 0.U.asTypeOf(query.response)
        query.epoch := 0.U
        query.stable := true.B
    }
    backend.io.canonicalStore.foreach { canonical =>
        canonical.checked := 0.U.asTypeOf(canonical.checked)
    }
    backend.io.posted.foreach { posted =>
        posted.contextEpoch := 0.U
        posted.externalBusy := false.B
        posted.blockNew := false.B
    }
    io.renamed0 := backend.io.renamed(0)
    io.renamed1 := backend.io.renamed(1)
    io.commit0 := backend.io.commit(0)
    io.commit1 := backend.io.commit(1)
    io.occupancy := backend.io.occupancy
    io.memory <> backend.io.memory
    io.memoryBusy := backend.io.memoryBusy
    io.lsuOffer := BoringUtils.bore(backend.lsu.io.start.valid)
    io.lsuFire := BoringUtils.bore(backend.lsu.io.start.valid) && BoringUtils.bore(backend.lsu.io.start.ready)
    io.lsu := BoringUtils.bore(backend.lsu.io.start.bits)
    io.lsuRequestFire := BoringUtils.bore(backend.lsu.io.memory.request.valid) &&
        BoringUtils.bore(backend.lsu.io.memory.request.ready)
    io.lsuRequestOwner := BoringUtils.bore(backend.lsu.io.requestOwner)
    io.headException := backend.io.headException
    io.trap := backend.io.trap.get
    io.redirect := backend.io.redirect
    io.committedValue := backend.io.committedValue
}

object ResidentMemoryEntryGsimMain extends App {
    require(args.length == 2 && Set("off", "on").contains(args(1)),
        "usage: ResidentMemoryEntryGsimMain output-directory off|on")
    val enabled = args(1) == "on"
    val out = Paths.get(args(0))
    Files.createDirectories(out)
    val p = ResidentMemoryEntryProfile.params(enabled)
    val manifest = new String(Files.readAllBytes(Paths.get("fpga/next/near-term-a-profile.json")), "UTF-8")
    val nativeArray = "(?s)\"native_options\"\\s*:\\s*\\[(.*?)\\]".r.findFirstMatchIn(manifest).get.group(1)
    val pinnedOptions = "\"(--[^\"]+)\"".r.findAllMatchIn(nativeArray).map(_.group(1)).toSeq
    require(pinnedOptions == ResidentMemoryEntryProfile.options, "fixture A68 vector differs from pinned manifest")
    Files.writeString(out.resolve("profile.json"), PostedBoardConfiguration.json(Map(
        "schema" -> "resident-memory-entry-p2-v1", "baseCommit" -> "bb85d08bda18121b1b848fbbbd004af50f2cc504",
        "options" -> ResidentMemoryEntryProfile.options, "core" -> p.productElementNames.zip(p.productIterator).toMap,
        "solePairDifference" -> "residentMemoryPayloadReuse", "backendOnly" -> true,
        "wholeCpuQualified" -> false, "virtualMemoryQualified" -> false)) + "\n")
    ChiselStage.emitCHIRRTLFile(new ResidentMemoryEntryGsim(enabled), Array("--target-dir", args(0)))
}
