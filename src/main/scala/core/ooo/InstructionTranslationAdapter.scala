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
    if (packetWords == 4) {
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
