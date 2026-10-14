package soc.core.ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}

/** Read the unchanged 52-option CPU profile, excluding the separate MAC overlay. */
object HeadDrainTestProfile {
    private val root = Iterator.iterate(Paths.get("").toAbsolutePath)(_.getParent)
        .takeWhile(_ != null).find(path => Files.isRegularFile(path.resolve("build.mill"))).get
    private val text = Files.readString(root.resolve("fpga/next/timing-batch-owner-row-profile.json"))
    private val list = "(?s)\"native_options\"\\s*:\\s*\\[(.*?)\\]".r.findFirstMatchIn(text).get.group(1)
    val options: Seq[String] = "\"([^\"]*)\"".r.findAllMatchIn(list).map(_.group(1)).toSeq
    require(options.size == 52 && options.distinct.size == 52)
    require(!options.contains("--future-home-way-reservation") && !options.contains("--eager-fetch-prefix-select"))
    val config: FpgaNextConfig = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
    _root_.ooo.PlacedTimingProfileBridge.requireShape(config)
    _root_.ooo.PlacedTimingProfileBridge.publishedFields(config)
    _root_.ooo.PlacedTimingProfileBridge.publishedFields(config.coreParams)
    val off: OooParams = config.coreParams
    require(!config.fetchAcceptedPrefixValidation && !config.alignedFetchSinglePage &&
        !config.factorCheckedNextAllowed && !config.localTaggedResponseReady)
    val on: OooParams = off.copy(predecodedHeadDrain = true)
    require(!config.futureHomeWayReservation && !off.eagerFetchPrefixSelect && !off.predecodedHeadDrain)
    require(off.robEntries == 16 && off.physicalRegs == 48 && off.tagBits == 64 && off.issueWidth == 2)
    require(on.copy(predecodedHeadDrain = false) == off && off.productArity == 175)
    require(off.productElementName(159) == "predecodedHeadDrain" &&
        off.productElementName(160) == "retirementIntent" && !off.retirementIntent && !on.retirementIntent)
    require(config.productArity == 92 && config.productElementName(73) == "retirementIntent" &&
        !config.retirementIntent)
    def writeParameters(directory: String): Unit = {
        val path = Paths.get(directory)
        Files.createDirectories(path)
        def json(value: Any): String = value match {
            case fields: Product => fields.productElementNames.zip(fields.productIterator).map {
                case (name, item) => "\"" + name + "\":" + json(item)
            }.mkString("{", ",", "}")
            case text: String => "\"" + text.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
            case scalar => scalar.toString
        }
        Files.writeString(path.resolve("actual-core-off.json"), json(off) + "\n")
        Files.writeString(path.resolve("actual-core-on.json"), json(on) + "\n")
        Files.writeString(path.resolve("native-options.txt"), options.mkString("", "\n", "\n"))
    }
}

/** Small combinational DUT boundary for an independent software encoding catalog. */
class HeadDrainDecodeGsim extends Module {
    val io = IO(new Bundle {
        val original = Input(UInt(32.W))
        val expanded = Input(UInt(32.W))
        val class0 = Output(Bool())
        val class8 = Output(Bool())
        val class16 = Output(Bool())
        val classCompressed = Output(Bool())
    })
    val base = OooParams(machineSystem = true)
    io.class0 := HeadDrainClass(io.original, io.expanded, base)
    io.class8 := HeadDrainClass(io.original, io.expanded, base.copy(pmpEntries = 8, virtualMemoryLevels = 3))
    io.class16 := HeadDrainClass(io.original, io.expanded, base.copy(pmpEntries = 16, virtualMemoryLevels = 3))
    io.classCompressed := HeadDrainClass(io.original, io.expanded,
        base.copy(pmpEntries = 16, virtualMemoryLevels = 3, compressedInstructions = true))
}

class HeadDrainOffer extends Bundle {
    val valid = Bool()
    val original = UInt(32.W)
    val expanded = UInt(32.W)
    val system = Bool()
    val fault = Bool()
    val pageFault = Bool()
    val rs1 = UInt(5.W)
    val rd = UInt(5.W)
    val writesRd = Bool()
    val memory = Bool()
    val immediate = UInt(64.W)
    val expectedClass = Bool()
}

/** Actual matched OFF/ON backends. Inputs are already-decoded backend requests;
  * no frontend/ISA-legality or physical-service qualification is implied.
  * Peripheral responses are inactive; memory requests are held and observed.
  */
