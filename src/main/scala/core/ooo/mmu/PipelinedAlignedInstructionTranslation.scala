package soc.core.ooo

import chisel3._
import chisel3.util._

class FetchOwnedCompletion extends Bundle {
    val slot = UInt(1.W)
    val token = UInt(64.W)
    val data = UInt(64.W)
    val accessFaults = UInt(2.W)
    val pageFaults = UInt(2.W)
}

class FetchResultAllocation extends Bundle {
    val token = UInt(64.W)
    val terminal = Bool()
}

/** Result storage is reserved at command acceptance, not at physical completion.
  * One completion write/cycle, two owned slots, ordered terminal delivery.
  * Younger faults may complete first but cannot pass the old head.
  */
class FetchCompletionLedger extends Module {
    val io = IO(new Bundle {
        val allocate = Flipped(Decoupled(new FetchResultAllocation))
        val allocationSlot = Output(UInt(1.W))
        val completion = Flipped(Decoupled(new FetchOwnedCompletion))
        val result = Decoupled(new FetchTransactionResult)
        val idle = Output(Bool())
    })
    val live = RegInit(VecInit(Seq.fill(2)(false.B)))
    val done = RegInit(VecInit(Seq.fill(2)(false.B)))
    val tokens = Reg(Vec(2, UInt(64.W)))
    val data = Reg(Vec(2, UInt(64.W)))
    val errors = Reg(Vec(2, UInt(2.W)))
    val pages = Reg(Vec(2, UInt(2.W)))
    val head = RegInit(false.B)
    val tail = RegInit(false.B)
    val count = RegInit(0.U(2.W))
    io.result.valid := live(head.asUInt) && done(head.asUInt)
    io.result.bits.token := tokens(head.asUInt)
    io.result.bits.data := data(head.asUInt)
    io.result.bits.accessFaults := errors(head.asUInt)
    io.result.bits.pageFaults := pages(head.asUInt)
    io.allocate.ready := count < 2.U || io.result.fire
    io.allocationSlot := tail.asUInt
    io.completion.ready := true.B // Every admitted command already owns storage.
    io.idle := count === 0.U
    when(io.result.fire) {
        live(head.asUInt) := false.B
        head := !head
    }
    when(io.completion.fire) {
        val c = io.completion.bits
        assert(live(c.slot), "fetch completion has no reserved global owner")
        assert(tokens(c.slot) === c.token, "fetch completion generation mismatch")
        assert(!done(c.slot), "fetch completion duplicated a terminal owner")
        assert(!io.allocate.fire || c.slot =/= tail.asUInt,
            "fetch allocation cannot overwrite a completing owner")
        data(c.slot) := c.data
        errors(c.slot) := c.accessFaults
        pages(c.slot) := c.pageFaults
        done(c.slot) := true.B
    }
    when(io.allocate.fire) {
        assert(!live(tail.asUInt) || (io.result.fire && head === tail), "fetch allocated a live result slot")
        live(tail.asUInt) := true.B
        done(tail.asUInt) := io.allocate.bits.terminal
        tokens(tail.asUInt) := io.allocate.bits.token
        data(tail.asUInt) := 0.U
        errors(tail.asUInt) := 0.U
        pages(tail.asUInt) := 0.U
        tail := !tail
    }
    when(io.allocate.fire =/= io.result.fire) {
        count := Mux(io.allocate.fire, count + 1.U, count - 1.U)
    }
    assert(count <= 2.U && PopCount(live) === count, "fetch global result credit mismatch")
}

class FetchPermissionCommand extends Bundle {
    val slot = UInt(1.W)
    val token = UInt(64.W)
    val address = UInt(64.W)
    val mask = UInt(2.W)
    val privilege = UInt(2.W)
}

class FetchPhysicalCommand extends Bundle {
    val slot = UInt(1.W)
    val token = UInt(64.W)
    val address = UInt(64.W)
    val mask = UInt(2.W)
    val accessFaults = UInt(2.W)
}

/** Existing first-offer PMP edge, now independent of the physical return owner.
  * Input latency one; send/local-fault acceptance releases this stage only.
  * An output stalled at its first offer freezes permission with its PA/token.
  */
