package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.isa.{Funct3, Funct6, Funct7, Opcode}

/** One combinational lane of the RV64I subset (ISA 20250508) plus Zicond 1.0.0, M 2.0 and B 1.0.0. Unsupported/reserved
  * encodings produce operation 15 with no register dependencies or destination. The backend then reports an ordered
  * illegal-instruction event. System instructions are enabled only for the machine development configuration.
  * IntegerCore expands optional C instructions before they reach this 32-bit decoder.
  */
class IntegerDecode(enableSystem: Boolean = false, enableAtomic: Boolean = false,
    parallelLegality: Boolean = false, parallelBitLegality: Boolean = false,
    experimentalFloatingPoint: Boolean = false,
    floatingPointConfig: FloatingPointConfig = FloatingPointConfig.fullFD) extends Module {
    val io = IO(new Bundle {
        val instruction = Input(UInt(32.W))
        val pc          = Input(UInt(64.W))
        val decoded     = Output(new IntegerRequest)
        val legal       = Output(Bool())
    })
    val inst      = io.instruction
    val opcode    = inst(6, 0)
    val funct3    = inst(14, 12)
    val funct7    = inst(31, 25)
    val immediate = opcode === Opcode.OP_IMM || opcode === Opcode.OP_IMM_32
    val register  = opcode === Opcode.OP || opcode === Opcode.OP_32
    val word      = opcode === Opcode.OP_IMM_32 || opcode === Opcode.OP_32
    val upper     = opcode === Opcode.LUI || opcode === Opcode.AUIPC
    val branch    = opcode === Opcode.BRANCH
    val jal       = opcode === Opcode.JAL
    val jalr      = opcode === Opcode.JALR
    val load      = opcode === Opcode.LOAD
    val store     = opcode === Opcode.STORE
    val atomic    = enableAtomic.B && opcode === "h2f".U
    val atomicOp  = inst(31, 27)
    val memory    = load || store || atomic
    val mulDiv    = register && funct7 === 1.U && (!word || funct3 === 0.U || funct3 >= 4.U)
    val control   = WireDefault(ControlFlow.none)
    val operation = WireDefault(15.U(6.W))
    val legal     = WireDefault(false.B)
    when(atomic) {
        legal := (funct3 === 2.U || funct3 === 3.U) &&
            Seq(0, 1, 2, 3, 4, 8, 12, 16, 20, 24, 28).map(n => atomicOp === n.U).reduce(_ || _) &&
            (atomicOp =/= 2.U || inst(24, 20) === 0.U)
        operation := IntegerOp.add
    }.elsewhen(mulDiv) {
        legal     := true.B
        operation := IntegerOp.add
    }.elsewhen(opcode === Opcode.OP && funct7 === 7.U && (funct3 === 5.U || funct3 === 7.U)) {
        // Zicond 1.0.0: both register dependencies remain live even when the result is zero.
        legal     := true.B
        operation := Mux(funct3 === 5.U, IntegerOp.czeroEqz, IntegerOp.czeroNez)
    }.elsewhen(memory) {
        legal     := Mux(store, funct3 <= 3.U, funct3 =/= 7.U)
        operation := IntegerOp.add
    }.elsewhen(branch) {
        control := MuxLookup(funct3, ControlFlow.none)(
            Seq(
                Funct3.I.BEQ  -> ControlFlow.beq,
                Funct3.I.BNE  -> ControlFlow.bne,
                Funct3.I.BLT  -> ControlFlow.blt,
                Funct3.I.BGE  -> ControlFlow.bge,
                Funct3.I.BLTU -> ControlFlow.bltu,
                Funct3.I.BGEU -> ControlFlow.bgeu
            )
        )
        legal     := control =/= ControlFlow.none
        operation := IntegerOp.add
    }.elsewhen(jal || jalr) {
        legal     := jal || funct3 === Funct3.I.JALR
        control   := Mux(jal, ControlFlow.jal, ControlFlow.jalr)
        operation := IntegerOp.add
    }.elsewhen(upper) {
        operation := IntegerOp.add
        legal     := true.B
    }.elsewhen(immediate || register) {
        switch(funct3) {
            is(Funct3.I.ADDSUB) {
                operation := Mux(register && inst(30), IntegerOp.sub, IntegerOp.add)
                legal     := immediate || funct7 === ("b" + Funct7.Z).U || funct7 === ("b" + Funct7.NZ).U
            }
            is(Funct3.I.SLL) {
                operation := IntegerOp.sll
                legal     := Mux(immediate && !word, inst(31, 26) === ("b" + Funct6.Z).U, funct7 === ("b" + Funct7.Z).U)
            }
            is(Funct3.I.SLT) {
                operation := IntegerOp.slt
                legal     := !word && (immediate || funct7 === ("b" + Funct7.Z).U)
            }
            is(Funct3.I.SLTU) {
                operation := IntegerOp.sltu
                legal     := !word && (immediate || funct7 === ("b" + Funct7.Z).U)
            }
            is(Funct3.I.XOR) {
                operation := IntegerOp.xor
                legal     := !word && (immediate || funct7 === ("b" + Funct7.Z).U)
            }
            is(Funct3.I.SRL_SRA) {
                operation := Mux(inst(30), IntegerOp.sra, IntegerOp.srl)
                legal     := Mux(
                    immediate && !word,
                    inst(31, 26) === ("b" + Funct6.Z).U || inst(31, 26) === ("b" + Funct6.NZ).U,
                    funct7 === ("b" + Funct7.Z).U || funct7 === ("b" + Funct7.NZ).U
                )
            }
            is(Funct3.I.OR) {
                operation := IntegerOp.or
                legal     := !word && (immediate || funct7 === ("b" + Funct7.Z).U)
            }
            is(Funct3.I.AND) {
                operation := IntegerOp.and
                legal     := !word && (immediate || funct7 === ("b" + Funct7.Z).U)
            }
        }
    }
    val bits = Module(new IntegerBitDecode(parallelBitLegality))
    bits.io.instruction := inst
    when(bits.io.legal) {
        legal     := true.B
        operation := bits.io.operation
    }
    val fence  = enableSystem.B && opcode === "h0f".U && (funct3 === 0.U || funct3 === 1.U)
    val sfenceVma = inst(31, 25) === "b0001001".U && inst(14, 7) === 0.U
    val floatingPoint = experimentalFloatingPoint.B && enableSystem.B &&
        FloatingPointDecode.supported(inst, floatingPointConfig)
    val system = floatingPoint || fence || (enableSystem.B && opcode === "h73".U &&
        (Seq(1, 2, 3, 5, 6, 7).map(f => funct3 === f.U).reduce(_ || _) ||
            inst === "h00000073".U || inst === "h00100073".U || inst === "h30200073".U ||
            inst === "h10200073".U || inst === "h10500073".U || sfenceVma))
    when(system) { legal := true.B; operation := IntegerOp.add }
    if (parallelLegality) {
        val qualification = Module(new ParallelIntegerLegality(enableSystem, enableAtomic))
        qualification.io.instruction := inst
        qualification.io.bitLegal := bits.io.legal
        legal := qualification.io.legal || floatingPoint
    }
    io.legal                      := legal
    io.decoded                    := 0.U.asTypeOf(new IntegerRequest)
    io.decoded.rename.pc          := io.pc
    io.decoded.rename.instruction := inst
    io.decoded.expandedInstruction := inst
    io.decoded.rename.rd          := Mux(legal && (branch || store), 0.U, inst(11, 7))
    io.decoded.rename.rs1         := Mux(legal && !upper && !jal, inst(19, 15), 0.U)
    io.decoded.rename.rs2         := Mux(
        legal && (register || branch || store || atomic) && !bits.io.singleSource,
        inst(24, 20),
        0.U
    )
    io.decoded.rename.writesRd := legal && !branch && !store
    io.decoded.operation       := Mux(legal, operation, 15.U)
    io.decoded.word            := Mux(bits.io.legal, bits.io.word, word && legal)
    io.decoded.mulDiv          := mulDiv
    io.decoded.mulDivOp        := Mux(mulDiv, funct3, 0.U)
    io.decoded.memory          := legal && memory
    io.decoded.atomic          := legal && atomic
    io.decoded.atomicOp        := Mux(legal && atomic, atomicOp, 0.U)
    io.decoded.store           := legal && store
    io.decoded.memorySize      := Mux(legal && memory, funct3(1, 0), 0.U)
    io.decoded.memoryUnsigned  := legal && load && funct3(2)
    io.decoded.controlFlow     := Mux(legal, control, ControlFlow.none)
    io.decoded.usePc           := (opcode === Opcode.AUIPC || jal) && legal
    io.decoded.useImmediate    := !(register || branch || store || atomic) || !legal || bits.io.singleSource
    io.decoded.immediate       := Mux(
        upper,
        Cat(Fill(32, inst(31)), inst(31, 12), 0.U(12.W)),
        Cat(Fill(52, inst(31)), inst(31, 20))
    )
    io.decoded.system := system
    when(system) {
        io.decoded.rename.rs1      := Mux(!fence && funct3 =/= 0.U && !funct3(2), inst(19, 15), 0.U)
        io.decoded.rename.rs2      := 0.U
        io.decoded.rename.rd       := Mux(fence || funct3 === 0.U, 0.U, inst(11, 7))
        io.decoded.rename.writesRd := !fence && funct3 =/= 0.U
        io.decoded.useImmediate    := true.B
    }
    when(floatingPoint) {
        // FP register numbers must never become integer PRF dependencies/destinations.
        val fromInteger = FloatingPointDecode.readsInteger(inst)
        val toInteger = FloatingPointDecode.writesInteger(inst)
        io.decoded.rename.rs1 := Mux(fromInteger, inst(19, 15), 0.U)
        io.decoded.rename.rs2 := 0.U
        io.decoded.rename.rd := Mux(toInteger, inst(11, 7), 0.U)
        io.decoded.rename.writesRd := toInteger
    }
    when(atomic) {
        io.decoded.immediate := 0.U
    }.elsewhen(store) {
        io.decoded.immediate := Cat(Fill(52, inst(31)), inst(31, 25), inst(11, 7))
    }.elsewhen(branch) {
        io.decoded.immediate := Cat(Fill(51, inst(31)), inst(31), inst(7), inst(30, 25), inst(11, 8), 0.U(1.W))
    }.elsewhen(jal) {
        io.decoded.immediate := Cat(Fill(43, inst(31)), inst(31), inst(19, 12), inst(20), inst(30, 21), 0.U(1.W))
    }
}
