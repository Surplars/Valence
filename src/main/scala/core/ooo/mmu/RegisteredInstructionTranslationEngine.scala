package soc.core.ooo

import chisel3._
import chisel3.util._

/** Real compatibility boundary for the registered instruction translation path.
  * Capacity one; no added request or reply edge. A result releases its credit
  * only on the upstream response handshake. Generation identity travels through
  * the engine, rather than being reconstructed from the current request at reply.
  * No stream/PMP epoch is invented here; existing outer cancellation and drain
  * contracts remain authoritative.
  */
class InstructionFetchTransactionBoundary(packetWords: Int = 2, tokenBits: Int = 64) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new InstructionPort(packetWords))
        val vmState = Input(new VmCsrState)
        val privilege = Input(UInt(2.W))
        val command = Decoupled(new FetchTransactionCommand(packetWords, tokenBits))
        val result = Flipped(Decoupled(new FetchTransactionResult(packetWords, tokenBits)))
        val idle = Output(Bool())
    })
    val occupied = RegInit(false.B)
    val activeToken = Reg(UInt(tokenBits.W))
    val nextToken = RegInit(0.U(tokenBits.W))
    val matches = occupied && io.result.bits.token === activeToken
    io.upstream.response.valid := io.result.valid && matches
    io.upstream.response.bits := io.result.bits.data
    io.upstream.responseError := io.result.bits.accessFaults
    io.upstream.responsePageFault := io.result.bits.pageFaults
    io.result.ready := io.upstream.response.ready && matches
    val releasing = io.result.fire
    val credit = !occupied || releasing
    io.command.valid := io.upstream.request.valid && credit
    io.upstream.request.ready := io.command.ready && credit
    io.command.bits.token := nextToken
    io.command.bits.virtualAddress := io.upstream.request.bits
    io.command.bits.requestMask := io.upstream.requestMask
    io.command.bits.satp := io.vmState.satp
    io.command.bits.sum := io.vmState.sum
    io.command.bits.mxr := io.vmState.mxr
    io.command.bits.privilege := io.privilege
    io.idle := !occupied
    when(releasing) { occupied := false.B }
    // New allocation wins the same-edge old-result release. The old result
    // continues to name activeToken before the edge; the command uses nextToken.
    when(io.command.fire) {
        occupied := true.B
        activeToken := io.command.bits.token
        nextToken := nextToken + 1.U
    }
    when(io.result.valid) {
        assert(occupied, "fetch transaction result has no owner")
        assert(io.result.bits.token === activeToken, "fetch transaction result generation mismatch")
    }
    assert(io.command.fire === io.upstream.request.fire,
        "fetch transaction command and public request acceptance must coincide")
}

/** The former registered-heads adapter FSM, at its original register edges.
  * Command acceptance captures VA, mask and complete translation context.
  * PMP is still sampled at the first physical offer, under the existing drain
  * barrier. One engine owner remains; this extraction does not claim II=1.
  */
