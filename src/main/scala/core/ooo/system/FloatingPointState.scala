package soc.core.ooo

import chisel3._
import chisel3.util._

/** Architectural transport is IEEE binary64, with boxed binary32; never HardFloat recFN. */
object FloatingPointBits {
    val flen = 64
    val registers = 32
    def boxSingle(value: UInt): UInt = Cat("hffffffff".U(32.W), value(31, 0))
    def operand(value: UInt, checkSingleBox: Bool): UInt =
        Mux(checkSingleBox && !value(63, 32).andR, "hffffffff7fc00000".U(64.W), value)
}

/** Decoded command from the ROB-head adapter. This is NOT an ISA decoder. */
class FloatingPointCommand(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val instruction = UInt(32.W)
    val sources = Vec(3, UInt(5.W))
    // Computational S operands check boxing; FSW and FMV.X.W must use raw bits.
    // Per-source qualification permits mixed-format conversions.
    val checkSingleBox = Vec(3, Bool())
    val integerSource = UInt(64.W)
    val destination = UInt(5.W)
    val singleResult = Bool()
    val writesFp = Bool()
    val writesFlags = Bool()
    val usesRounding = Bool()
    val rounding = UInt(3.W)
}

class FloatingPointExecution(p: OooParams) extends Bundle {
    val command = new FloatingPointCommand(p)
    val operands = Vec(3, UInt(64.W))
    val rounding = UInt(3.W)
}

/** Result/fault envelope shared by a future arithmetic or FP memory adapter.
  * FP flags are accrued data, not traps; memory faults use exception/cause/tval.
  */
class FloatingPointResult(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val value = UInt(64.W)
    val flags = UInt(5.W)
    val exception = Bool()
    val cause = UInt(6.W)
    val tval = UInt(64.W)
}

class FloatingPointCsr extends Bundle {
    val address = UInt(12.W)
    val operation = UInt(2.W) // 0=write, 1=set, 2=clear; 3 is illegal
    val write = Bool()       // false for CSRRS/CSRRC with zero source
    val value = UInt(64.W)
}

/** Conservative FLEN=64 state and single-outstanding transaction boundary.
  *
  * Three combinational architectural reads, one retirement write, no FP rename.
  * issue -> registered execute -> registered completion -> exact-token retirement.
  * No same-cycle refill; throughput is deliberately bounded by retirement.
  * A caller must authorize the oldest instruction and serialize CSR/context access.
  * All architectural changes occur at retirement or an authorized idle CSR/FS access.
  * Flush wins over issue/result/retirement and never rolls back committed FP state.
  * Producers must echo the complete non-reused ROB token; reset must drain/reset them.
  * No board instantiation, misa bit or device-tree F/D advertisement is added by M1.
  */
class FloatingPointState(val p: OooParams) extends Module {
    val io = IO(new Bundle {
        val headAuthorized = Input(Bool())
        val flush = Input(Bool())
        val issue = Flipped(Decoupled(new FloatingPointCommand(p)))
        val execute = Decoupled(new FloatingPointExecution(p))
        val result = Flipped(Decoupled(new FloatingPointResult(p)))
        val complete = Output(Valid(new FloatingPointResult(p)))
        val retire = Input(Valid(new RobToken(p)))
        val retireAccepted = Output(Bool())
        val csr = Flipped(Decoupled(new FloatingPointCsr))
        val csrRead = Output(UInt(64.W))
        val csrIllegal = Output(Bool())
        // Future mstatus/sstatus adapter owns privilege/CSR-mask checks.
        val setFs = Flipped(Decoupled(UInt(2.W)))
        val fs = Output(UInt(2.W))
        val sd = Output(Bool())
        val fcsr = Output(UInt(8.W))
        val busy = Output(Bool())
    })
    // One committed write and three asynchronous operand reads fit distributed
    // FPGA RAM. Payload is never reset; resettable validity supplies architectural
    // zero until the first committed write, including across reset after use.
    private val memoryPayload = if (p.fpConfig.resources.committedStateMemory)
        Some(Mem(FloatingPointBits.registers, UInt(64.W))) else None
    private val registerPayload = if (!p.fpConfig.resources.committedStateMemory)
        Some(RegInit(VecInit(Seq.fill(FloatingPointBits.registers)(0.U(64.W))))) else None
    private val initialized = if (p.fpConfig.resources.committedStateMemory)
        Some(RegInit(VecInit(Seq.fill(FloatingPointBits.registers)(false.B)))) else None
    private def storedRegister(index: UInt): UInt = memoryPayload match {
        case Some(payload) => Mux(initialized.get(index), payload.read(index), 0.U(64.W))
        case None => BankedOneHotRead(registerPayload.get, index)
    }
    val frm = RegInit(0.U(3.W))
    val flags = RegInit(0.U(5.W))
    val fs = RegInit(0.U(2.W))
    val idle :: send :: waiting :: completed :: Nil = Enum(4)
    val state = RegInit(idle)
    val pending = Reg(new FloatingPointExecution(p))
    val response = Reg(new FloatingPointResult(p))
    val destination = Reg(UInt(FloatingPointBits.registers.W))
    // Architectural retirement remains immediate. Only the physical array
    // write is delayed one edge, with exact committed-value read forwarding.
    // An older accepted write MUST survive a following younger flush.
    val committedMask = RegInit(0.U(FloatingPointBits.registers.W))
    val committedValue = Reg(UInt(64.W))
    private val committedAddress = Reg(UInt(5.W))
    private val committedValid = committedMask.orR

