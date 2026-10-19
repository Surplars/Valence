package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.tilelink.{TileLinkLineProbeEngine, TileLinkLineTransfer}
import soc.core.ooo.{CacheTagConfig, HomeRamRange, ParallelHomeLineMatch}

/** Serialized TL-C home for private T owners. A line has at most one owner; a competing
  * client or uncached agent probes that owner before accessing backing RAM. The client
  * count is explicit so source IDs and probe/GrantAck routing remain local to each hart.
  */
class I1CoherentLineHome(
    params: TLParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3),
    base: BigInt = BigInt("80010000", 16),
    bytes: BigInt = 4096,
    nClients: Int = 1,
    trackedLines: Int = 0,
    trackedWays: Int = 1,
    rawResponseMetadata: Boolean = false,
    parallelQualification: Boolean = false,
    tagConfig: CacheTagConfig = CacheTagConfig.FullWidth,
    ordinaryWritePipeline: Boolean = false,
    lineDispatchFlow: Boolean = false,
    wholeLineRead: Boolean = false,
    internalLineGrant: Boolean = false, writebackOverlap: Boolean = false,
    readOverlap: Boolean = false
) extends I1CoherentLineHomeModule(params, nClients, wholeLineRead, internalLineGrant) {
    require(!writebackOverlap || (parallelQualification && internalLineGrant))
    require(!readOverlap || (writebackOverlap && nClients == 2))
    require(bytes >= 64 && bytes % 64 == 0 && isPow2(bytes) && base % 64 == 0)
    require(nClients >= 1 && nClients <= 8)
    require(trackedLines == 0 || (nClients <= 2 && trackedLines >= 2 &&
        trackedLines <= bytes / 64 && isPow2(trackedLines)))
    require(trackedLines != 0 || base % bytes == 0)
    require(nClients == 1 || (trackedLines > 0 && Set(2, 4).contains(trackedWays)),
        "two private clients require directory ways for their combined associativity")
    require(Set(1, 2, 4).contains(trackedWays) &&
        (trackedWays == 1 || (trackedLines != 0 && trackedLines / trackedWays >= 2)))
    require(params.sourceBits >= 3, "line transfer needs separate read and write source IDs")
    private def client(index: UInt): TLBundle = if (nClients == 1) io.clients(0) else io.clients(index)
    private val clientBits = math.max(1, log2Ceil(nClients))
    private val Seq(idle, probeSend, probeWait, accessSend, accessWait, fillSend, fillWait,
        grant, grantAck, releaseReceive, lineWriteSend, lineWriteWait, releaseAck) = homeStates
    private val stateStorage = RegInit(idle); private val state = WireDefault(UInt(idle.getWidth.W), stateStorage)
    private val resume = Reg(UInt(state.getWidth.W))
    private val reads = RegInit(0.U(4.W))
    // Reuse the existing outstanding counter for same-direction cohorts.
    // A write cohort never crosses reads, MMIO, probes, releases or acquires.
    private val cohortWrite = if (ordinaryWritePipeline) Some(Reg(Bool())) else None
    private val access = Reg(new I1DataRequest)
    private val acquireAddress = Reg(UInt(params.addrWidth.W))
    private val acquireSource = Reg(UInt(params.sourceBits.W))
    private val acquireClient = Reg(UInt(clientBits.W))
    private val probeAddress = Reg(UInt(params.addrWidth.W))
    private val probeClient = Reg(UInt(clientBits.W))
    private val probeForAcquire = Reg(Bool())
    private val lineAddress = Reg(UInt(params.addrWidth.W))
    private val lineData = Reg(Vec(8, UInt(64.W)))
    private val lineError = Reg(Bool())
    private val beat = RegInit(0.U(3.W))
    private val releaseSource = Reg(UInt(params.sourceBits.W))
    private val releaseClient = Reg(UInt(clientBits.W))
    private val releaseParam = Reg(UInt(3.W))
    private val releaseOrigin = Reg(Bool())
    // The second read BORROWS the existing release address/source/client/row
    // context. These two transaction kinds are mutually exclusive. Its data
    // stays in the existing two-slot line reader until the real Grant fire.
    private val pairedRead = if (readOverlap) Some(RegInit(false.B)) else None
    private val pairedAck = if (readOverlap) Some(RegInit(false.B)) else None
    private val pairedSend = if (readOverlap) Some(RegInit(false.B)) else None
    private val secondReadLive = pairedRead.getOrElse(false.B)
    private val primaryInstall = WireDefault(false.B)
    private val secondInstall = WireDefault(false.B)
    // Retain ONLY the existing release context while its real backing write
    // finishes. lineData is free once the existing line writer captured it.
    private val releaseWritePending = if (writebackOverlap) Some(RegInit(false.B)) else None
    private val releaseAckPending = if (writebackOverlap) Some(RegInit(false.B)) else None
    private val detachedRelease = releaseWritePending.getOrElse(false.B) || releaseAckPending.getOrElse(false.B)
    private val releaseDPhase = if (writebackOverlap)
        in(releaseAck) || releaseAckPending.get else in(releaseAck)
    private val ownerEntries = if (trackedLines == 0) (bytes / 64).toInt else trackedLines
    private val owned = RegInit(VecInit(Seq.fill(ownerEntries)(false.B)))
    // Resolved rows extend the EXISTING serialized transaction contexts.
    // They are not more directory entries or outstanding Home transactions.
    private val ownerIndexBits = math.max(1, log2Ceil(ownerEntries))
    private val acquireSlot = if (parallelQualification) Some(Reg(UInt(ownerIndexBits.W))) else None
    private val probeSlot = if (parallelQualification) Some(Reg(UInt(ownerIndexBits.W))) else None
    private val releaseSlot = if (parallelQualification) Some(Reg(UInt(ownerIndexBits.W))) else None
    private val acquireHadSpace = if (parallelQualification) Some(Reg(Bool())) else None
    private val installOwner = WireDefault(false.B)
    private val clearProbedOwner = WireDefault(false.B)
    private val clearReleasedOwner = WireDefault(false.B)
    // A single L1 owns at most trackedWays physical lines per cache set.
    // Directory slots need not use the client's physical way number: tag lookup
    // finds owners, and a completed GrantAck reserves an empty slot in that set.
    // Capacity stays bounded by L1 capacity rather than external RAM size.
    private val tagGeometry = tagConfig.geometry(base, bytes, 6, params.addrWidth)
    private val ownerSetBits = log2Ceil(ownerEntries / trackedWays)
    // The set bits are already implicit in the RAM address. Four compact
    // 256-deep banks cover two 32KiB/two-way caches without a 1024-entry
    // resettable payload vector or repeated wide asynchronous FF muxes.
    private val directoryTagBits = math.max(1, tagGeometry.tagBits - ownerSetBits)
    private val directoryBanks = Seq.fill(trackedWays)(
        Mem(ownerEntries / trackedWays, UInt((directoryTagBits + clientBits).W)))
    // Memory-array attributes are applied by the exact physical exporter;
    // firtool rejects AttributeAnnotation targeting a memory operation itself.
    private val directoryAddress = Wire(UInt(params.addrWidth.W))
    private val directorySet = directoryAddress(5 + ownerSetBits, 6)
    private val directoryWords = VecInit(directoryBanks.map(_.read(directorySet)))
    // Separate addresses, not duplicated directory owners. A.valid/priority
    // selection must not sit BEFORE the asynchronous directory read.
    private val acquireWords = if (parallelQualification)
        Some(io.clients.map(c => VecInit(directoryBanks.map(_.read(c.a.bits.address(5 + ownerSetBits, 6))))))
        else None
    // Resolve each raw voluntary C address BEFORE C-valid/FSM/client selection.
    // The selected result is captured once; maintenance never rereads tags
    // on GrantAck, backing-write completion or the directory write-enable path.
    // This is an extra read port, not extra directory capacity/payload FF.
    private val releaseWords = if (parallelQualification)
        Some(io.clients.map(c => VecInit(directoryBanks.map(_.read(c.c.bits.address(5 + ownerSetBits, 6))))))
        else None
    private val maintenanceAddress = Wire(UInt(params.addrWidth.W))
    private val maintenanceSet = maintenanceAddress(5 + ownerSetBits, 6)
    private val maintenanceWords = if (parallelQualification)
        VecInit(directoryBanks.map(_.read(maintenanceSet))) else directoryWords
    private def directoryTag(address: UInt): UInt =
        (tagGeometry.tag(address) >> ownerSetBits).pad(directoryTagBits)
    private def directoryWay(index: UInt): UInt =
        if (trackedWays == 1) 0.U else index(log2Ceil(ownerEntries) - 1, ownerSetBits)
    private def checkLookup(address: UInt, maintenance: Boolean = false): Unit =
        assert((if (maintenance && parallelQualification) maintenanceSet else directorySet) ===
            address(5 + ownerSetBits, 6), "directory read port belongs to its consuming operation")
    // The Home state machine serializes line/probe ownership. Four buffering
    // slots in each shared engine cannot create four Home transactions.
    private val lineTransfer = Module(new TileLinkLineTransfer(
        params.copy(sourceBits = params.sourceBits - 1), entries = 2,
        rawResponseMetadata = rawResponseMetadata, dispatchFlow = lineDispatchFlow,
        isolatedWriteLaunch = parallelQualification, lineReadChannel = wholeLineRead,
        serializedWrites = parallelQualification))
    io.lineRead.foreach(_ <> lineTransfer.io.lineRead.get)
    private val probeEngine = Module(new TileLinkLineProbeEngine(params, entries = 2))
    io.line <> lineTransfer.io.tl
    for (i <- 0 until nClients) {
        io.clients(i).b.valid := probeEngine.io.probe.valid && probeClient === i.U
        io.clients(i).b.bits := probeEngine.io.probe.bits
    }
    probeEngine.io.probe.ready := client(probeClient).b.ready

    private val aValid = VecInit(io.clients.map(_.a.valid))
    private val aAny = aValid.asUInt.orR
    private val aTurn = RegInit(0.U(clientBits.W))
    private val afterTurn = VecInit((0 until nClients).map(i => aValid(i) && i.U >= aTurn))
    private val aSelect = Wire(UInt(clientBits.W))
    aSelect := Mux(afterTurn.asUInt.orR, PriorityEncoder(afterTurn), PriorityEncoder(aValid))
    private val releaseValid = VecInit(io.clients.map(c =>
        c.c.valid && TLOpcode.isRelease(c.c.bits.opcode)))
    private val releaseAny = releaseValid.asUInt.orR
    private val releaseSelect = Wire(UInt(clientBits.W))
    releaseSelect := PriorityEncoder(releaseValid)
    private val cSelect = Mux(in(releaseReceive), releaseClient,
        Mux(releaseAny, releaseSelect, probeClient))
    private val clientC = client(cSelect).c

    // Only the selected transaction consumes the directory output. A held
    // ordinary offer cannot be preempted; voluntary releases may preempt a
    // probe. Every consuming edge asserts the selected RAM-address invariant.
    maintenanceAddress := Mux(in(grantAck), acquireAddress,
        Mux(in(lineWriteWait), lineAddress,
            Mux(in(probeSend) || in(probeWait), Mux(releaseAny, clientC.bits.address, probeAddress),
                Mux(releaseAny, clientC.bits.address, Mux(aAny, client(aSelect).a.bits.address,
                    io.upstream.request.bits.address)))))
    // Foreground admission is not driven by the Home FSM or by C selection.
    // Maintenance gets its own asynchronous RAM read port, not a selected-tag
    // feedback mux. Same directory capacity, same handshake/cycle behavior.
    directoryAddress := (if (parallelQualification) io.upstream.request.bits.address else maintenanceAddress)
    private def directorySlots(address: UInt): Seq[UInt] = {
        val set = address(5 + ownerSetBits, 6)
        (0 until trackedWays).map { way =>
            if (trackedWays == 1) set else Cat(way.U(log2Ceil(trackedWays).W), set)
        }
    }
    // Native indexed selection permits the FPGA's local MUX resources.
    // The previous expanded AND/OR ownership decoder increased placement
    // spread and LUT cost. Capacity and reset semantics are identical.
    private def wayOwned(address: UInt, way: Int): Bool = owned(directorySlots(address)(way))
    private def directoryMatches(address: UInt, maintenance: Boolean = false): Seq[Bool] =
        directorySlots(address).zipWithIndex.map { case (i, way) =>
            tagGeometry.qualifies(address) && wayOwned(address, way) &&
                (if (trackedLines == 0) true.B
                 else (if (maintenance) maintenanceWords else directoryWords)(way)(
                     directoryTagBits + clientBits - 1, clientBits) === directoryTag(address))
        }
    private def indexFromMatches(address: UInt, hits: Seq[Bool]): UInt = {
        val set = address(5 + ownerSetBits, 6)
        if (trackedWays == 1) set
        else {
            val matched = VecInit(hits)
            val empty = VecInit((0 until trackedWays).map(way => !wayOwned(address, way)))
            val selected = Mux(matched.asUInt.orR, PriorityEncoder(matched),
                Mux(empty.asUInt.orR, PriorityEncoder(empty), (trackedWays - 1).U))
            Cat(selected, set)
        }
    }
    private def lineIndex(address: UInt, maintenance: Boolean = false): UInt =
        indexFromMatches(address, directoryMatches(address, maintenance))
    private def lineOwned(address: UInt, maintenance: Boolean = false): Bool = {
        directoryMatches(address, maintenance).reduce(_ || _)
    }
    private def lineOwner(address: UInt, maintenance: Boolean = false): UInt = {
        val words = if (maintenance) maintenanceWords else directoryWords
        Mux1H(directoryMatches(address, maintenance).zipWithIndex.map { case (hit, way) =>
            hit -> words(way)(clientBits - 1, 0)
        })
    }
    private val acquireMatches = if (parallelQualification)
        io.clients.zipWithIndex.map { case (c, i) =>
            directorySlots(c.a.bits.address).zipWithIndex.map { case (slot, way) =>
                tagGeometry.qualifies(c.a.bits.address) && wayOwned(c.a.bits.address, way) &&
                    (if (trackedLines == 0) true.B else acquireWords.get(i)(way)(
                        directoryTagBits + clientBits - 1, clientBits) === directoryTag(c.a.bits.address))
            }
        } else Seq.empty
    private val selectedAcquireOwned = if (parallelQualification)
        Mux1H((0 until nClients).map(i => (aSelect === i.U) -> acquireMatches(i).reduce(_ || _)))
        else lineOwned(client(aSelect).a.bits.address)
    private val selectedAcquireOwner = if (parallelQualification)
        Mux1H((0 until nClients).flatMap(i => (0 until trackedWays).map(w =>
            (aSelect === i.U && acquireMatches(i)(w)) -> acquireWords.get(i)(w)(clientBits - 1, 0))))
        else lineOwner(client(aSelect).a.bits.address)
    private val selectedAcquireIndex = if (parallelQualification)
        Some(Mux1H((0 until nClients).map(i => (aSelect === i.U) ->
            indexFromMatches(io.clients(i).a.bits.address, acquireMatches(i))))) else None
    private val selectedAcquireSpace = if (parallelQualification)
        Some(Mux1H((0 until nClients).map { i =>
            val empty = (0 until trackedWays).map(way => !wayOwned(io.clients(i).a.bits.address, way)).reduce(_ || _)
            (aSelect === i.U) -> (acquireMatches(i).reduce(_ || _) || empty)
        })) else None
    private val selectedReleaseIndex = if (parallelQualification) {
        val indices = io.clients.zipWithIndex.map { case (c, i) =>
            val hits = directorySlots(c.c.bits.address).zipWithIndex.map { case (slot, way) =>
                tagGeometry.qualifies(c.c.bits.address) && wayOwned(c.c.bits.address, way) &&
                    (if (trackedLines == 0) true.B else releaseWords.get(i)(way)(
                        directoryTagBits + clientBits - 1, clientBits) === directoryTag(c.c.bits.address))
            }
            indexFromMatches(c.c.bits.address, hits)
        }
        Some(Mux1H((0 until nClients).map(i => (releaseSelect === i.U) -> indices(i))))
    } else None
    private def inRam(address: UInt): Bool =
        if (parallelQualification) HomeRamRange.contains(address, params.addrWidth, base, bytes)
        else address >= base.U(65.W) && address < (base + bytes).U(65.W)
    private val request = io.upstream.request.bits
    if (parallelQualification) when(in(idle)) {
        // The probe context is unowned in idle. Prepare its payload BEFORE
        // aperture/tag/ordinary-admission qualification; only the unchanged
        // accepted request below can enter probeSend and expose these bits.
        // A later Acquire has priority over an ordinary request, exactly as
        // READY arbitration does. Releases may delay/preempt, not consume,
        // this unowned context. No new stage or Home transaction is added.
        val a = client(aSelect).a.bits
        probeAddress := Mux(aAny, a.address, Cat(request.address(63, 6), 0.U(6.W)))
        probeClient := Mux(aAny, selectedAcquireOwner, lineOwner(request.address))
        probeSlot.get := Mux(aAny, selectedAcquireIndex.get, lineIndex(request.address))
        probeForAcquire := aAny
        access := request
    }
    // An ordinary read is offered combinationally to the downstream TL bridge.
    // Once stalled, it cannot be preempted by a later Acquire or voluntary C
    // release: the shared TL arbiter may already have locked this A producer.
    // Withdrawing that offer and waiting for a line fill deadlocks both paths.
    // The upstream request FIFO retains its head/payload until the same fire.
    private val directReadHeld = RegInit(false.B)
    when(directReadHeld) { directoryAddress := io.upstream.request.bits.address }
    io.drainDone := in(idle) && reads === 0.U && !directReadHeld && !releaseAny && !secondReadLive
    private val releaseAllowed = reads === 0.U && !directReadHeld && !detachedRelease && !secondReadLive &&
        (in(idle) || in(probeSend) || in(probeWait))
    private val needsProbe = !io.upstreamRequestCpu && inRam(request.address) &&
        lineOwned(request.address)
    private val upperWrite = io.upstream.request.valid && request.write
    private val pipelineWrite = ordinaryWritePipeline.B && request.write && inRam(request.address) && !needsProbe
    private val stagedAccess = (upperWrite && !pipelineWrite) || needsProbe
    private val cohortAllowed = if (ordinaryWritePipeline)
        reads === 0.U || cohortWrite.get === request.write else true.B
    private val directRead = in(idle) && !secondReadLive && io.upstream.request.valid && !stagedAccess &&
        cohortAllowed && (directReadHeld || (!io.drainRequest && !aAny && !releaseAny))

    io.downstream.request.valid := directRead || in(accessSend)
    io.downstream.request.bits := Mux(in(accessSend), access, request)
    io.upstream.request.ready := in(idle) && !secondReadLive &&
        (directReadHeld || (!io.drainRequest && !aAny && !releaseAny)) &&
        Mux(stagedAccess, reads === 0.U, cohortAllowed && io.downstream.request.ready)
    io.upstream.response.valid := Mux(in(accessWait), io.downstream.response.valid,
        in(idle) && reads =/= 0.U && io.downstream.response.valid)
    io.upstream.response.bits := io.downstream.response.bits
    io.downstream.response.ready := io.upstream.response.ready &&
        (in(accessWait) || (in(idle) && reads =/= 0.U))
    when(directRead && !io.downstream.request.ready) { directReadHeld := true.B }
    when(directRead && io.downstream.request.fire) { directReadHeld := false.B }
    when(directReadHeld) {
        assert(in(idle) && io.upstream.request.valid && !stagedAccess && cohortAllowed,
            "a stalled home direct read must retain its request until acceptance")
    }
    private val directFire = io.upstream.request.fire && !stagedAccess
    if (ordinaryWritePipeline) {
        when(directFire) {
            when(reads === 0.U) { cohortWrite.get := request.write }
            .otherwise { assert(cohortWrite.get === request.write, "Home mixed ordinary read/write cohorts") }
        }
    }
    when(directFire =/=
        (in(idle) && io.upstream.response.fire)) {
        reads := Mux(directFire, reads + 1.U, reads - 1.U)
    }
    when(in(idle) && io.upstream.request.fire && stagedAccess) {
        checkLookup(request.address)
        if (!parallelQualification) access := request
        when(needsProbe) {
            if (!parallelQualification) {
                probeAddress := Cat(request.address(63, 6), 0.U(6.W))
                probeClient := lineOwner(request.address)
                probeForAcquire := false.B
            }
        }
        state := Mux(needsProbe, probeSend, accessSend)
    }
    when(in(accessSend) && io.downstream.request.fire) { state := accessWait }
    when(in(accessWait) && io.upstream.response.fire) { state := idle }

    // A second DDR owner may read only a DIFFERENT, currently unowned line
    // with an existing empty directory row. Never overlap probes, ordinary
    // accesses, aliasing writeback addresses or directory-capacity exhaustion.
    private val overlapQualified = if (writebackOverlap)
        Some(RegInit(VecInit(Seq.fill(nClients)(false.B)))) else None
    overlapQualified.foreach { proofs =>
        for (i <- 0 until nClients) {
            val c = io.clients(i)
            val empty = (0 until trackedWays).map(way => !wayOwned(c.a.bits.address, way)).reduce(_ || _)
            val chosen = indexFromMatches(c.a.bits.address, acquireMatches(i))
            // No new request owner. A stalled TL A head is sticky; prepare a
            // one-bit authorization during the existing write-response wait,
            // rather than directory tag/empty/alias -> A READY in one cycle.
            proofs(i) := in(lineWriteWait) && c.a.valid && !c.a.ready &&
                !acquireMatches(i).reduce(_ || _) && empty && chosen =/= releaseSlot.get &&
                c.a.bits.address(params.addrWidth - 1, 6) =/= lineAddress(params.addrWidth - 1, 6)
        }
    }
    private val overlapAcquire = writebackOverlap.B && in(lineWriteWait) &&
        releaseOrigin && phaseIs(resume, idle) && detachedRelease &&
        overlapQualified.map(bits => Mux1H((0 until nClients).map(i =>
            (aSelect === i.U) -> bits(i)))).getOrElse(false.B)
    private val readQualified = if (readOverlap)
        Some(RegInit(VecInit(Seq.fill(nClients)(false.B)))) else None
    readQualified.foreach { proofs =>
        for (i <- 0 until nClients) {
            val a = io.clients(i).a
            val empty = (0 until trackedWays).map(way => !wayOwned(a.bits.address, way)).reduce(_ || _)
            val row = indexFromMatches(a.bits.address, acquireMatches(i))
            proofs(i) := in(fillWait) && !secondReadLive && !detachedRelease &&
                a.valid && !a.ready && acquireClient =/= i.U &&
                !acquireMatches(i).reduce(_ || _) && empty && row =/= acquireSlot.get &&
                a.bits.address(params.addrWidth - 1, 6) =/= acquireAddress(params.addrWidth - 1, 6)
        }
    }
    private val secondAcquire = readOverlap.B && in(fillWait) && !secondReadLive &&
        !detachedRelease &&
        readQualified.map(v => Mux1H((0 until nClients).map(i => (aSelect === i.U) -> v(i))))
            .getOrElse(false.B)
    for (i <- 0 until nClients) {
        io.clients(i).a.ready := !io.drainRequest && !secondReadLive &&
            (in(idle) || overlapAcquire || secondAcquire) &&
            reads === 0.U && !releaseAny && !directReadHeld &&
            aSelect === i.U
    }
    val selectedAcquire = client(aSelect).a.bits
    val secondAcquireFire = aAny && client(aSelect).a.fire && secondAcquire
    val acquireFire = aAny && client(aSelect).a.fire && !secondAcquire
    val acquiredOwned = if (parallelQualification)
        (0 until nClients).map(i => io.clients(i).a.fire && !secondAcquire &&
            acquireMatches(i).reduce(_ || _)).reduce(_ || _)
        else acquireFire && selectedAcquireOwned
    val immediateFill = if (parallelQualification)
        (0 until nClients).map(i => io.clients(i).a.fire && !secondAcquire &&
            !acquireMatches(i).reduce(_ || _)).reduce(_ || _)
        else acquireFire && !selectedAcquireOwned
    when(acquireFire) {
        val a = selectedAcquire
        if (!parallelQualification) checkLookup(a.address)
        aTurn := Mux(aSelect === (nClients - 1).U, 0.U, aSelect + 1.U)
        assert(a.opcode === TLOpcode.AcquireBlock &&
            a.param === TLPermissions.nToT && a.size === 6.U &&
            a.address(5, 0) === 0.U && inRam(a.address) &&
            (!selectedAcquireOwned || selectedAcquireOwner =/= aSelect),
            "home accepts an aligned nToT AcquireBlock from a non-owner")
        if (writebackOverlap) when(in(lineWriteWait)) {
            assert(writebackOverlap.B && !selectedAcquireOwned && selectedAcquireSpace.get &&
                selectedAcquireIndex.get =/= releaseSlot.get &&
                a.address(params.addrWidth - 1, 6) =/= lineAddress(params.addrWidth - 1, 6),
                "prepared overlap proof lost its sticky A head, independent row or nonaliasing writeback")
        }
        acquireAddress := a.address
        acquireSource := a.source
        acquireClient := aSelect
        acquireSlot.foreach(_ := selectedAcquireIndex.get)
        acquireHadSpace.foreach(_ := selectedAcquireSpace.get)
        when(selectedAcquireOwned) {
            if (parallelQualification) {
                assert(in(idle), "owned Acquire must reserve the idle probe context")
            } else {
                probeAddress := a.address
                probeClient := selectedAcquireOwner
                probeForAcquire := true.B
            }
            state := probeSend
        }.otherwise { state := Mux(lineTransfer.io.readRequest.ready, fillWait, fillSend) }
    }
    // A no-probe Acquire can reserve the line reader in its acceptance cycle.
    // If the reader is full, fillSend keeps the registered address stable until it opens.
    private val secondSend = secondAcquireFire || pairedSend.getOrElse(false.B)
    lineTransfer.io.readRequest.valid := in(fillSend) || immediateFill || secondSend
    lineTransfer.io.readRequest.bits.address := Mux(pairedSend.getOrElse(false.B), lineAddress,
        Mux(in(fillSend), acquireAddress, selectedAcquire.address))
    lineTransfer.io.readRequest.bits.tag := Mux(secondSend, 1.U, 0.U)
    when(lineTransfer.io.readRequest.fire && !secondSend) { state := fillWait }
    lineTransfer.io.readResponse.ready := in(fillWait) &&
        (!readOverlap.B || lineTransfer.io.readResponse.bits.tag === 0.U)
    when(lineTransfer.io.readResponse.fire && (!readOverlap.B || lineTransfer.io.readResponse.bits.tag === 0.U)) {
        for (i <- 0 until 8) {
            lineData(i) := lineTransfer.io.readResponse.bits.data(64 * i + 63, 64 * i)
        }
        lineError := lineTransfer.io.readResponse.bits.error
        beat := 0.U
        state := grant
    }
    private val dClient = Mux(releaseDPhase, releaseClient, acquireClient)
    for (i <- 0 until nClients) {
        io.clients(i).d.valid := ((!internalLineGrant.B && in(grant)) ||
            releaseDPhase) && dClient === i.U
        io.clients(i).d.bits := 0.U.asTypeOf(io.clients(i).d.bits)
        io.clients(i).d.bits.opcode := Mux(releaseDPhase, TLOpcode.ReleaseAck, TLOpcode.GrantData)
        io.clients(i).d.bits.param := Mux(releaseDPhase, 0.U, TLPermissions.toT)
        io.clients(i).d.bits.size := 6.U
        io.clients(i).d.bits.source := Mux(releaseDPhase, releaseSource, acquireSource)
        io.clients(i).d.bits.sink := 0.U
        io.clients(i).d.bits.denied := !releaseDPhase && in(grant) && lineError
        io.clients(i).d.bits.data := lineData(beat)
        io.clients(i).d.bits.corrupt := !releaseDPhase && in(grant) && lineError
    }
    when(client(dClient).d.fire && in(grant) && !releaseDPhase) {
        beat := beat + 1.U
        when(beat === 7.U) { state := grantAck }
    }
    io.lineGrants.foreach { grants =>
        for (i <- 0 until nClients) {
            grants(i).valid := in(grant) && acquireClient === i.U
            grants(i).bits.source := acquireSource
            grants(i).bits.sink := 0.U
            grants(i).bits.cap := TLPermissions.toT
            grants(i).bits.denied := lineError
            grants(i).bits.corrupt := lineError
            // Reuse the existing checked lineData bank. No extra response
            // payload, owner, source or sink; only the private transport widens.
            grants(i).bits.data := lineData.asUInt
            when(in(grant) && acquireClient === i.U && grants(i).fire) { state := grantAck }
            when(in(grant) && acquireClient === i.U && grants(i).valid) {
                assert((!io.clients(i).d.valid ||
                    io.clients(i).d.bits.opcode === TLOpcode.ReleaseAck) && beat === 0.U,
                    "private line grant overlapped or followed a legacy D beat")
            }
        }
    }
    for (i <- 0 until nClients) {
        io.clients(i).e.ready := in(grantAck) && acquireClient === i.U
    }
    when(in(grantAck) && client(acquireClient).e.fire) {
        checkLookup(acquireAddress, maintenance = true)
        assert(client(acquireClient).e.bits.sink === 0.U, "line home GrantAck sink mismatch")
        when(!lineError) {
            if (trackedLines != 0) {
                if (parallelQualification) {
                    assert(acquireHadSpace.get,
                        "private I/D clients must release a set slot before acquiring beyond combined capacity")
                } else {
                    assert(!owned(lineIndex(acquireAddress, maintenance = true)) ||
                        lineOwned(acquireAddress, maintenance = true),
                        "private I/D clients must release a set slot before acquiring beyond combined capacity")
                }
                if (tagConfig.compact) assert(tagGeometry.contains(acquireAddress), "home tag outside aperture")
            }
            val installIndex = if (parallelQualification) acquireSlot.get
                else lineIndex(acquireAddress, maintenance = true)
            primaryInstall := true.B
            if (parallelQualification) { installOwner := true.B }
            else owned(installIndex) := true.B
        }
        state := Mux(detachedRelease && !(releaseAckPending.getOrElse(false.B) &&
            client(releaseClient).d.fire), lineWriteWait, idle)
    }
    if (readOverlap) {
        when(lineTransfer.io.readResponse.valid && !reset.asBool) {
            assert((lineTransfer.io.readResponse.bits.tag === 0.U && in(fillWait)) ||
                (lineTransfer.io.readResponse.bits.tag === 1.U && secondReadLive && !pairedAck.get),
                "whole-line read reply has no matching primary/borrowed Home owner")
        }
        when(secondAcquireFire) {
            val a = selectedAcquire
            assert(!selectedAcquireOwned && selectedAcquireSpace.get &&
                selectedAcquireIndex.get =/= acquireSlot.get && aSelect =/= acquireClient &&
                a.address(params.addrWidth - 1, 6) =/= acquireAddress(params.addrWidth - 1, 6),
                "paired read lost independent directory row/client/line")
            assert(a.opcode === TLOpcode.AcquireBlock && a.param === TLPermissions.nToT &&
                a.size === 6.U && a.address(5, 0) === 0.U && inRam(a.address))
            pairedRead.get := true.B; pairedAck.get := false.B
            pairedSend.get := !lineTransfer.io.readRequest.ready
            lineAddress := a.address; releaseSource := a.source; releaseClient := aSelect
            releaseSlot.get := selectedAcquireIndex.get
            aTurn := Mux(aSelect === (nClients - 1).U, 0.U, aSelect + 1.U)
        }
        when(pairedSend.get && lineTransfer.io.readRequest.fire) { pairedSend.get := false.B }
        val secondResponse = secondReadLive && !pairedAck.get &&
            lineTransfer.io.readResponse.valid && lineTransfer.io.readResponse.bits.tag === 1.U
        when(secondResponse) {
            lineTransfer.io.readResponse.ready := io.lineGrants.get(releaseClient).ready
        }
        for (i <- 0 until nClients) {
            when(secondResponse && releaseClient === i.U) {
                val g = io.lineGrants.get(i)
                g.valid := true.B; g.bits.source := releaseSource; g.bits.sink := 1.U
                g.bits.cap := TLPermissions.toT
                g.bits.denied := lineTransfer.io.readResponse.bits.error
                g.bits.corrupt := lineTransfer.io.readResponse.bits.error
                g.bits.data := lineTransfer.io.readResponse.bits.data
            }
            // One tag-bank write per edge. Both clients may keep E asserted;
            // the primary installation wins and the second E is retained.
            when(secondReadLive && pairedAck.get && releaseClient === i.U) {
                io.clients(i).e.ready := !(in(grantAck) && !lineError &&
                    client(acquireClient).e.valid)
            }
        }
        when(secondResponse && lineTransfer.io.readResponse.fire) {
            pairedAck.get := true.B
            releaseParam := lineTransfer.io.readResponse.bits.error
        }
        when(secondReadLive && pairedAck.get && client(releaseClient).e.fire) {
            assert(client(releaseClient).e.bits.sink === 1.U, "paired GrantAck sink mismatch")
            pairedRead.get := false.B; pairedAck.get := false.B
            when(!releaseParam(0)) {
                secondInstall := true.B; installOwner := true.B
            }
        }
        when(secondReadLive) {
            assert(!detachedRelease && !releaseAllowed && !releaseDPhase &&
                !in(probeSend) && !in(probeWait) && !in(releaseReceive),
                "paired read aliases the existing release/probe context")
        }
    }

    // E arbitration above already retains a competing secondary GrantAck.
    // Describe that arbitration BEFORE the Mem operation: two mutually
    // exclusive Scala .write calls still create two RTL write ports and
    // expand this multi-read directory into FFs/muxes on FPGA. Keep exactly
    // one physical writer per bank, with no queue, extra cycle or new owner.
    private val installIndex = if (parallelQualification)
        Mux(secondInstall, releaseSlot.get, acquireSlot.get)
        else lineIndex(acquireAddress, maintenance = true)
    private val installSet = if (parallelQualification) installIndex(ownerSetBits - 1, 0)
        else directorySet
    private val installWord = Mux(secondInstall,
        Cat(directoryTag(lineAddress), releaseClient),
        Cat(directoryTag(acquireAddress), acquireClient))
    for (way <- 0 until trackedWays) {
        when((primaryInstall || secondInstall) && directoryWay(installIndex) === way.U) {
            directoryBanks(way).write(installSet, installWord)
        }
    }
    when(!reset.asBool) {
        assert(!(primaryInstall && secondInstall),
            "single directory writer requires retained secondary GrantAck arbitration")
    }

    probeEngine.io.request.valid := in(probeSend) && !releaseAny
    probeEngine.io.request.bits.address := probeAddress
    probeEngine.io.request.bits.tag := 0.U
    when(probeEngine.io.request.fire) { state := probeWait }
    probeEngine.io.response.ready := in(probeWait) && !releaseAny
    when(probeEngine.io.response.fire) {
        checkLookup(probeAddress, maintenance = true)
        assert(!probeEngine.io.response.bits.corrupt, "dirty probe data must not be corrupt")
        if (parallelQualification) clearProbedOwner := true.B
        else owned(lineIndex(probeAddress, maintenance = true)) := false.B
        when(probeEngine.io.response.bits.hasData) {
            lineAddress := probeAddress
            for (i <- 0 until 8) {
                lineData(i) := probeEngine.io.response.bits.data(64 * i + 63, 64 * i)
            }
            lineError := false.B
            beat := 0.U
            releaseOrigin := false.B
            state := lineWriteSend
        }.otherwise { state := Mux(probeForAcquire, fillSend, accessSend) }
    }

    // C is shared by probe acknowledgements and voluntary releases. A release can preempt a
    // queued probe so a cache evicting another line can make progress without a B/C deadlock.
    val isRelease = TLOpcode.isRelease(clientC.bits.opcode)
    probeEngine.io.ack.valid := clientC.valid && !isRelease && !releaseAny
    probeEngine.io.ack.bits := clientC.bits
    for (i <- 0 until nClients) {
        io.clients(i).c.ready := cSelect === i.U &&
            Mux(isRelease, releaseAllowed || in(releaseReceive), probeEngine.io.ack.ready)
    }
    when(clientC.fire && isRelease && !in(releaseReceive)) {
        checkLookup(clientC.bits.address, maintenance = true)
        assert(releaseAllowed && clientC.bits.size === 6.U &&
            clientC.bits.address(5, 0) === 0.U && inRam(clientC.bits.address) &&
            lineOwned(clientC.bits.address, maintenance = true) &&
            lineOwner(clientC.bits.address, maintenance = true) === cSelect &&
            clientC.bits.param === TLPermissions.tToN,
            "invalid voluntary line release")
        releaseClient := cSelect
        releaseSource := clientC.bits.source
        releaseParam := clientC.bits.param
        releaseSlot.foreach(_ := selectedReleaseIndex.get)
        if (parallelQualification) {
            assert(cSelect === releaseSelect &&
                selectedReleaseIndex.get === lineIndex(clientC.bits.address, maintenance = true),
                "raw C directory lookup did not belong to the retained release")
        }
        lineAddress := clientC.bits.address
        lineData(0) := clientC.bits.data
        beat := 1.U
        resume := stateStorage
        when(clientC.bits.opcode === TLOpcode.ReleaseData) {
            state := releaseReceive
        }.otherwise {
            if (!parallelQualification) owned(lineIndex(clientC.bits.address, maintenance = true)) := false.B
            state := releaseAck
        }
    }
    when(clientC.fire && in(releaseReceive)) {
        assert(clientC.bits.opcode === TLOpcode.ReleaseData &&
            clientC.bits.address === lineAddress &&
            clientC.bits.source === releaseSource &&
            clientC.bits.param === releaseParam &&
            clientC.bits.size === 6.U && !clientC.bits.corrupt,
            "ReleaseData burst changed control or was corrupt")
        lineData(beat) := clientC.bits.data
        when(beat === 7.U) {
            beat := 0.U
            releaseOrigin := true.B
            state := lineWriteSend
        }.otherwise { beat := beat + 1.U }
    }
    lineTransfer.io.writeRequest.valid := in(lineWriteSend)
    lineTransfer.io.writeRequest.bits.address := lineAddress
    lineTransfer.io.writeRequest.bits.data := lineData.asUInt
    lineTransfer.io.writeRequest.bits.tag := 0.U
    when(lineTransfer.io.writeRequest.fire) { state := lineWriteWait }
    lineTransfer.io.writeResponse.ready := in(lineWriteWait) || releaseWritePending.getOrElse(false.B)
    when(lineTransfer.io.writeResponse.fire) {
        // A detached voluntary write uses its already resolved releaseSlot,
        // not the maintenance RAM port now serving the independent Acquire.
        if (writebackOverlap) {
            when(!releaseOrigin) { checkLookup(lineAddress, maintenance = true) }
        } else checkLookup(lineAddress, maintenance = true)
        assert(!lineTransfer.io.writeResponse.bits.error,
            "coherent home backing RAM rejected a dirty line writeback")
        when(releaseOrigin) {
            if (!parallelQualification) owned(lineIndex(lineAddress, maintenance = true)) := false.B
            if (writebackOverlap) {
                releaseWritePending.get := false.B
                releaseAckPending.get := true.B
            } else state := releaseAck
        }.elsewhen(probeForAcquire) {
            // ProbeAckData already supplied the full line. Backing RAM is now current;
            // forwarding the buffered data avoids a redundant eight-beat refill.
            beat := 0.U
            state := grant
        }.otherwise { state := accessSend }
    }
    if (writebackOverlap) {
        when(lineTransfer.io.writeRequest.fire && releaseOrigin) { releaseWritePending.get := true.B }
        when(releaseAckPending.get && client(releaseClient).d.fire) {
            releaseAckPending.get := false.B
            when(in(lineWriteWait) && !acquireFire) { state := resume }
        }
        when(in(releaseAck) && client(releaseClient).d.fire) { state := resume }
        when(detachedRelease) {
            assert(releaseOrigin, "detached writeback lost its original voluntary release")
        }
    } else when(in(releaseAck) && client(releaseClient).d.fire) { state := resume }
    if (parallelQualification) {
        // Clear the captured release row during the EXISTING Ack phase.
        // No A/ordinary request can enter before it completes; a preempted
        // probe resumes only afterwards. Dirty release still waits for its
        // real backing write reply, and no new directory tag is installed early.
        clearReleasedOwner := releaseDPhase
        assert(PopCount(Seq(installOwner, clearProbedOwner, clearReleasedOwner)) <= 1.U ||
            (writebackOverlap.B && installOwner && clearReleasedOwner &&
                acquireSlot.get =/= releaseSlot.get),
            "Home directory metadata has multiple maintenance owners")
        for (row <- 0 until ownerEntries) {
            val install = (primaryInstall && acquireSlot.get === row.U) ||
                (secondInstall && releaseSlot.get === row.U)
            val clear = (clearProbedOwner && probeSlot.get === row.U) ||
                (clearReleasedOwner && releaseSlot.get === row.U)
            when(install || clear) { owned(row) := install && !clear }
        }
    }
    // Explicit local phase bits remove binary state decode/encoding from
    // already late directory decisions. Resume retains the same one owner.
    private def homeStates: Seq[UInt] = if (parallelQualification)
        (0 until 13).map(i => (BigInt(1) << i).U(13.W)) else Enum(13)
    private def phaseIs(value: UInt, phase: UInt): Bool = if (parallelQualification)
        value(phase.litValue.bitLength - 1) else value === phase
    private def in(phase: UInt): Bool = phaseIs(stateStorage, phase)
    stateStorage := state
    if (parallelQualification) {
        // Each phase has ONLY its own hold/exit controls. In particular a
        // late owned/tag result may select probe vs fill, but cannot flow
        // through every unrelated writeback/release priority mux afterwards.
        // 'state' above retains the original priority equations as an oracle;
        // no additional register or transition edge is introduced.
        val ordinaryStart = in(idle) && io.upstream.request.fire && stagedAccess
        val releaseStart = clientC.fire && isRelease && !in(releaseReceive)
        val probeReturned = probeEngine.io.response.fire
        val probeData = probeReturned && probeEngine.io.response.bits.hasData
        val probeClean = probeReturned && !probeEngine.io.response.bits.hasData
        val primaryReturned = lineTransfer.io.readResponse.fire &&
            (!readOverlap.B || lineTransfer.io.readResponse.bits.tag === 0.U)
        val grantDone = if (internalLineGrant)
            io.lineGrants.get(acquireClient).fire && in(grant)
            else client(dClient).d.fire && in(grant) && !releaseDPhase && beat === 7.U
        val installed = in(grantAck) && client(acquireClient).e.fire
        val receiveDone = in(releaseReceive) && clientC.fire && beat === 7.U
        val writerSent = in(lineWriteSend) && lineTransfer.io.writeRequest.ready
        val writerReturned = lineTransfer.io.writeResponse.fire
        val probeWritten = writerReturned && !releaseOrigin
        val releasedWritten = writerReturned && releaseOrigin && !writebackOverlap.B
        val pendingAckDone = releaseAckPending.getOrElse(false.B) && client(releaseClient).d.fire
        val resumeDone = (in(releaseAck) && client(releaseClient).d.fire) ||
            (writebackOverlap.B && in(lineWriteWait) && !acquireFire && pendingAckDone)
        val returnTo = (phase: UInt) => resumeDone && phaseIs(resume, phase)
        val waitForRelease = installed && detachedRelease && !pendingAckDone
        val next = Seq(
            (in(idle) && !ordinaryStart && !acquireFire && !releaseStart) ||
                (in(accessWait) && io.upstream.response.fire) ||
                (installed && !waitForRelease) || returnTo(idle),
            (in(probeSend) && !probeEngine.io.request.fire && !releaseStart) ||
                (ordinaryStart && needsProbe) || acquiredOwned || returnTo(probeSend),
            (in(probeWait) && !probeReturned && !releaseStart) ||
                probeEngine.io.request.fire || returnTo(probeWait),
            (in(accessSend) && !io.downstream.request.ready) ||
                (ordinaryStart && !needsProbe) || (probeClean && !probeForAcquire) ||
                (probeWritten && !probeForAcquire),
            (in(accessWait) && !io.upstream.response.fire) ||
                (in(accessSend) && io.downstream.request.ready),
            (in(fillSend) && !lineTransfer.io.readRequest.ready) ||
                (immediateFill && !lineTransfer.io.readRequest.ready) ||
                (probeClean && probeForAcquire),
            (in(fillWait) && !primaryReturned) ||
                ((in(fillSend) || immediateFill) && lineTransfer.io.readRequest.ready),
            (in(grant) && !grantDone) || primaryReturned || (probeWritten && probeForAcquire),
            (in(grantAck) && !installed) || grantDone,
            (in(releaseReceive) && !receiveDone) ||
                (releaseStart && clientC.bits.opcode === TLOpcode.ReleaseData),
            (in(lineWriteSend) && !lineTransfer.io.writeRequest.ready) || receiveDone || probeData,
            (in(lineWriteWait) && !acquireFire && !probeWritten && !releasedWritten && !resumeDone) ||
                writerSent || waitForRelease,
            (in(releaseAck) && !resumeDone) || releasedWritten ||
                (releaseStart && clientC.bits.opcode =/= TLOpcode.ReleaseData))
        val parallelNext = VecInit(next).asUInt
        stateStorage := parallelNext
        when(!reset.asBool) {
            assert(parallelNext === state, "local Home phase equations changed transition priority")
            assert(acquiredOwned === (acquireFire && selectedAcquireOwned) &&
                immediateFill === (acquireFire && !selectedAcquireOwned),
                "bank-local Home admission lost the selected real A handshake")
        }
    }
    if (parallelQualification) when(!reset.asBool) {
        assert(PopCount(stateStorage) === 1.U, "Home phase lost its single transaction owner")
    }
}
