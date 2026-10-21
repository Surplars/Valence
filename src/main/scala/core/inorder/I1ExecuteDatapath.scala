package soc.core.inorder

import chisel3._
import chisel3.util._

/** Combinational helpers for the optional FPGA profile. No additional owner or pipeline edge. */
object I1ExecuteDatapath {
    /** Exact vacancy lookahead. No response prediction, owner or pipeline edge. */
    def backendCapacity(rr: Bool, ex: Bool, address: Bool, memory: Bool,
        memoryDone: Bool, executeDone: Bool, progress: Bool): Bool =
        !rr || (progress && !ex) || (progress && executeDone && !address) ||
            (progress && executeDone && !memory) || (progress && executeDone && memoryDone)

    private def preceding(offers: Seq[Bool], index: Int): Bool =
        if (index == 0) false.B else VecInit(offers.take(index)).asUInt.orR

    def operandMasksWhen(enabled: Bool, offers: Seq[Bool]): Seq[Bool] =
        offers.indices.map(i => enabled && offers(i) && !preceding(offers, i))

    def operandMasks(index: UInt, offers: Seq[Bool]): Seq[Bool] =
        operandMasksWhen(index =/= 0.U, offers)

    // Choose the nearest OWNER before checking whether its value is ready.
    // A blocked nearest writer must never select an older same-rd payload.
    def admittedMasks(owners: Seq[Bool], available: Seq[Bool]): Seq[Bool] = {
        require(owners.size == available.size)
        owners.zip(available).map { case (owner, ready) => owner && ready }
    }

    def operand(masks: Seq[Bool], values: Seq[UInt]): UInt = {
        require(masks.size == values.size && masks.nonEmpty)
        // Three source pairs fit one six-input LUT payload group. Keep the
        // near/far reduction explicit instead of a six-way priority mux.
        masks.zip(values).grouped(3).map { group =>
            // Mux1H on a singleton elides its selector. Keep the last group's
            // mask when the arity is 1 mod 3, including the all-zero case.
            if (group.size == 1) Mux(group.head._1, group.head._2, 0.U)
            else Mux1H(group)
        }.reduce(_ | _)
    }

    // Merge PC/immediate qualification BEFORE the one-hot payload reduction,
    // rather than appending another XLEN mux after the forwarded operand.
    def overrideOperand(masks: Seq[Bool], values: Seq[UInt], overrideEnable: Bool,
        overrideValue: UInt, registerEnable: Bool = true.B): UInt =
        operand(masks.map(_ && !overrideEnable && registerEnable), values) |
            Mux(overrideEnable, overrideValue, 0.U)

    // Preserve priority even for an illegal/overlapping control fixture.
    // Production captures these five bits at the existing ID -> RF edge.
    def resultMask(floating: Bool, jump: Bool, csr: Bool, multiply: Bool): UInt = {
        val offers = Seq(floating, jump, csr, multiply, true.B)
        VecInit(offers.indices.map(i => offers(i) && !preceding(offers, i))).asUInt
    }

    def result(mask: UInt, values: Seq[UInt]): UInt = Mux1H(values.indices.map(i => mask(i) -> values(i)))

    // ALU selection is already folded into its operation masks.
    def resultFromEnabledAlu(mask: UInt, other: Seq[UInt], alu: UInt): UInt =
        result(mask, other) | alu

    def numericalLegal(fetchError: Bool, decodedLegal: Bool, floating: Bool,
        fpEnabled: Bool, usesRounding: Bool, rounding: UInt): Bool =
        !fetchError && decodedLegal && (!floating || fpEnabled) && (!usesRounding || rounding <= 4.U)
}