    val idleAuthorized = state === idle && io.headAuthorized && !io.flush
    io.setFs.ready := idleAuthorized
    io.csr.ready := idleAuthorized && !io.setFs.valid
    io.issue.ready := idleAuthorized && !io.setFs.valid && !io.csr.valid
    io.execute.valid := state === send && !io.flush
    io.execute.bits := pending
    // Drain stale completions too: a killed producer must not block its successor.
    io.result.ready := true.B
    io.complete.valid := state === completed && !io.flush
    io.complete.bits := response
    io.retireAccepted := io.complete.valid && io.retire.valid && io.headAuthorized &&
        io.retire.bits.asUInt === pending.command.token.asUInt
    io.fs := fs
    io.sd := fs === 3.U
    io.fcsr := Cat(frm, flags)
    io.busy := state =/= idle
    committedMask := Mux(io.retireAccepted && !response.exception && pending.command.writesFp,
        destination, 0.U)
    committedValue := Mux(pending.command.singleResult, FloatingPointBits.boxSingle(response.value), response.value)
    // No flush qualification here: this write was already irrevocably accepted
    // on the preceding edge. A younger flush must not discard an older commit.
    committedAddress := pending.command.destination
    memoryPayload match {
        case Some(payload) =>
            when(committedValid) {
                payload.write(committedAddress, committedValue)
                initialized.get(committedAddress) := true.B
            }
        case None =>
            for (register <- 0 until FloatingPointBits.registers) {
                when(committedMask(register)) { registerPayload.get(register) := committedValue }
            }
    }
    // Observational architectural view; the production read below uses the
    // equivalent per-port forwarding to avoid a 32-entry payload mux layer.
    // Test-only observation is eliminated when unused; normalized production
    // RTL must retain only the three real operand reads (checked structurally).
    val architecturalRegisters = VecInit((0 until FloatingPointBits.registers).map { register =>
        Mux(committedMask(register), committedValue, storedRegister(register.U(5.W)))
    })

    val csrKnown = io.csr.bits.address === 1.U || io.csr.bits.address === 2.U || io.csr.bits.address === 3.U
    io.csrRead := MuxLookup(io.csr.bits.address, 0.U(64.W))(Seq(
        1.U -> flags.pad(64), 2.U -> frm.pad(64), 3.U -> Cat(frm, flags).pad(64)))
    io.csrIllegal := !csrKnown || fs === 0.U || io.csr.bits.operation === 3.U
    val csrWritten = MuxLookup(io.csr.bits.operation, io.csr.bits.value)(Seq(
        1.U -> (io.csrRead | io.csr.bits.value), 2.U -> (io.csrRead & ~io.csr.bits.value)))
    when(io.setFs.fire) { fs := io.setFs.bits }
    when(io.csr.fire && io.csr.bits.write && !io.csrIllegal) {
        when(io.csr.bits.address === 1.U) { flags := csrWritten(4, 0) }
        when(io.csr.bits.address === 2.U) { frm := csrWritten(2, 0) }
        when(io.csr.bits.address === 3.U) {
            flags := csrWritten(4, 0)
            frm := csrWritten(7, 5)
        }
        fs := 3.U
    }

    when(io.issue.fire) {
        pending.command := io.issue.bits
        destination := UIntToOH(io.issue.bits.destination, FloatingPointBits.registers)
        for (lane <- 0 until 3) {
            val source = io.issue.bits.sources(lane)
            val stored = storedRegister(source)
            val architectural = Mux(committedMask(source), committedValue, stored)
            pending.operands(lane) := FloatingPointBits.operand(
                architectural, io.issue.bits.checkSingleBox(lane))
        }
        val effectiveRounding = Mux(io.issue.bits.rounding === 7.U, frm, io.issue.bits.rounding)
        pending.rounding := effectiveRounding
        val illegal = fs === 0.U || (io.issue.bits.usesRounding && effectiveRounding > 4.U)
        state := Mux(illegal, completed, send)
        response := 0.U.asTypeOf(new FloatingPointResult(p))
        response.token := io.issue.bits.token
        response.exception := illegal
        response.cause := Mux(illegal, 2.U, 0.U)
        response.tval := Mux(illegal, io.issue.bits.instruction.pad(64), 0.U)
    }
    when(io.execute.fire) { state := waiting }
    when(io.result.fire && state === waiting && !io.flush &&
        io.result.bits.token.asUInt === pending.command.token.asUInt) {
        response := io.result.bits
        state := completed
    }
    when(io.retireAccepted) {
        when(!response.exception) {
            // f0 is writable. Its committed array write/forwarding above is
            // independent of the high-fanout same-cycle ROB retirement grant.
            when(pending.command.writesFlags) { flags := flags | response.flags }
            when(pending.command.writesFp || pending.command.writesFlags) { fs := 3.U }
        }
        state := idle
    }
    when(io.flush) { state := idle }
}