class AlignedFetchPermissionStage(pmpEntries: Int, sharedTwoWord: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val input = Flipped(Decoupled(new FetchPermissionCommand))
        val physical = Decoupled(new FetchPhysicalCommand)
        val fault = Decoupled(new FetchOwnedCompletion)
        val pmpState = Input(new PmpState)
        val idle = Output(Bool())
    })
    val valid = RegInit(false.B)
    val owner = Reg(new FetchPermissionCommand)
    val captured = RegInit(false.B)
    val savedMask = Reg(UInt(2.W))
    val savedErrors = Reg(UInt(2.W))
    val denied = Wire(Vec(2, Bool()))
    if (sharedTwoWord && pmpEntries == 16) {
        val checker = Module(new SharedTwoWordFetchPmp)
        checker.io.state := io.pmpState
        checker.io.base := Cat(owner.address(63, 3), 0.U(3.W))
        checker.io.privilege := owner.privilege
        denied := checker.io.denied
    } else for (word <- 0 until 2) {
        val checker = Module(new PmpChecker(pmpEntries, alignedWordAccess = true, decodedWordGranularity = true))
        checker.io.state := io.pmpState
        checker.io.address := Cat(owner.address(63, 3), word.U(1.W), 0.U(2.W))
        checker.io.size := 2.U
        checker.io.privilege := owner.privilege
        checker.io.access := PmpAccess.execute
        denied(word) := checker.io.denied
    }
    val checkedMask = owner.mask & ~denied.asUInt
    val checkedErrors = owner.mask & denied.asUInt
    val mask = Mux(captured, savedMask, checkedMask)
    val errors = Mux(captured, savedErrors, checkedErrors)
    io.physical.valid := valid && mask.orR
    io.physical.bits.slot := owner.slot
    io.physical.bits.token := owner.token
    io.physical.bits.address := owner.address
    io.physical.bits.mask := mask
    io.physical.bits.accessFaults := errors
    io.fault.valid := valid && !mask.orR
    io.fault.bits.slot := owner.slot
    io.fault.bits.token := owner.token
    io.fault.bits.data := 0.U
    io.fault.bits.accessFaults := errors
    io.fault.bits.pageFaults := 0.U
    val release = io.physical.fire || io.fault.fire
    io.input.ready := !valid || release
    io.idle := !valid
    when(valid && !captured) {
        savedMask := checkedMask
        savedErrors := checkedErrors
        captured := true.B
    }
    when(release) { valid := false.B }
    when(io.input.fire) {
        assert(io.input.bits.address(2, 0) === 0.U, "pipelined instruction PA must be eight-byte aligned")
        valid := true.B
        owner := io.input.bits
        captured := false.B
    }
}

/** Bind each accepted ordered physical request to its reserved global slot.
  * Native InstructionPort has no response tag: exactly-once, ordered delivery
  * is a required lower-level contract, independently checked at TL source level.
  * A FIFO alone cannot diagnose a duplicate masquerading as another live reply.
  */
class OrderedFetchPhysicalReturns extends Module {
    val io = IO(new Bundle {
        val command = Flipped(Decoupled(new FetchPhysicalCommand))
        val physical = new InstructionPort
        val completion = Decoupled(new FetchOwnedCompletion)
        val idle = Output(Bool())
    })
    val routes = Module(new Queue(new FetchPhysicalCommand, 2, pipe = true, flow = false))
    io.physical.request.valid := io.command.valid && routes.io.enq.ready
    io.physical.request.bits := io.command.bits.address
    io.physical.requestMask := io.command.bits.mask
    io.command.ready := io.physical.request.ready && routes.io.enq.ready
    routes.io.enq.valid := io.physical.request.fire
    routes.io.enq.bits := io.command.bits
    io.physical.response.ready := routes.io.deq.valid && io.completion.ready
    routes.io.deq.ready := io.physical.response.fire
    io.completion.valid := io.physical.response.valid && routes.io.deq.valid
    io.completion.bits.slot := routes.io.deq.bits.slot
    io.completion.bits.token := routes.io.deq.bits.token
    io.completion.bits.data := io.physical.response.bits
    io.completion.bits.accessFaults := routes.io.deq.bits.accessFaults |
        (io.physical.responseError & routes.io.deq.bits.mask)
    io.completion.bits.pageFaults := io.physical.responsePageFault & routes.io.deq.bits.mask
    io.idle := routes.io.count === 0.U
    when(io.physical.response.valid) {
        // A combinational responder may OFFER on the first request handshake.
        // Ready remains low until that accepted route is registered; the
        // responder must retain its payload until the following acceptance.
        assert(routes.io.deq.valid || io.physical.request.fire, "physical fetch response has no route owner")
    }
    assert(io.command.fire === io.physical.request.fire, "physical fetch route allocation differs from request")
}