class HeadDrainBackendPairGsim extends Module {
    val p = HeadDrainTestProfile.off
    val io = IO(new Bundle {
        val offer0 = Input(new HeadDrainOffer)
        val offer1 = Input(new HeadDrainOffer)
        val pc = Input(UInt(64.W))
        val commitEnable = Input(Bool())
        val fetchQuiescent = Input(Bool())
        val fenceReady = Input(Bool())
        val recover = Input(Valid(new RecoveryRequest(p)))
        val renamed0 = Output(Valid(new RobToken(p)))
        val renamed1 = Output(Valid(new RobToken(p)))
        val occupancy = Output(UInt(p.countBits.W))
        val head = Output(UInt(p.robBits.W))
        val pendingMask = Output(UInt(p.robEntries.W))
        val savedMask = Output(UInt(p.robEntries.W))
        val liveMask = Output(UInt(p.robEntries.W))
        val headPending = Output(Bool())
        val headSystem = Output(Bool())
        val headOriginal = Output(UInt(32.W))
        val headExpanded = Output(UInt(32.W))
        val pauseFetch = Output(Bool())
        val reserveSystem = Output(Bool())
        val systemStart = Output(Bool())
        val fenceFlush = Output(Bool())
        val memoryPrepared = Output(Bool())
        val lsuStart = Output(Bool())
        val recoveryAccepted = Output(Bool())
        val recovering = Output(Bool())
        val committed = Output(UInt(2.W))
        val trap = Output(Bool())
        val redirect = Output(Bool())
    })
    val requests = Seq(io.offer0, io.offer1).zipWithIndex.map { case (offer, lane) =>
        val request = WireDefault(0.U.asTypeOf(Valid(new IntegerRequest)))
        request.valid := offer.valid
        request.bits.rename.pc := io.pc + (4 * lane).U
        request.bits.rename.instruction := offer.original
        request.bits.expandedInstruction := offer.expanded
        request.bits.system := offer.system
        request.bits.fetchFault := offer.fault
        request.bits.fetchPageFault := offer.pageFault
        request.bits.fetchTval := io.pc + (4 * lane).U
        request.bits.operation := IntegerOp.add
        request.bits.useImmediate := true.B
        request.bits.rename.rs1 := offer.rs1
        request.bits.rename.rd := offer.rd
        request.bits.rename.writesRd := offer.writesRd
        request.bits.memory := offer.memory
        request.bits.memorySize := 3.U
        request.bits.immediate := offer.immediate
        request
    }
    val backends = Seq(p, HeadDrainTestProfile.on).map { params =>
        val b = Module(new IntegerBackend(params, registerCanonicalStoreEvent = params.registeredCanonicalStoreEvent))
        b.io.allocate := VecInit(requests)
        b.io.rawDestinations.foreach(_ := VecInit(requests.map(_.bits.rename.rd)))
        b.io.rawRequests.foreach(_ := VecInit(requests.map(_.bits.rename)))
        b.io.fetchFaultMask.foreach(_ := VecInit(requests.map(r => r.bits.fetchFault || r.bits.fetchPageFault)).asUInt)
        b.io.commitEnable := io.commitEnable
        b.io.recover := io.recover
        b.io.inspectRegister := 0.U
        b.io.imsic.get.request.ready := true.B
        b.io.imsic.get.response.valid := false.B
        b.io.imsic.get.response.bits := 0.U.asTypeOf(b.io.imsic.get.response.bits)
        b.io.externalInterrupt.get := false.B
        b.io.supervisorExternalInterrupt.get := false.B
        b.io.timerInterrupt.get := false.B
        b.io.timeValue.get := 0.U
        b.io.emptyPc.get := io.pc
        b.io.fetchQuiescent.get := io.fetchQuiescent
        b.io.fenceIFlushReady.get := io.fenceReady
        b.io.vmFlushReady.get := io.fenceReady
        b.io.externalPrefetchBusy.foreach(_ := false.B)
        b.io.memory.request.ready := false.B
        b.io.memory.response.valid := false.B
        b.io.memory.response.bits := 0.U.asTypeOf(b.io.memory.response.bits)
        b.io.loadPrecheck.foreach { port =>
            port.response := 0.U.asTypeOf(port.response)
            port.epoch := 0.U
            port.stable := true.B
        }
        b.io.canonicalStore.foreach(port => port.checked := 0.U.asTypeOf(port.checked))
        b.io.posted.foreach { port =>
            port.contextEpoch := 0.U
            port.externalBusy := false.B
            port.blockNew := false.B
        }
        b
    }
    val off = backends.head
    val on = backends(1)
    def tap[T <: Data](value: T): T = BoringUtils.bore(value)
    def sameValid[T <: Data](a: ValidIO[T], b: ValidIO[T], label: String): Unit = {
        assert(a.valid === b.valid, s"head-drain pair $label valid")
        when(a.valid) { assert(a.bits.asUInt === b.bits.asUInt, s"head-drain pair $label payload") }
    }
    for (lane <- 0 until 2) {
        sameValid(off.io.renamed(lane), on.io.renamed(lane), s"rename $lane")
        sameValid(off.io.commit(lane), on.io.commit(lane), s"commit $lane")
        sameValid(off.io.issued(lane), on.io.issued(lane), s"issue $lane")
    }
    sameValid(off.io.headException, on.io.headException, "head exception")
    sameValid(off.io.redirect, on.io.redirect, "redirect")
    sameValid(off.io.trap.get, on.io.trap.get, "trap")
    assert(off.io.memory.request.valid === on.io.memory.request.valid, "head-drain pair memory valid")
    when(off.io.memory.request.valid) {
        assert(off.io.memory.request.bits.asUInt === on.io.memory.request.bits.asUInt, "head-drain pair memory payload")
    }
    for ((a, b) <- Seq(
        off.io.pauseFetch.get -> on.io.pauseFetch.get,
        off.io.recoveryAccepted -> on.io.recoveryAccepted,
        off.io.recovering -> on.io.recovering,
        off.io.fenceIFlush.get -> on.io.fenceIFlush.get,
        off.io.vmFlush.get -> on.io.vmFlush.get,
        off.io.memoryBusy -> on.io.memoryBusy,
        tap(off.reserveSystem) -> tap(on.reserveSystem),
        tap(off.systemStart) -> tap(on.systemStart),
        tap(off.pendingStoreProof.get.io.flushQueries) -> tap(on.pendingStoreProof.get.io.flushQueries),
        tap(off.lsu.io.start.valid) -> tap(on.lsu.io.start.valid),
        tap(off.lsu.io.start.ready) -> tap(on.lsu.io.start.ready))) {
        assert(a === b, "head-drain pair scheduling authority")
    }
    assert(off.io.occupancy === on.io.occupancy && tap(off.pending).asUInt === tap(on.pending).asUInt,
        "head-drain pair owner state")
    assert(tap(off.head) === tap(on.head), "head-drain pair head")
    assert(tap(off.stagedMemoryValid.get) === tap(on.stagedMemoryValid.get),
        "head-drain pair staged memory valid")
    when(tap(off.stagedMemoryValid.get)) {
        assert(tap(off.stagedMemoryToken.get).asUInt === tap(on.stagedMemoryToken.get).asUInt &&
            tap(off.stagedMemoryAddress.get) === tap(on.stagedMemoryAddress.get) &&
            tap(off.stagedMemoryData.get) === tap(on.stagedMemoryData.get), "head-drain pair staged memory payload")
    }
    when(tap(off.lsu.io.start.valid)) {
        assert(tap(off.lsu.io.start.bits).asUInt === tap(on.lsu.io.start.bits).asUInt,
            "head-drain pair LSU start payload")
    }

