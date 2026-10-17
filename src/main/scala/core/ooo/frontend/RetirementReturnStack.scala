package soc.core.ooo

import chisel3._
import chisel3.util._

class ReturnStackCommit extends Bundle {
    val pc = UInt(64.W)
    val instruction = UInt(32.W)
    val rd = UInt(5.W)
    val writesRd = Bool()
    val data = UInt(64.W)
}

/** Retirement-trained circular RAS. Capacity depth, up to width ordered actions
  * per cycle, no input backpressure, no extra prediction/training cycle. Full
  * pushes overwrite the oldest physical entry and saturate count, as before.
  * Prediction reads pre-edge state; invalid payloads never mutate the stack.
  * PC-derived links sever general completion-data -> RAS data feedback without
  * changing architectural writeback or the existing call/return classification.
  */
class RetirementReturnStack(depth: Int, width: Int, pcDerivedLinks: Boolean,
    parallelControl: Boolean = false) extends Module {
    require(depth >= 2 && depth <= 32 && (depth & (depth - 1)) == 0)
    require(width >= 1 && width <= 6)
    require(!parallelControl || width == 2)
    val io = IO(new Bundle {
        val commit = Input(Vec(width, Valid(new ReturnStackCommit)))
        val available = Output(Bool())
        val target = Output(UInt(64.W))
        val occupancy = Output(UInt(log2Ceil(depth + 1).W))
    })
    val top = RegInit(0.U(log2Ceil(depth).W))
    val count = RegInit(0.U(log2Ceil(depth + 1).W))
    val entries = Reg(Vec(depth, UInt(64.W)))
    io.available := count =/= 0.U
    io.target := entries(top - 1.U)
    io.occupancy := count
    def classification(lane: Int): (Bool, Bool, UInt) = {
        val commit = io.commit(lane)
        val inst = commit.bits.instruction
        val short = inst(1, 0) =/= 3.U
        val linkRd = commit.bits.rd === 1.U || commit.bits.rd === 5.U
        val linkRs1 = inst(19, 15) === 1.U || inst(19, 15) === 5.U
        val compressedControl = short && inst(1, 0) === 2.U && inst(15, 13) === 4.U &&
            inst(6, 2) === 0.U && inst(11, 7) =/= 0.U
        val call = ((short && compressedControl && inst(12)) ||
            (!short && linkRd && commit.bits.writesRd &&
                (inst(6, 0) === "h6f".U || inst(6, 0) === "h67".U)))
        val ret = !call &&
            ((short && compressedControl && !inst(12) &&
                (inst(11, 7) === 1.U || inst(11, 7) === 5.U)) ||
            (!short && inst(6, 0) === "h67".U && inst(14, 12) === 0.U &&
                inst(11, 7) === 0.U && linkRs1 && inst(31, 20) === 0.U))
        // Calculate both constants in parallel; instruction length selects a
        // completed PC increment rather than starting a late variable increment.
        val link = if (pcDerivedLinks) Mux(short, commit.bits.pc + 2.U, commit.bits.pc + 4.U)
            else commit.bits.data
        (call, ret, link)
    }
    if (parallelControl) {
        // Speculate both payload actions before late commit.valid arrives. Four
        // valid-mask states preserve every ordered packet, even invalid lane 0.
        // No added registers/training cycle; lane 1 still wins colliding writes.
        val actions = (0 until 2).map(classification)
        def advance(at: UInt, used: UInt, lane: Int): (UInt, UInt) = {
            val (call, ret, _) = actions(lane)
            val pop = ret && used =/= 0.U
            val increment = (at + 1.U)(log2Ceil(depth) - 1, 0)
            val decrement = (at - 1.U)(log2Ceil(depth) - 1, 0)
            val nextAt = Mux(call, increment, Mux(pop, decrement, at))
            val nextUsed = Mux(call, Mux(used === depth.U, used, used + 1.U),
                Mux(pop, used - 1.U, used))
            (nextAt, nextUsed)
        }
        val first = advance(top, count, 0)
        val secondOnly = advance(top, count, 1)
        val both = advance(first._1, first._2, 1)
        val mask = Cat(io.commit(1).valid, io.commit(0).valid)
        top := MuxLookup(mask, top)(Seq(1.U -> first._1, 2.U -> secondOnly._1, 3.U -> both._1))
        count := MuxLookup(mask, count)(Seq(1.U -> first._2, 2.U -> secondOnly._2, 3.U -> both._2))
        for (slot <- 0 until depth) {
            val firstHere = top === slot.U
            val secondHere = Mux(io.commit(0).valid, first._1 === slot.U, firstHere)
            when(io.commit(0).valid && actions(0)._1 && firstHere) { entries(slot) := actions(0)._3 }
            when(io.commit(1).valid && actions(1)._1 && secondHere) { entries(slot) := actions(1)._3 }
        }
    } else {
        var nextTop = top
        var nextCount = count
        for (lane <- 0 until width) {
            val (callType, retType, link) = classification(lane)
            val call = io.commit(lane).valid && callType
            val pop = io.commit(lane).valid && retType && nextCount =/= 0.U
            when(call) { entries(nextTop) := link }
            nextTop = Mux(call, nextTop + 1.U, Mux(pop, nextTop - 1.U, nextTop))
            nextCount = Mux(call, Mux(nextCount === depth.U, nextCount, nextCount + 1.U),
                Mux(pop, nextCount - 1.U, nextCount))
        }
        top := nextTop
        count := nextCount
    }
}