/** Two reserved contexts/results, one ordered TLB issuer, independent permission
  * send and physical-return stages. Hit response may accompany its TLB request;
  * a miss keeps this translation context until its actual response handshake.
  * Bare acceptance reaches PMP at the old edge; no extra admission bubble.
  */
class PipelinedAlignedFetchEngine(p: OooParams, sharedTwoWord: Boolean = false) extends Module {
    require(p.renameWidth == 2 && p.compressedInstructions && p.registeredTranslationHeads &&
        p.alignedFetchSinglePage && p.alignedFetchPmp && p.fetchReplyTurnover && p.fetchIdentityTranslation &&
        p.virtualMemoryLevels > 0 && p.pmpEntries > 0 && !p.fetchAddressBeforePmp &&
        !p.alignedFetchPermissionStage && !p.fetchPreviousPacket,
        "two fetch contexts require the explicitly aligned two-lane translation profile")
    val io = IO(new Bundle {
        val command = Flipped(Decoupled(new FetchTransactionCommand))
        val result = Decoupled(new FetchTransactionResult)
        val physical = new InstructionPort
        val translation = new SvTranslationPort
        val pmpState = Input(new PmpState)
        val idle = Output(Bool())
    })
    val ledger = Module(new FetchCompletionLedger)
    val permission = Module(new AlignedFetchPermissionStage(p.pmpEntries, sharedTwoWord))
    val returns = Module(new OrderedFetchPhysicalReturns)
    val completions = Module(new Arbiter(new FetchOwnedCompletion, 3))
    permission.io.pmpState := io.pmpState
    returns.io.command <> permission.io.physical
    io.physical <> returns.io.physical
    completions.io.in(0) <> returns.io.completion
    completions.io.in(1) <> permission.io.fault
    ledger.io.completion <> completions.io.out
    io.result <> ledger.io.result

    val translating = RegInit(false.B)
    val issued = RegInit(false.B)
    val translationCommand = Reg(new FetchTransactionCommand)
    val translationSlot = Reg(UInt(1.W))
    io.translation.request.valid := translating && !issued
    io.translation.request.bits.virtualAddress := translationCommand.virtualAddress
    io.translation.request.bits.rootPpn := translationCommand.satp(43, 0)
    io.translation.request.bits.asid := translationCommand.satp(59, 44)
    io.translation.request.bits.mode := translationCommand.satp(63, 60)
    io.translation.request.bits.privilege := translationCommand.privilege
    io.translation.request.bits.access := PmpAccess.execute
    io.translation.request.bits.sum := translationCommand.sum
    io.translation.request.bits.mxr := translationCommand.mxr
    val translationFault = io.translation.response.bits.pageFault || io.translation.response.bits.accessFault
    completions.io.in(2).valid := translating && io.translation.response.valid && translationFault
    completions.io.in(2).bits.slot := translationSlot
    completions.io.in(2).bits.token := translationCommand.token
    completions.io.in(2).bits.data := 0.U
    completions.io.in(2).bits.accessFaults := Mux(io.translation.response.bits.pageFault,
        0.U, translationCommand.requestMask)
    completions.io.in(2).bits.pageFaults := Mux(io.translation.response.bits.pageFault,
        translationCommand.requestMask, 0.U)
    io.translation.response.ready := translating && Mux(translationFault,
        completions.io.in(2).ready, permission.io.input.ready)

