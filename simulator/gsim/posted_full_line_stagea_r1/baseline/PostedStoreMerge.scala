package soc.core.ooo

import chisel3._
import chisel3.util._

/** Standalone new reconstruction, not yet connected to CPU/cache.
  * A cache must atomically reserve its existing response and physical resources
  * with enq.fire. Every event input denotes an actual captured handshake.
  * Throughput targets: one ingress/ACK/drain/install per cycle; two line owners,
  * sixteen tokens. No new MSHRs, acquire sources, WB slots or SRAM ports.
  */
class PostedStoreMerge(c: PostedStoreMergeConfig) extends Module {
    val io = IO(new Bundle {
        val enq = Flipped(Irrevocable(new PostedStoreOffer(c)))
        val cacheAdmission = Input(new PostedStoreAdmission(c))
        val contextEpoch = Input(UInt(c.epochBits.W))
        // An ordered marker or recovery seals; it never cancels accepted work.
        val seal = Input(Bool())
        // Integration asserts only after its registered aggregate responsibility
        // (accepted SB/FIFO, owner, WB and ordering-required coherence) drains.
        val endEpisode = Input(Bool())
        val episodeActive = Output(Bool())
        val eligible = Output(Bool())
        val canJoin = Output(Bool())
        val admission = Output(new PostedLineContext(c))
        val accepted = Output(Valid(new PostedStoreAcceptance(c)))
        val acknowledged = Input(Valid(new PostedStoreMember(c)))
        val acquireIssued = Input(Valid(new PostedLineEvent(c)))
        val refill = Flipped(Decoupled(new PostedLineRefill(c)))
        val install = Irrevocable(new PostedLineInstall(c))
        val drained = Irrevocable(new PostedStoreMember(c))
        val released = Irrevocable(new PostedLineEvent(c))
        val writebackAttached = Input(Valid(new PostedWritebackEvent(c)))
        val writebackSent = Input(Valid(new PostedWritebackEvent(c)))
        val writebackCompleted = Input(Valid(new PostedWritebackEvent(c)))
        val victimCancelled = Input(Valid(new PostedLineEvent(c)))
        val fallback = Irrevocable(new PostedStoreOffer(c))
        val fallbackAcknowledged = Input(Valid(new PostedFallbackAcknowledgement(c)))
        val busy = Output(Bool())
        val exhausted = Output(Bool())
        val failed = Output(Bool())
        val stores = Output(UInt(c.countBits.W))
        val lines = Output(UInt(log2Ceil(c.lineEntries + 1).W))
    })

    io.enq.ready := false.B
    io.eligible := false.B
    io.canJoin := false.B
    io.admission := 0.U.asTypeOf(io.admission)
    io.accepted := 0.U.asTypeOf(io.accepted)
    io.refill.ready := false.B
    io.install.valid := false.B
    io.install.bits := 0.U.asTypeOf(io.install.bits)
    io.drained.valid := false.B
    io.drained.bits := 0.U.asTypeOf(io.drained.bits)
    io.released.valid := false.B
    io.released.bits := 0.U.asTypeOf(io.released.bits)
    io.fallback.valid := false.B
    io.fallback.bits := io.enq.bits
    io.busy := false.B
    io.exhausted := false.B
    io.failed := false.B
    io.stores := 0.U
    io.lines := 0.U
    io.episodeActive := false.B

