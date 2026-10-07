package soc.core.ooo

import chisel3._
import chisel3.util._

/** Translates a fetch packet before the physical instruction port. Four-word packets are 16-byte aligned and fit
  * in one translation page; the two-word path retains precise handling of a packet crossing a page boundary.
  */
class InstructionTranslationAdapter(p: OooParams) extends Module {
    require(p.virtualMemoryLevels > 0 && p.pmpEntries > 0)
    private val packetWords = if (p.compressedInstructions && p.renameWidth == 4) 4 else 2
    val io = IO(new Bundle {
        val virtual = Flipped(new InstructionPort(packetWords))
        val physical = new InstructionPort(packetWords)
        val translation = new SvTranslationPort
        val vmState = Input(new VmCsrState)
        val privilege = Input(UInt(2.W))
        val pmpState = Input(new PmpState)
        val idle = Output(Bool())
    })
    if (p.registeredTranslationHeads) {
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
        val secondVirtualPc = Reg(UInt(64.W))
        val requested = Reg(UInt(packetWords.W))
        val satp = Reg(UInt(64.W))
        val sum = Reg(Bool())
        val mxr = Reg(Bool())
        val privilege = Reg(UInt(2.W))
        val firstPhysical = Reg(UInt(64.W))
        val secondPhysical = Reg(UInt(64.W))
        val secondPageFault = RegInit(false.B)
        val secondAccessFault = RegInit(false.B)
        val permissionCaptured = RegInit(false.B)
        val allowed = Reg(UInt(packetWords.W))
        val errors = Reg(UInt(packetWords.W))
        val pageFaults = Reg(UInt(packetWords.W))
        val data = Reg(UInt((32 * packetWords).W))
        val crosses = if (packetWords == 2) virtualPc(11, 0) === 4092.U && requested(1) else false.B
        val alignedPacket = p.alignedFetchPmp && p.compressedInstructions

        io.virtual.request.ready := state === idle
        when(io.virtual.request.fire) {
            if (packetWords == 4 || alignedPacket) {
                assert(io.virtual.request.bits(log2Ceil(4 * packetWords) - 1, 0) === 0.U,
                    "aligned instruction packet must preserve its packet offset through translation")
            }
            virtualPc := io.virtual.request.bits
            // The generic cross-page path still needs modulo64 +4, but this
            // carry completes at request capture, before the TLB lookup.
            secondVirtualPc := io.virtual.request.bits + 4.U
            requested := io.virtual.requestMask
            satp := io.vmState.satp
            sum := io.vmState.sum
            mxr := io.vmState.mxr
            privilege := io.privilege
            secondPageFault := false.B
            secondAccessFault := false.B
            permissionCaptured := false.B
            allowed := 0.U
            errors := (if (packetWords == 4) ~io.virtual.requestMask else 0.U)
            pageFaults := 0.U
            data := 0.U
            state := translateFirst
        }

        val translating = state === translateFirst || state === translateSecond
        val second = state === translateSecond
        io.translation.request.valid := translating && !issued
        io.translation.request.bits.virtualAddress := Mux(second, secondVirtualPc, virtualPc)
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
                secondPhysical := response.physicalAddress
                secondPageFault := response.pageFault
                secondAccessFault := response.accessFault
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
        for (word <- 0 until packetWords) {
            val samePageAddress = if (alignedPacket)
                Cat(firstPhysical(63, log2Ceil(4 * packetWords)), word.U(log2Ceil(packetWords).W), 0.U(2.W))
            else firstPhysical + (4 * word).U
            val wordAddress = if (packetWords == 2 && word == 1)
                Mux(crosses, secondPhysical, samePageAddress) else samePageAddress
            val checker = Module(new PmpChecker(p.pmpEntries, alignedWordAccess = alignedPacket))
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
            val secondFault = crosses && (secondPageFault || secondAccessFault)
            val secondAllowed = requested(1) && !secondFault && !denied(1)
            checkedAllowed := Cat(secondAllowed, firstAllowed)
            checkedErrors := Cat(requested(1) && !(crosses && secondPageFault) &&
                ((crosses && secondAccessFault) || denied(1)), requested(0) && denied(0))
            checkedPages := Cat(crosses && secondPageFault, false.B)
        } else {
            checkedAllowed := requested & ~denied.asUInt
            checkedErrors := ~checkedAllowed
            checkedPages := 0.U
        }
        val activeAllowed = Mux(permissionCaptured, allowed, checkedAllowed)
        val secondOnly = crosses && !activeAllowed(0)
        val sendingSecond = state === sendSecond || (state === sendFirst && secondOnly)
        val firstMask = if (packetWords == 2) Mux(crosses, Cat(false.B, activeAllowed(0)), activeAllowed)
            else activeAllowed
        val offerMask = Mux(sendingSecond, 1.U(packetWords.W), firstMask)
        io.physical.request.valid := (state === sendFirst || state === sendSecond) && activeAllowed.orR
        io.physical.request.bits := Mux(sendingSecond, secondPhysical, firstPhysical)
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
        io.physical.response.ready := state === waitFirst || state === waitSecond
        when(io.physical.response.fire) {
            when(state === waitSecond) {
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
        io.virtual.response.valid := state === reply
        io.virtual.response.bits := data
        io.virtual.responseError := errors
        io.virtual.responsePageFault := pageFaults
        when(io.virtual.response.fire) { state := idle }
        io.idle := state === idle
    } else if (packetWords == 4) {
        val Seq(idle, translate, send, waitData, reply) = Enum(5)
        val state = RegInit(idle)
        val issued = RegInit(false.B)
        val virtualPc = Reg(UInt(64.W))
        val requested = Reg(UInt(4.W))
        val satp = Reg(UInt(64.W))
        val sum = Reg(Bool())
        val mxr = Reg(Bool())
        val privilege = Reg(UInt(2.W))
        val physicalPc = Reg(UInt(64.W))
        val physicalMask = Reg(UInt(4.W))
        val errors = Reg(UInt(4.W))
        val pageFaults = Reg(UInt(4.W))
        val data = Reg(UInt(128.W))

        io.virtual.request.ready := state === idle
        when(io.virtual.request.fire) {
            assert(io.virtual.request.bits(3, 0) === 0.U, "wide instruction packet must align to 16 bytes")
            virtualPc := io.virtual.request.bits
            requested := io.virtual.requestMask
            satp := io.vmState.satp
            sum := io.vmState.sum
            mxr := io.vmState.mxr
            privilege := io.privilege
            errors := ~io.virtual.requestMask
            pageFaults := 0.U
            data := 0.U
            state := translate
        }
        io.translation.request.valid := state === translate && !issued
        io.translation.request.bits.virtualAddress := virtualPc
        io.translation.request.bits.rootPpn := satp(43, 0)
        io.translation.request.bits.asid := satp(59, 44)
        io.translation.request.bits.mode := satp(63, 60)
        io.translation.request.bits.privilege := privilege
        io.translation.request.bits.access := PmpAccess.execute
        io.translation.request.bits.sum := sum
        io.translation.request.bits.mxr := mxr
        io.translation.response.ready := state === translate
        when(io.translation.request.fire) { issued := true.B }
        val denied = Wire(Vec(4, Bool()))
        for (word <- 0 until 4) {
            val checker = Module(new PmpChecker(p.pmpEntries))
            checker.io.state := io.pmpState
            checker.io.address := io.translation.response.bits.physicalAddress + (word * 4).U
            checker.io.size := 2.U
            checker.io.privilege := privilege
            checker.io.access := PmpAccess.execute
            denied(word) := checker.io.denied
        }
        when(io.translation.response.fire) {
            issued := false.B
            when(io.translation.response.bits.pageFault) {
                pageFaults := requested
                state := reply
            }.elsewhen(io.translation.response.bits.accessFault) {
                errors := "hf".U
                state := reply
            }.otherwise {
                val allowed = requested & ~denied.asUInt
                physicalPc := io.translation.response.bits.physicalAddress
                physicalMask := allowed
                errors := ~allowed
                state := Mux(allowed.orR, send, reply)
            }
        }
        io.physical.request.valid := state === send
        io.physical.request.bits := physicalPc
        io.physical.requestMask := physicalMask
        when(io.physical.request.fire) { state := waitData }
        io.physical.response.ready := state === waitData
        when(io.physical.response.fire) {
            data := io.physical.response.bits
            errors := errors | io.physical.responseError
            pageFaults := pageFaults | io.physical.responsePageFault
            state := reply
        }
        io.virtual.response.valid := state === reply
        io.virtual.response.bits := data
        io.virtual.responseError := errors
        io.virtual.responsePageFault := pageFaults
        when(io.virtual.response.fire) { state := idle }
        io.idle := state === idle
    } else {
    val states = Enum(8)
    val idle = states(0)
    val translateFirst = states(1)
    val translateSecond = states(2)
    val sendFirst = states(3)
    val waitFirst = states(4)
    val sendSecond = states(5)
    val waitSecond = states(6)
    val reply = states(7)
    val state = RegInit(idle)
    val issued = RegInit(false.B)
    val virtualPc = Reg(UInt(64.W))
    val requested = Reg(UInt(2.W))
    val satp = Reg(UInt(64.W))
    val sum = Reg(Bool())
    val mxr = Reg(Bool())
    val privilege = Reg(UInt(2.W))
    val firstPhysical = Reg(UInt(64.W))
    val secondPhysical = Reg(UInt(64.W))
    val allowed = Reg(UInt(2.W))
    val errors = Reg(UInt(2.W))
    val pageFaults = Reg(UInt(2.W))
    val data = Reg(UInt(64.W))
    val crosses = virtualPc(11, 0) === 4092.U && requested(1)

    io.virtual.request.ready := state === idle
    when(io.virtual.request.fire) {
        virtualPc := io.virtual.request.bits
        requested := io.virtual.requestMask
        satp := io.vmState.satp
        sum := io.vmState.sum
        mxr := io.vmState.mxr
        privilege := io.privilege
        allowed := 0.U
        errors := 0.U
        pageFaults := 0.U
        data := 0.U
        state := translateFirst
    }

    val translating = state === translateFirst || state === translateSecond
    val second = state === translateSecond
    io.translation.request.valid := translating && !issued
    io.translation.request.bits.virtualAddress := virtualPc + Mux(second, 4.U, 0.U)
    io.translation.request.bits.rootPpn := satp(43, 0)
    io.translation.request.bits.asid := satp(59, 44)
    io.translation.request.bits.mode := satp(63, 60)
    io.translation.request.bits.privilege := privilege
    io.translation.request.bits.access := PmpAccess.execute
    io.translation.request.bits.sum := sum
    io.translation.request.bits.mxr := mxr
    io.translation.response.ready := translating
    when(io.translation.request.fire) { issued := true.B }

    val firstPmp = Module(new PmpChecker(p.pmpEntries))
    firstPmp.io.state := io.pmpState
    firstPmp.io.address := io.translation.response.bits.physicalAddress
    firstPmp.io.size := 2.U
    firstPmp.io.privilege := privilege
    firstPmp.io.access := PmpAccess.execute
    val secondPmp = Module(new PmpChecker(p.pmpEntries))
    secondPmp.io.state := io.pmpState
    secondPmp.io.address := io.translation.response.bits.physicalAddress + 4.U
    secondPmp.io.size := 2.U
    secondPmp.io.privilege := privilege
    secondPmp.io.access := PmpAccess.execute
    val response = io.translation.response.bits
    when(io.translation.response.fire) {
        issued := false.B
        when(second) {
            secondPhysical := response.physicalAddress
            when(response.pageFault) { pageFaults := pageFaults | 2.U }
            .elsewhen(response.accessFault || firstPmp.io.denied) { errors := errors | 2.U }
            .otherwise { allowed := allowed | 2.U }
            when(allowed(0)) { state := sendFirst }
            .elsewhen(!response.pageFault && !response.accessFault && !firstPmp.io.denied) {
                state := sendSecond
            }.otherwise { state := reply }
        }.otherwise {
            firstPhysical := response.physicalAddress
            when(response.pageFault) { pageFaults := requested }
            .elsewhen(response.accessFault) { errors := requested }
            .otherwise {
                val firstAllowed = requested(0) && !firstPmp.io.denied
                val secondAllowed = requested(1) && !crosses && !secondPmp.io.denied
                allowed := Cat(secondAllowed, firstAllowed)
                errors := Cat(requested(1) && !crosses && secondPmp.io.denied,
                    requested(0) && firstPmp.io.denied)
            }
            when(crosses && !response.pageFault && !response.accessFault) {
                state := translateSecond
            }.elsewhen(!response.pageFault && !response.accessFault &&
                ((requested(0) && !firstPmp.io.denied) || (requested(1) && !secondPmp.io.denied))) {
                state := sendFirst
            }.otherwise { state := reply }
        }
    }

    io.physical.request.valid := state === sendFirst || state === sendSecond
    io.physical.request.bits := Mux(state === sendSecond, secondPhysical, firstPhysical)
    io.physical.requestMask := Mux(state === sendSecond, 1.U,
        Mux(crosses, Cat(0.U(1.W), allowed(0)), allowed))
    when(io.physical.request.fire) {
        state := Mux(state === sendSecond, waitSecond, waitFirst)
    }
    io.physical.response.ready := state === waitFirst || state === waitSecond
    when(io.physical.response.fire) {
        when(state === waitSecond) {
            data := Cat(io.physical.response.bits(31, 0), data(31, 0))
            errors := errors | (io.physical.responseError(0) << 1)
            pageFaults := pageFaults | (io.physical.responsePageFault(0) << 1)
            state := reply
        }.otherwise {
            data := io.physical.response.bits
            errors := errors | (io.physical.responseError & io.physical.requestMask)
            pageFaults := pageFaults | (io.physical.responsePageFault & io.physical.requestMask)
            state := Mux(crosses && allowed(1), sendSecond, reply)
        }
    }
    io.virtual.response.valid := state === reply
    io.virtual.response.bits := data
    io.virtual.responseError := errors
    io.virtual.responsePageFault := pageFaults
    when(io.virtual.response.fire) { state := idle }
    io.idle := state === idle
    }
}