    val identity = io.command.bits.privilege === 3.U || io.command.bits.satp(63, 60) === 0.U
    val emptyIdentity = identity && !io.command.bits.requestMask.orR
    val translationReady = !translating || io.translation.response.fire
    val executionReady = Mux(identity, emptyIdentity || (!translating && permission.io.input.ready), translationReady)
    ledger.io.allocate.valid := io.command.valid && executionReady
    ledger.io.allocate.bits.token := io.command.bits.token
    ledger.io.allocate.bits.terminal := emptyIdentity
    io.command.ready := ledger.io.allocate.ready && executionReady
    val translatedSuccess = translating && io.translation.response.valid && !translationFault
    val directIdentity = io.command.valid && ledger.io.allocate.ready && identity && !emptyIdentity && !translating
    permission.io.input.valid := translatedSuccess || directIdentity
    permission.io.input.bits.slot := Mux(translating, translationSlot, ledger.io.allocationSlot)
    permission.io.input.bits.token := Mux(translating, translationCommand.token, io.command.bits.token)
    permission.io.input.bits.address := Mux(translating,
        io.translation.response.bits.physicalAddress, io.command.bits.virtualAddress)
    permission.io.input.bits.mask := Mux(translating, translationCommand.requestMask, io.command.bits.requestMask)
    permission.io.input.bits.privilege := Mux(translating, translationCommand.privilege, io.command.bits.privilege)
    when(io.translation.request.fire) { issued := true.B }
    when(io.translation.response.fire) {
        translating := false.B
        issued := false.B
    }
    when(io.command.fire) {
        assert(io.command.bits.virtualAddress(2, 0) === 0.U, "pipelined fetch commands must be eight-byte aligned")
        when(!identity) {
            translating := true.B
            issued := false.B
            translationCommand := io.command.bits
            translationSlot := ledger.io.allocationSlot
        }
    }
    when(io.translation.response.valid) {
        assert(translating, "instruction translation response has no context owner")
    }
    io.idle := ledger.io.idle && !translating && permission.io.idle && returns.io.idle
    when(ledger.io.idle) {
        assert(!translating && permission.io.idle && returns.io.idle, "fetch drained global credit before lower obligations")
    }
    assert(io.command.fire === ledger.io.allocate.fire, "fetch command lacks atomic result reservation")
}

/** Public ordered-port compatibility with explicit command/result generations.
  * A result must name the next accepted sequence, including fault-only owners.
  * Context is captured on public fire, or frozen on its first stalled offer
  * so automatic trap privilege changes cannot reinterpret an older request.
  */
class PipelinedAlignedInstructionTranslation(p: OooParams, sharedTwoWord: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val virtual = Flipped(new InstructionPort)
        val physical = new InstructionPort
        val translation = new SvTranslationPort
        val vmState = Input(new VmCsrState)
        val privilege = Input(UInt(2.W))
        val pmpState = Input(new PmpState)
        val idle = Output(Bool())
    })
    val engine = Module(new PipelinedAlignedFetchEngine(p, sharedTwoWord))
    val nextToken = RegInit(0.U(64.W))
    val nextResult = RegInit(0.U(64.W))
    val liveCommand = Wire(new FetchTransactionCommand)
    liveCommand.token := nextToken
    liveCommand.virtualAddress := io.virtual.request.bits
    liveCommand.requestMask := io.virtual.requestMask
    liveCommand.satp := io.vmState.satp
    liveCommand.sum := io.vmState.sum
    liveCommand.mxr := io.vmState.mxr
    liveCommand.privilege := io.privilege
    // Architectural traps can change privilege without the CSR/fence drain.
    // Freeze the complete FIRST PUBLIC held offer, even if inner credit is
    // unavailable. Token allocation still occurs only on actual acceptance.
    val held = RegInit(false.B)
    val heldCommand = Reg(new FetchTransactionCommand)
    engine.io.command.valid := io.virtual.request.valid
    engine.io.command.bits := Mux(held, heldCommand, liveCommand)
    engine.io.command.bits.token := nextToken
    when(io.virtual.request.valid && !io.virtual.request.ready && !held) {
        held := true.B
        heldCommand := liveCommand
    }
    when(io.virtual.request.fire) { held := false.B }
    when(held) {
        assert(io.virtual.request.valid && io.virtual.request.bits === heldCommand.virtualAddress &&
            io.virtual.requestMask === heldCommand.requestMask,
            "held public fetch offer must retain its address and mask")
    }
    io.virtual.request.ready := engine.io.command.ready
    val matches = engine.io.result.bits.token === nextResult
    io.virtual.response.valid := engine.io.result.valid && matches
    io.virtual.response.bits := engine.io.result.bits.data
    io.virtual.responseError := engine.io.result.bits.accessFaults
    io.virtual.responsePageFault := engine.io.result.bits.pageFaults
    engine.io.result.ready := io.virtual.response.ready && matches
    when(engine.io.command.fire) { nextToken := nextToken + 1.U }
    when(engine.io.result.fire) { nextResult := nextResult + 1.U }
    when(engine.io.result.valid) { assert(matches, "pipelined fetch result generation/order mismatch") }
    when(io.virtual.request.valid) {
        assert(io.virtual.request.bits(2, 0) === 0.U, "single-page fetch offers must be eight-byte aligned")
    }
    engine.io.pmpState := io.pmpState
    io.physical <> engine.io.physical
    io.translation <> engine.io.translation
    io.idle := engine.io.idle && nextToken === nextResult && !held
    assert(engine.io.idle === (nextToken === nextResult), "pipelined fetch idle must drain all generations")
}