    if (c.enabled) {
        val live = RegInit(VecInit(Seq.fill(c.lineEntries)(false.B)))
        val contexts = Reg(Vec(c.lineEntries, new PostedLineContext(c)))
        val reservations = Reg(Vec(c.lineEntries, new PostedCacheReservation(c)))
        val sealedRun = RegInit(VecInit(Seq.fill(c.lineEntries)(false.B)))
        val acquired = RegInit(VecInit(Seq.fill(c.lineEntries)(false.B)))
        val refilled = RegInit(VecInit(Seq.fill(c.lineEntries)(false.B)))
        val installed = RegInit(VecInit(Seq.fill(c.lineEntries)(false.B)))
        val payload = Reg(Vec(c.lineEntries, Vec(64, UInt(8.W))))
        val byteValid = RegInit(VecInit(Seq.fill(c.lineEntries)(0.U(64.W))))
        val lineMembers = RegInit(VecInit(Seq.fill(c.lineEntries)(0.U(c.countBits.W))))
        val victimDone = RegInit(VecInit(Seq.fill(c.lineEntries)(false.B)))
        val wbAttached = RegInit(VecInit(Seq.fill(c.lineEntries)(false.B)))
        val wbSent = RegInit(VecInit(Seq.fill(c.lineEntries)(false.B)))
        val wbTickets = Reg(Vec(c.lineEntries, new PostedWritebackTicket(c)))
        val nextGeneration = RegInit(0.U(c.generationBits.W))
        val exhausted = RegInit(false.B)
        val failed = RegInit(false.B)
        val cohortRoot = Reg(new PostedLineOwner(c))
        val cohortEpoch = Reg(UInt(c.epochBits.W))
        val episodeActive = RegInit(false.B)

        val members = Reg(Vec(c.storeEntries, new PostedStoreMember(c)))
        val tokenLive = RegInit(VecInit(Seq.fill(c.storeEntries)(false.B)))
        val tokenAcked = RegInit(VecInit(Seq.fill(c.storeEntries)(false.B)))
        val head = RegInit(0.U(c.storeBits.W))
        val tail = RegInit(0.U(c.storeBits.W))
        val ackHead = RegInit(0.U(c.storeBits.W))
        val count = RegInit(0.U(c.countBits.W))
        val unacked = RegInit(0.U(c.countBits.W))
        val fallbackPending = RegInit(false.B)
        val fallbackOwner = Reg(new PostedFallbackAcknowledgement(c))
        val fallbackEpoch = Reg(UInt(c.epochBits.W))
        val installHeld = RegNext(io.install.valid && !io.install.ready, false.B)
        val drainHeld = RegNext(io.drained.valid && !io.drained.ready, false.B)
        val releaseHeld = RegNext(io.released.valid && !io.released.ready, false.B)
        val refillBad = io.refill.bits.error || !io.refill.bits.toT ||
            !io.refill.bits.hasData || !io.refill.bits.grantAcked
        val errorPending = io.refill.valid && refillBad

        def equalOwner(a: PostedLineOwner, b: PostedLineOwner): Bool = a.asUInt === b.asUInt
        def matches(e: PostedLineEvent): Bool = {
            val s = e.context.owner.slot
            live(s) && e.context.asUInt === contexts(s).asUInt && e.reservation.asUInt === reservations(s).asUInt
        }
        val anyLive = live.asUInt.orR
        val firstOlder = live(0) && (!live(1) || contexts(0).owner.generation < contexts(1).owner.generation)
        val oldest = Mux(firstOlder, 0.U, 1.U)
        val newest = Mux(live(1) && (!live(0) || contexts(1).owner.generation > contexts(0).owner.generation), 1.U, 0.U)
        val freeSlot = PriorityEncoder(VecInit(live.map(!_)))
        val freeLine = !live.asUInt.andR
        val offer = io.enq.bits
        val request = offer.request
        val proof = offer.proof
        val naturalMask = MuxLookup(request.size, 255.U(8.W))(Seq(0.U -> 1.U, 1.U -> 3.U, 2.U -> 15.U))
        val aligned = (request.address(2, 0) & ((1.U << request.size) - 1.U)) === 0.U
        val withinRam = request.address >= c.guaranteedBase.U(65.W) &&
            (request.address +& (1.U(64.W) << request.size)) <= (c.guaranteedBase + c.guaranteedBytes).U(65.W)
        val proven = proof.headAuthorized && proof.physicalPmpAllowed && proof.originalPhysical &&
            proof.integerOrigin && proof.legacyPostedAccepted && proof.finalChecked
        val original = proof.address === request.address && proof.data === request.data &&
            proof.mask === request.mask && proof.size === request.size
        val eligible = proven && original && proof.epoch === io.contextEpoch &&
            request.write && !request.atomic && !request.virtualized && !request.uncached &&
            !request.precheckedLoad && request.translationEpoch === 0.U && aligned && withinRam &&
            request.mask === (naturalMask << request.address(2, 0))(7, 0)
        val address = Cat(request.address(63, 6), 0.U(6.W))
        val duplicateToken = VecInit((0 until c.storeEntries).map(i =>
            tokenLive(i) && members(i).token.asUInt === proof.token.asUInt)).asUInt.orR
        val sameLine = VecInit((0 until c.lineEntries).map(i => live(i) && contexts(i).lineAddress === address)).asUInt.orR
        // A real pending refill seals before admission, avoiding same-edge overlay ambiguity.
        val newestRefilling = io.refill.valid && equalOwner(io.refill.bits.context.owner, contexts(newest).owner)
        val join = anyLive && contexts(newest).lineAddress === address &&
            contexts(newest).epoch === proof.epoch && !sealedRun(newest) && !refilled(newest) &&
            !installed(newest) && !newestRefilling && !io.seal
        val candidate = Mux(join, newest, freeSlot)
        val newOwner = Wire(new PostedLineOwner(c))
        newOwner.slot := freeSlot
        newOwner.generation := nextGeneration
        val newContext = Wire(new PostedLineContext(c))
        newContext.owner := newOwner
        newContext.cohortRoot := Mux(episodeActive, cohortRoot, newOwner)
        newContext.epoch := proof.epoch
        newContext.lineAddress := address
        io.admission := Mux(join, contexts(newest), newContext)
        val reservation = io.cacheAdmission.reservation
        val reservationShape = reservation.mshr < c.readMshrs.U && reservation.way < c.cacheWays.U &&
            reservation.set === request.address(5 + c.setBits, 6) &&
            (!reservation.victimDirty || reservation.victimValid) &&
            (!reservation.victimValid || (reservation.victimAddress(5, 0) === 0.U &&
                reservation.victimAddress(5 + c.setBits, 6) === reservation.set &&
                reservation.victimAddress =/= address))
        val reservationConflict = VecInit((0 until c.lineEntries).map(i => live(i) &&
            (reservations(i).mshr === reservation.mshr || reservations(i).set === reservation.set))).asUInt.orR
        val allocateReady = !exhausted && freeLine && !sameLine && io.cacheAdmission.targetAbsent &&
            io.cacheAdmission.reservationValid &&
            reservationShape && !reservationConflict
        val mergeReady = eligible && !failed && !errorPending && !fallbackPending && !duplicateToken &&
            io.cacheAdmission.responseAvailable && count < c.storeEntries.U && (join || allocateReady)
        io.eligible := eligible && !failed
        io.canJoin := eligible && join && !failed
        val fallbackPossible = eligible && exhausted && !anyLive && !failed && !fallbackPending
        io.fallback.valid := io.enq.valid && fallbackPossible
        io.enq.ready := mergeReady || (fallbackPossible && io.fallback.ready)
        val accepted = io.enq.fire && !io.fallback.fire
        val allocate = accepted && !join
        io.accepted.valid := accepted
        io.accepted.bits.member.token := proof.token
        io.accepted.bits.member.context := io.admission
        io.accepted.bits.member.responseTicket := io.cacheAdmission.responseTicket
        io.accepted.bits.newLine := !join
        io.accepted.bits.reservation := Mux(join, reservations(newest), reservation)

        when(io.enq.valid) { assert(!duplicateToken, "posted offer reused a still-live full ROB token") }
        when(io.fallback.fire) {
            assert(count === 0.U && unacked === 0.U && !anyLive, "fallback must follow complete posted drain")
            assert(io.cacheAdmission.responseAvailable, "legacy fallback must reserve its original response credit")
            fallbackPending := true.B
            fallbackOwner.token := proof.token
            fallbackOwner.responseTicket := io.cacheAdmission.responseTicket
            fallbackEpoch := proof.epoch
        }
        when(io.fallbackAcknowledged.valid) {
            assert(fallbackPending && io.fallbackAcknowledged.bits.asUInt === fallbackOwner.asUInt,
                "legacy fallback ACK lost its full token or original response credit")
            fallbackPending := false.B
        }
        when(allocate) {
            assert(!exhausted && !live(candidate), "posted allocation reused a live or exhausted generation")
            contexts(candidate) := newContext
            reservations(candidate) := reservation
            live(candidate) := true.B
            acquired(candidate) := false.B
            refilled(candidate) := false.B
            installed(candidate) := false.B
            sealedRun(candidate) := false.B
            victimDone(candidate) := !reservation.victimValid
            wbAttached(candidate) := false.B
            wbSent(candidate) := false.B
            when(!episodeActive) {
                cohortRoot := newOwner
                cohortEpoch := proof.epoch
                episodeActive := true.B
            }
            when(nextGeneration.andR) { exhausted := true.B }
                .otherwise { nextGeneration := nextGeneration + 1.U }
        }
        for (i <- 0 until c.lineEntries) {
            when(live(i) && (io.seal || allocate)) { sealedRun(i) := true.B }
            val push = accepted && candidate === i.U
            val pop = io.drained.fire && io.drained.bits.context.owner.slot === i.U
            when(push || pop) { lineMembers(i) := lineMembers(i) + push.asUInt - pop.asUInt }
            when(push) {
                val beat = request.address(5, 3)
                val shiftedMask = (request.mask << (beat << 3))(63, 0)
                byteValid(i) := Mux(allocate, shiftedMask, byteValid(i) | shiftedMask)
                for (b <- 0 until 64) {
                    when(beat === (b / 8).U && request.mask(b % 8)) {
                        payload(i)(b) := request.data(8 * (b % 8) + 7, 8 * (b % 8))
                    }
                }
            }
            when(live(i)) { assert(contexts(i).epoch === io.contextEpoch, "context changed with accepted posted responsibility") }
        }
        when(accepted) {
            assert(!tokenLive(tail), "posted ledger overwrote a live store")
            for (i <- 0 until c.storeEntries) {
                assert(!tokenLive(i) || tokenAcked(i) || members(i).responseTicket =/= io.cacheAdmission.responseTicket,
                    "new posted store reused a response ticket before its real ACK")
            }
            members(tail) := io.accepted.bits.member
            tokenLive(tail) := true.B
            tokenAcked(tail) := false.B
            tail := tail + 1.U
        }
        when(io.acknowledged.valid) {
            assert(unacked =/= 0.U && tokenLive(ackHead) && !tokenAcked(ackHead) &&
                io.acknowledged.bits.asUInt === members(ackHead).asUInt,
                "posted ACK must be the one real ordered upstream response handshake")
            tokenAcked(ackHead) := true.B
            ackHead := ackHead + 1.U
        }
        when(accepted =/= io.acknowledged.valid) {
            unacked := Mux(accepted, unacked + 1.U, unacked - 1.U)
        }

        when(io.acquireIssued.valid) {
            val s = io.acquireIssued.bits.context.owner.slot
            assert(matches(io.acquireIssued.bits) && !acquired(s) && (victimDone(s) || wbSent(s)),
                "actual A.fire lost its reservation or preceded the original victim C-last")
            acquired(s) := true.B
        }
        // Storage was reserved at acceptance. A younger completion must not hold
        // the engine response port while waiting for the older line to return.
        val fillSlot = io.refill.bits.context.owner.slot
        // A contract error cannot withdraw an already offered successful event.
        // Stop new success offers, finish any held ones, then capture the error.
        io.refill.ready := !failed && matches(io.refill.bits) && acquired(fillSlot) && !refilled(fillSlot) &&
            (!refillBad || !(installHeld || drainHeld || releaseHeld))
        when(io.refill.valid) {
            assert(matches(io.refill.bits) && acquired(fillSlot) && !refilled(fillSlot),
                "refill kind/full generation must select its original live posted owner")
        }
        when(io.refill.fire) {
            assert(io.refill.bits.grantAcked, "engine completion must follow actual Grant E")
            sealedRun(fillSlot) := true.B
            when(refillBad) {
                failed := true.B
                for (i <- 0 until c.lineEntries) { when(live(i)) { sealedRun(i) := true.B } }
            }.otherwise {
                refilled(fillSlot) := true.B
                for (b <- 0 until 64) {
                    when(!byteValid(fillSlot)(b)) { payload(fillSlot)(b) := io.refill.bits.data(8 * b + 7, 8 * b) }
                }
            }
        }
        val uninstalled = VecInit((0 until c.lineEntries).map(i => live(i) && !installed(i)))
        val firstUninstalled = uninstalled(0) && (!uninstalled(1) || firstOlder)
        val installSlot = Mux(firstUninstalled, 0.U, 1.U)
        io.install.valid := uninstalled.asUInt.orR && refilled(installSlot) && !failed && (!errorPending || installHeld)
        io.install.bits.context := contexts(installSlot)
        io.install.bits.reservation := reservations(installSlot)
        io.install.bits.data := payload(installSlot).asUInt
        when(io.install.fire) {
            assert(live(installSlot) && refilled(installSlot) && !installed(installSlot), "duplicate posted SRAM installation")
            installed(installSlot) := true.B
        }
        io.drained.valid := count =/= 0.U && tokenLive(head) && tokenAcked(head) &&
            installed(members(head).context.owner.slot) && !failed && (!errorPending || drainHeld)
        io.drained.bits := members(head)
        when(io.drained.fire) {
            val s = members(head).context.owner.slot
            assert(live(s) && members(head).context.asUInt === contexts(s).asUInt,
                "token drain must retain its installed full generation")
            tokenLive(head) := false.B
            tokenAcked(head) := false.B
            head := head + 1.U
        }
        when(accepted =/= io.drained.fire) { count := Mux(accepted, count + 1.U, count - 1.U) }

        when(io.writebackAttached.valid) {
            val event = io.writebackAttached.bits
            val s = event.context.owner.slot
            assert(matches(event) && reservations(s).victimValid && !victimDone(s) && !wbAttached(s) &&
                event.ticket.slot < c.writebackEntries.U && equalOwner(event.ticket.owner, contexts(s).owner),
                "real eviction capture must attach the exact victim and full WB ticket once")
            for (i <- 0 until c.lineEntries) {
                assert(!live(i) || !wbAttached(i) || victimDone(i) || wbTickets(i).slot =/= event.ticket.slot,
                    "physical WB slot is still owned, including a same-edge ReleaseAck")
            }
            assert(!io.victimCancelled.valid || !equalOwner(io.victimCancelled.bits.context.owner, event.context.owner),
                "victim cannot be captured and cancelled on the same edge")
            wbAttached(s) := true.B
            wbTickets(s) := event.ticket
        }
        when(io.writebackSent.valid) {
            val event = io.writebackSent.bits
            val s = event.context.owner.slot
            assert(matches(event) && wbAttached(s) && !wbSent(s) && !victimDone(s) &&
                event.ticket.asUInt === wbTickets(s).asUInt, "actual C-last changed its captured full WB ticket")
            wbSent(s) := true.B
        }
        when(io.writebackCompleted.valid) {
            val event = io.writebackCompleted.bits
            val s = event.context.owner.slot
            assert(matches(event) && wbAttached(s) && wbSent(s) && !victimDone(s) &&
                event.ticket.asUInt === wbTickets(s).asUInt, "ReleaseAck detached from captured WB generation")
            victimDone(s) := true.B
        }
        when(io.victimCancelled.valid) {
            val event = io.victimCancelled.bits
            val s = event.context.owner.slot
            assert(matches(event) && reservations(s).victimValid && !victimDone(s) && !wbAttached(s),
                "only a genuinely removed, uncaptured original victim may cancel its release")
            victimDone(s) := true.B
        }
        io.released.valid := anyLive && installed(oldest) && lineMembers(oldest) === 0.U &&
            victimDone(oldest) && !failed && (!errorPending || releaseHeld)
        io.released.bits.context := contexts(oldest)
        io.released.bits.reservation := reservations(oldest)
        when(io.released.fire) { live(oldest) := false.B }

        io.busy := anyLive || count =/= 0.U || fallbackPending || failed
        io.exhausted := exhausted
        io.failed := failed
        io.stores := count
        io.lines := PopCount(live)
        io.episodeActive := episodeActive
        when(io.endEpisode) {
            assert(!io.busy && !io.enq.valid && !io.fallback.valid,
                "cohort may end only at an empty registered aggregate boundary, never a held ingress")
            episodeActive := false.B
        }
        when(io.enq.valid && episodeActive) {
            assert(proof.epoch === cohortEpoch, "continuing posted episode cannot acquire a new authorization epoch")
        }
        when(fallbackPending) { assert(io.contextEpoch === fallbackEpoch, "context changed with an accepted legacy fallback") }
        assert(unacked <= count && count <= c.storeEntries.U)
        assert(PopCount(tokenLive) === count, "posted ledger count and full-token ownership disagree")
        when(live(0) && live(1)) {
            assert(contexts(0).lineAddress =/= contexts(1).lineAddress &&
                contexts(0).owner.generation =/= contexts(1).owner.generation &&
                contexts(0).cohortRoot.asUInt === contexts(1).cohortRoot.asUInt,
                "posted line/cohort identity collision")
        }

        def stable[T <: Data](valid: Bool, ready: Bool, bits: T, message: String): Unit = {
            val held = RegNext(valid && !ready, false.B)
            val prior = RegEnable(bits.asUInt, valid && !ready)
            when(held) { assert(valid && bits.asUInt === prior, message) }
        }
        stable(io.enq.valid, io.enq.ready, io.enq.bits, "held posted ingress changed")
        stable(io.install.valid, io.install.ready, io.install.bits, "held posted install changed")
        stable(io.drained.valid, io.drained.ready, io.drained.bits, "held posted token drain changed")
        stable(io.released.valid, io.released.ready, io.released.bits, "held posted resource release changed")
        stable(io.fallback.valid, io.fallback.ready, io.fallback.bits, "held original fallback changed")
        stable(io.refill.valid, io.refill.ready, io.refill.bits, "held posted engine refill changed")
        val heldIngress = RegNext(io.enq.valid && !io.enq.ready, false.B)
        val heldEpoch = RegEnable(io.contextEpoch, io.enq.valid && !io.enq.ready)
        when(heldIngress) {
            assert(io.contextEpoch === heldEpoch && io.enq.bits.proof.epoch === heldEpoch,
                "context changed while an original posted proof was held before admission")
        }
    }
}