class RegisteredInstructionTranslationEngine(val p: OooParams,
    val sharedTwoWordFetchPmp: Boolean = false, tokenBits: Int = 64,
    withRequestContext: Boolean = false) extends Module {
    require(p.registeredTranslationHeads && p.virtualMemoryLevels > 0 && p.pmpEntries > 0)
    private val packetWords = if (p.compressedInstructions && p.renameWidth == 4) 4 else 2
    val io = IO(new Bundle {
        val command = Flipped(Decoupled(new FetchTransactionCommand(packetWords, tokenBits)))
        val result = Decoupled(new FetchTransactionResult(packetWords, tokenBits))
        val physical = new InstructionPort(packetWords, withRequestContext)
        val translation = new SvTranslationPort
        val pmpState = Input(new PmpState)
        val idle = Output(Bool())
    })
    val activeToken = Reg(UInt(tokenBits.W))
    when(io.command.fire) { activeToken := io.command.bits.token }
    io.result.bits.token := activeToken
    // Retiming, not another successful-fetch cycle: translation captures PA
    // first, and PMP occupies the already-existing physical send cycle.
    // A zero permitted mask returns its fault one cycle later. The first
    // permission offer is captured even under request backpressure, so a
    // held physical address/mask never re-evaluates live CSR permissions.
    // The existing PMP/SFENCE fetch-drain barrier keeps CSR state stable
    // while !io.idle; this profile samples PMP at first offer, not TLB reply.
    val Seq(idle, translateFirst, translateSecond, sendFirst, waitFirst,
        sendSecond, waitSecond, reply) = Enum(8)
    val state = RegInit(idle)
    val issued = RegInit(false.B)
    val virtualPc = Reg(UInt(64.W))
    val secondVirtualPc = if (p.alignedFetchSinglePage) None else Some(Reg(UInt(64.W)))
    val requested = Reg(UInt(packetWords.W))
    val satp = Reg(UInt(64.W))
    val sum = Reg(Bool())
    val mxr = Reg(Bool())
    val privilege = Reg(UInt(2.W))
    io.physical.requestContext.foreach(_.privilege := privilege)
    val firstPhysical = Reg(UInt(64.W))
    val secondPhysical = if (p.alignedFetchSinglePage) None else Some(Reg(UInt(64.W)))
    val secondPageFault = if (p.alignedFetchSinglePage) None else Some(RegInit(false.B))
    val secondAccessFault = if (p.alignedFetchSinglePage) None else Some(RegInit(false.B))
    val permissionCaptured = RegInit(false.B)
    val allowed = Reg(UInt(packetWords.W))
    val errors = Reg(UInt(packetWords.W))
    val pageFaults = Reg(UInt(packetWords.W))
    val data = Reg(UInt((32 * packetWords).W))
    val crosses = if (packetWords == 2 && !p.alignedFetchSinglePage)
        virtualPc(11, 0) === 4092.U && requested(1) else false.B
    val alignedPacket = p.alignedFetchPmp && p.compressedInstructions

    if (p.alignedFetchSinglePage) {
        // The frontend constructs packet bases by clearing bits 2:0, including
        // the packet at page offset 4088. A 32-bit instruction at offset 4094
        // is assembled upstream from two independently translated packets.
        when(io.command.valid) {
            assert(io.command.bits.virtualAddress(2, 0) === 0.U,
                "single-page fetch offers must be eight-byte aligned")
        }
        when(state =/= idle) {
            assert(virtualPc(2, 0) === 0.U,
                "single-page fetch ownership must retain an aligned request")
            assert(state =/= translateSecond && state =/= sendSecond && state =/= waitSecond,
                "an aligned fetch owner must never enter a second-page phase")
        }
    }

    // Only a committed reply handshake may replace the single owner. The
    // old response remains registered and unchanged until that edge.
    io.command.ready := state === idle ||
        (if (p.fetchReplyTurnover) state === reply && io.result.ready else false.B)
    if (p.fetchIdentityTranslation && p.alignedFetchSinglePage) {
        // READY names an idle owner or the old reply consumed on this edge.
        // Capturing an unoffered address changes only dead payload; actual
        // owner/context/permission state still requires the original FIRE.
        // The translation-response capture below retains final priority.
        when(io.command.ready) { firstPhysical := io.command.bits.virtualAddress }
    }
    when(io.command.fire) {
        if (packetWords == 4 || alignedPacket) {
            assert(io.command.bits.virtualAddress(log2Ceil(4 * packetWords) - 1, 0) === 0.U,
                "aligned instruction packet must preserve its packet offset through translation")
        }
        virtualPc := io.command.bits.virtualAddress
        // The generic cross-page path still needs modulo64 +4, but this
        // carry completes at request capture, before the TLB lookup.
        secondVirtualPc.foreach(_ := io.command.bits.virtualAddress + 4.U)
        requested := io.command.bits.requestMask
        satp := io.command.bits.satp
        sum := io.command.bits.sum
        mxr := io.command.bits.mxr
        privilege := io.command.bits.privilege
        secondPageFault.foreach(_ := false.B)
        secondAccessFault.foreach(_ := false.B)
        permissionCaptured := false.B
        allowed := 0.U
        errors := (if (packetWords == 4) ~io.command.bits.requestMask else 0.U)
        pageFaults := 0.U
        if (!p.fetchReadyDataClear) data := 0.U
        if (p.fetchIdentityTranslation) {
            // Capture the architectural identity case with the request's
            // context. PMP still runs in the existing registered send stage;
            // live CSR changes cannot change the captured address or mode.
            val identity = io.command.bits.privilege === 3.U || io.command.bits.satp(63, 60) === 0.U
            if (!p.alignedFetchSinglePage) firstPhysical := io.command.bits.virtualAddress
            secondPhysical.foreach(_ := io.command.bits.virtualAddress + 4.U)
            state := Mux(identity, Mux(io.command.bits.requestMask.orR, sendFirst, reply), translateFirst)
        } else {
            state := translateFirst
        }
        issued := false.B
    }

    if (p.fetchReadyDataClear) {
        // READY names idle ownership or a reply consumed on this edge. A
        // held reply and all translating/sending/waiting owners retain data.
        // Every accepted new request still initializes the full payload on
        // its original edge, including zero-mask and second-word-only faults.
        // Keep incoming VALID/correction out of the wide synchronous clear.
        when(io.command.ready) { data := 0.U }
    }

    val second = if (p.alignedFetchSinglePage) false.B else state === translateSecond
    val translating = state === translateFirst || second
    io.translation.request.valid := translating && !issued
    io.translation.request.bits.virtualAddress :=
        secondVirtualPc.map(pc => Mux(second, pc, virtualPc)).getOrElse(virtualPc)
    io.translation.request.bits.rootPpn := satp(43, 0)
    io.translation.request.bits.asid := satp(59, 44)
    io.translation.request.bits.mode := satp(63, 60)
    io.translation.request.bits.privilege := privilege
    io.translation.request.bits.access := PmpAccess.execute
    io.translation.request.bits.sum := sum
    io.translation.request.bits.mxr := mxr
    io.translation.response.ready := translating
    when(io.translation.request.fire) { issued := true.B }
    val response = io.translation.response.bits
    when(io.translation.response.fire) {
        issued := false.B
        // Failed translations have no meaningful physical address. Never
        // assert alignment on their payload or on an inactive response.
        if (alignedPacket) {
            when(!response.pageFault && !response.accessFault) {
                assert(response.physicalAddress(log2Ceil(4 * packetWords) - 1, 0) === 0.U,
                    "successful aligned translation must preserve the packet offset")
            }
        }
        when(second) {
            secondPhysical.foreach(_ := response.physicalAddress)
            secondPageFault.foreach(_ := response.pageFault)
            secondAccessFault.foreach(_ := response.accessFault)
            // Even when page two faults, permission for page one's saved
            // PA still decides whether its requested word may be sent.
            state := sendFirst
        }.otherwise {
            firstPhysical := response.physicalAddress
            when(response.pageFault) {
                pageFaults := requested
                state := reply
            }.elsewhen(response.accessFault) {
                errors := (if (packetWords == 4) ((1 << packetWords) - 1).U else requested)
                state := reply
            }.elsewhen(!requested.orR) {
                state := reply
            }.otherwise {
                state := Mux(crosses, translateSecond, sendFirst)
            }
        }
    }

    val denied = Wire(Vec(packetWords, Bool()))
    if (sharedTwoWordFetchPmp && p.pmpEntries == 16 && packetWords == 2 &&
        alignedPacket && p.alignedFetchSinglePage) {
        val checker = Module(new SharedTwoWordFetchPmp)
        checker.io.base := Cat(firstPhysical(63, 3), 0.U(3.W))
        checker.io.state := io.pmpState
        checker.io.privilege := privilege
        denied := checker.io.denied
    } else for (word <- 0 until packetWords) {
        val samePageAddress = if (alignedPacket)
            Cat(firstPhysical(63, log2Ceil(4 * packetWords)), word.U(log2Ceil(packetWords).W), 0.U(2.W))
        else firstPhysical + (4 * word).U
        val wordAddress = if (packetWords == 2 && word == 1 && !p.alignedFetchSinglePage)
            Mux(crosses, secondPhysical.get, samePageAddress) else samePageAddress
        val checker = Module(new PmpChecker(p.pmpEntries, alignedWordAccess = alignedPacket,
            decodedWordGranularity = alignedPacket))
        checker.io.state := io.pmpState
        // Low bits are defined even when these PA registers are inactive;
        // the live translation capture above proves the exact transform.
        checker.io.address := (if (alignedPacket) Cat(wordAddress(63, 2), 0.U(2.W)) else wordAddress)
        checker.io.size := 2.U
        checker.io.privilege := privilege
        checker.io.access := PmpAccess.execute
        denied(word) := checker.io.denied
    }
    val checkedAllowed = Wire(UInt(packetWords.W))
    val checkedErrors = Wire(UInt(packetWords.W))
    val checkedPages = Wire(UInt(packetWords.W))
    if (packetWords == 2) {
        val firstAllowed = requested(0) && !denied(0)
        val secondPage = secondPageFault.getOrElse(false.B)
        val secondAccess = secondAccessFault.getOrElse(false.B)
        val secondFault = crosses && (secondPage || secondAccess)
        val secondAllowed = requested(1) && !secondFault && !denied(1)
        checkedAllowed := Cat(secondAllowed, firstAllowed)
        checkedErrors := Cat(requested(1) && !(crosses && secondPage) &&
            ((crosses && secondAccess) || denied(1)), requested(0) && denied(0))
        checkedPages := Cat(crosses && secondPage, false.B)
    } else {
        checkedAllowed := requested & ~denied.asUInt
        checkedErrors := ~checkedAllowed
        checkedPages := 0.U
    }
    val activeAllowed = Mux(permissionCaptured, allowed, checkedAllowed)
    val secondOnly = crosses && !activeAllowed(0)
    val sendingSecond = if (p.alignedFetchSinglePage) false.B
        else state === sendSecond || (state === sendFirst && secondOnly)
    val firstMask = if (packetWords == 2) Mux(crosses, Cat(false.B, activeAllowed(0)), activeAllowed)
        else activeAllowed
    val offerMask = Mux(sendingSecond, 1.U(packetWords.W), firstMask)
    val sending = if (p.alignedFetchSinglePage) state === sendFirst
        else state === sendFirst || state === sendSecond
    io.physical.request.valid := sending && activeAllowed.orR
    // This existing specialization only emits successful eight-byte packet
    // bases. Expose that invariant as wires, so downstream partial-word mask
    // selection cannot create a fictitious carry into the upper PA bits.
    // Failed translations never authorize a physical request.
    io.physical.request.bits := (if (p.alignedFetchSinglePage)
        Cat(firstPhysical(63, 3), 0.U(3.W))
    else secondPhysical.map(address => Mux(sendingSecond, address, firstPhysical)).getOrElse(firstPhysical))
    io.physical.requestMask := offerMask
    when(state === sendFirst && !permissionCaptured) {
        permissionCaptured := true.B
        allowed := checkedAllowed
        errors := checkedErrors
        pageFaults := checkedPages
        when(!checkedAllowed.orR) { state := reply }
    }
    when(io.physical.request.fire) {
        state := Mux(sendingSecond, waitSecond, waitFirst)
    }
    val waitingSecond = if (p.alignedFetchSinglePage) false.B else state === waitSecond
    io.physical.response.ready := state === waitFirst || waitingSecond
    when(io.physical.response.fire) {
        when(waitingSecond) {
            data := Cat(io.physical.response.bits(31, 0), data(31, 0))
            errors := errors | (io.physical.responseError(0) << 1)
            pageFaults := pageFaults | (io.physical.responsePageFault(0) << 1)
            state := reply
        }.otherwise {
            data := io.physical.response.bits
            errors := errors | (if (packetWords == 4) io.physical.responseError
                else io.physical.responseError & firstMask)
            pageFaults := pageFaults | (if (packetWords == 4) io.physical.responsePageFault
                else io.physical.responsePageFault & firstMask)
            state := Mux(crosses && allowed(1), sendSecond, reply)
        }
    }
    io.result.valid := state === reply
    io.result.bits.data := data
    io.result.bits.accessFaults := errors
    io.result.bits.pageFaults := pageFaults
    // New-owner initialization wins over retiring the prior reply.
    when(io.result.fire && !io.command.fire) { state := idle }
    io.idle := state === idle
}