    // Independent software oracle bits are captured only with actual accepted
    // renames. Never compare uninitialized/stale row payload as though it were valid.
    val expected = Reg(Vec(p.robEntries, Bool()))
    val tags = Reg(Vec(p.robEntries, UInt(p.tagBits.W)))
    val written = RegInit(VecInit(Seq.fill(p.robEntries)(false.B)))
    for (lane <- 0 until 2) {
        val r = off.io.renamed(lane)
        when(r.valid) {
            expected(r.bits.token.index) := Seq(io.offer0, io.offer1)(lane).expectedClass
            tags(r.bits.token.index) := r.bits.token.tag
            written(r.bits.token.index) := true.B
        }
    }
    val saved = tap(on.headDrainClasses.get)
    val pending = tap(on.pending)
    val metadata = tap(on.issueEntries)
    val ledgerTags = tap(on.ledger.entries).map(_.tag)
    val ledgerHead = tap(on.ledger.head)
    val live = VecInit((0 until p.robEntries).map { row =>
        val age = (row.U(p.robBits.W) - ledgerHead)(p.robBits - 1, 0)
        age < on.io.occupancy
    })
    for (row <- 0 until p.robEntries) {
        val owned = live(row) && pending(row) && written(row) &&
            metadata(row).renamed.token.index === row.U &&
            metadata(row).renamed.token.tag === tags(row) && ledgerTags(row) === tags(row)
        when(live(row) && pending(row)) { assert(owned, "head-drain oracle owner witness") }
        when(owned) { assert(saved(row) === expected(row), "head-drain accepted-row oracle") }
    }
    io.renamed0.valid := off.io.renamed(0).valid
    io.renamed0.bits := off.io.renamed(0).bits.token
    io.renamed1.valid := off.io.renamed(1).valid
    io.renamed1.bits := off.io.renamed(1).bits.token
    io.occupancy := off.io.occupancy
    io.head := tap(off.head)
    io.pendingMask := pending.asUInt
    io.savedMask := saved.asUInt
    io.liveMask := live.asUInt
    io.headPending := pending(io.head)
    io.headSystem := metadata(io.head).request.system
    io.headOriginal := tap(off.headRequest.rename.instruction)
    io.headExpanded := tap(off.headRequest.expandedInstruction)
    io.pauseFetch := off.io.pauseFetch.get
    io.reserveSystem := tap(off.reserveSystem)
    io.systemStart := tap(off.systemStart)
    io.fenceFlush := off.io.fenceIFlush.get
    io.memoryPrepared := tap(off.stagedMemoryValid.get)
    io.lsuStart := tap(off.lsu.io.start.valid) && tap(off.lsu.io.start.ready)
    io.recoveryAccepted := off.io.recoveryAccepted
    io.recovering := off.io.recovering
    io.committed := PopCount(off.io.commit.map(_.valid))
    io.trap := off.io.trap.get.valid
    io.redirect := off.io.redirect.valid
}

