package soc.core.ooo

import chisel3._
import chisel3.util._

/** Stateless B datapath: one combinational result per lane/cycle, no queue or private completion port. Scheduling,
  * backpressure and recovery are inherited from IntegerAlu. See docs/rv64b.md for the contract.
  */
class IntegerBitManip(parallelResult: Boolean = false, parallelAddressSums: Boolean = false,
    parallelMinMax: Boolean = false, externalMinMax: Boolean = false, earlyWordResults: Boolean = false) extends Module {
    require(!parallelAddressSums || parallelResult)
    require(!parallelMinMax || parallelResult)
    require(!externalMinMax || (parallelMinMax && parallelResult))
    require(!earlyWordResults || (parallelAddressSums && externalMinMax))
    val io = IO(new Bundle {
        val operation = Input(UInt(6.W))
        val word      = Input(Bool())
        val left      = Input(UInt(64.W))
        val right     = Input(UInt(64.W))
        val result    = Output(UInt(64.W))
        val legal     = Output(Bool())
        val addressResult = if (earlyWordResults) Some(Output(UInt(64.W))) else None
    })
    // Prepare W payload per independent class before late one-hot qualification.
    def wordResult(data: UInt): UInt = {
        val xlen = Wire(UInt(64.W))
        xlen := data
        Mux(io.word, Cat(Fill(32, xlen(31)), xlen(31, 0)), xlen)
    }
    val op    = io.operation
    val a     = io.left
    val b     = io.right
    val uw    = op >= IntegerOp.addUw && op <= IntegerOp.slliUw
    val index = Mux(uw, Cat(0.U(32.W), a(31, 0)), a)
    // Fixed 0/1/2/3 shifts ahead of one shared address-generation adder.
    val shiftedIndex = MuxLookup(op, index)(
        Seq(
            IntegerOp.sh1add   -> (index << 1)(63, 0),
            IntegerOp.sh1addUw -> (index << 1)(63, 0),
            IntegerOp.sh2add   -> (index << 2)(63, 0),
            IntegerOp.sh2addUw -> (index << 2)(63, 0),
            IntegerOp.sh3add   -> (index << 3)(63, 0),
            IntegerOp.sh3addUw -> (index << 3)(63, 0)
        )
    )
    val address    = shiftedIndex + b
    val countInput = Mux(io.word, Cat(0.U(32.W), a(31, 0)), a)
    // Balanced binary selection: six levels rather than a 64-way linear priority chain.
    def leadingZeros(x: UInt, width: Int): UInt = {
        if (width == 1) (!x(0)).asUInt
        else {
            val half = width / 2
            val high = x(width - 1, half)
            val low  = x(half - 1, 0)
            Mux(
                high.orR,
                Cat(0.U(1.W), leadingZeros(high, half)),
                half.U(log2Ceil(width + 1).W) + leadingZeros(low, half)
            )
        }
    }
    val clz = leadingZeros(countInput, 64) - Mux(io.word, 32.U, 0.U)
    val ctz = Mux(countInput.orR, leadingZeros(Reverse(countInput), 64), Mux(io.word, 32.U, 64.U))
    // Repeated low word allows the same six-level rotate network for 32/64 bits.
    val rotateInput  = Mux(io.word, Cat(a(31, 0), a(31, 0)), a)
    val amount       = Mux(io.word, Cat(0.U(1.W), b(4, 0)), b(5, 0))
    val rotateAmount = Mux(op === IntegerOp.rol, (0.U(6.W) - amount), amount)
    val rotated      = (0 until 6).foldLeft(rotateInput) { (value, bit) =>
        val distance = 1 << bit
        Mux(rotateAmount(bit), Cat(value(distance - 1, 0), value(63, distance)), value)
    }
    val signedLess   = a.asSInt < b.asSInt
    val unsignedLess = a < b
    val bitMask      = (1.U(64.W) << b(5, 0))(63, 0)
    val results = Seq(
            IntegerOp.sh1add   -> address,
            IntegerOp.sh2add   -> address,
            IntegerOp.sh3add   -> address,
            IntegerOp.addUw    -> address,
            IntegerOp.sh1addUw -> address,
            IntegerOp.sh2addUw -> address,
            IntegerOp.sh3addUw -> address,
            IntegerOp.slliUw   -> (index << b(5, 0))(63, 0),
            IntegerOp.andn     -> (a & ~b),
            IntegerOp.orn      -> (a | ~b),
            IntegerOp.xnor     -> ~(a ^ b),
            IntegerOp.clz      -> clz,
            IntegerOp.ctz      -> ctz,
            IntegerOp.cpop     -> PopCount(countInput),
            IntegerOp.min      -> Mux(signedLess, a, b),
            IntegerOp.minU     -> Mux(unsignedLess, a, b),
            IntegerOp.max      -> Mux(signedLess, b, a),
            IntegerOp.maxU     -> Mux(unsignedLess, b, a),
            IntegerOp.sextB    -> Cat(Fill(56, a(7)), a(7, 0)),
            IntegerOp.sextH    -> Cat(Fill(48, a(15)), a(15, 0)),
            IntegerOp.zextH    -> a(15, 0),
            IntegerOp.rol      -> rotated,
            IntegerOp.ror      -> rotated,
            IntegerOp.orcB     -> Cat((0 until 8).reverse.map(i => Fill(8, a(8 * i + 7, 8 * i).orR))),
            IntegerOp.rev8     -> Cat((0 until 8).map(i => a(8 * i + 7, 8 * i))),
            IntegerOp.bclr     -> (a & ~bitMask),
            IntegerOp.bset     -> (a | bitMask),
            IntegerOp.binv     -> (a ^ bitMask),
            IntegerOp.bext     -> a(b(5, 0)).asUInt
        )
    if (parallelResult) {
        // Address and rotate aliases share data; operation qualification is
        // independent of the late operand result and illegal controls yield 0.
        val addressOps = Seq(IntegerOp.sh1add, IntegerOp.sh2add, IntegerOp.sh3add,
            IntegerOp.addUw, IntegerOp.sh1addUw, IntegerOp.sh2addUw, IntegerOp.sh3addUw)
        val rotateOps = Seq(IntegerOp.rol, IntegerOp.ror)
        // Run fixed-shift additions independently of opcode/unsigned-word
        // selection. Only the final one-hot result waits for those controls.
        // Full XLEN carry/wrap semantics and the original illegal-W payload stay
        // unchanged; this trades combinational adders for no extra execute cycle.
        val addressResults = if (parallelAddressSums) {
            val unsignedWord = Cat(0.U(32.W), a(31, 0))
            Seq(IntegerOp.addUw -> (unsignedWord + b)) ++
                Seq((IntegerOp.sh1add, IntegerOp.sh1addUw, 1),
                    (IntegerOp.sh2add, IntegerOp.sh2addUw, 2),
                    (IntegerOp.sh3add, IntegerOp.sh3addUw, 3)).flatMap { case (full, word, shift) =>
                    Seq(full -> (((a << shift)(63, 0)) + b),
                        word -> (((unsignedWord << shift)(63, 0)) + b))
                }
        } else Seq.empty
        val addressSelect = if (parallelAddressSums)
            addressResults.map { case (code, value) => (op === code) -> value }
        else Seq(addressOps.map(op === _).reduce(_ || _) -> address)
        val minMaxOps = Seq(IntegerOp.min, IntegerOp.max, IntegerOp.minU, IntegerOp.maxU)
        // Select two raw operands directly, not four comparator-selected64 payloads.
        val minMaxSelect = if (parallelMinMax && !externalMinMax) Seq(
            ((op === IntegerOp.min && signedLess) || (op === IntegerOp.max && !signedLess) ||
                (op === IntegerOp.minU && unsignedLess) || (op === IntegerOp.maxU && !unsignedLess)) -> a,
            ((op === IntegerOp.min && !signedLess) || (op === IntegerOp.max && signedLess) ||
                (op === IntegerOp.minU && !unsignedLess) || (op === IntegerOp.maxU && unsignedLess)) -> b
        ) else Seq.empty
        io.addressResult.foreach { output =>
            output := Mux1H(addressSelect.map { case (grant, data) => grant -> wordResult(data) })
        }
        // Address sums bypass the unrelated count/rotate/logical result tree.
        val shared = (if (earlyWordResults) Seq.empty else addressSelect) ++ minMaxSelect ++ Seq(
            rotateOps.map(op === _).reduce(_ || _) -> rotated)
        val remaining = results.filterNot { case (code, _) =>
            val value = code.litValue
            addressOps.exists(_.litValue == value) || rotateOps.exists(_.litValue == value) ||
                (parallelMinMax && minMaxOps.exists(_.litValue == value))
        }.map { case (code, data) =>
            // Some count expressions have an inferred width at construction.
            // Normalize at the XLEN boundary exactly as the legacy output does.
            val xlenResult = Wire(UInt(64.W))
            xlenResult := data
            (op === code) -> xlenResult
        }
        val classes = shared ++ remaining
        io.result := Mux1H(if (earlyWordResults)
            classes.map { case (grant, data) => grant -> wordResult(data) } else classes)
    } else {
        io.result := MuxLookup(op, 0.U(64.W))(results)
    }
    io.legal := op >= IntegerOp.sh1add && op <= IntegerOp.bext && (!io.word ||
        op === IntegerOp.clz || op === IntegerOp.ctz || op === IntegerOp.cpop ||
        op === IntegerOp.rol || op === IntegerOp.ror)
}
