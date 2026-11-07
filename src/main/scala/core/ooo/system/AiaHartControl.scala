package soc.core.ooo

import chisel3._
import chisel3.util._

/** RV64 AIA 1.0 hart-local interrupt nomination with read-only-zero iprio/hviprio arrays.
  *
  * Contract: mCandidates and hsCandidates are already enabled and delegation-filtered,
  * but not filtered by global interrupt enables or the current privilege mode. vsip/vsie
  * use VS cause numbering. guestTopei is the LIVE selected guest interrupt-file value,
  * not a cached CSR response. The caller owns CSR privilege checks and trap entry.
  *
  * All three nominations are combinational (latency 0, initiation interval 1, no queues
  * or backpressure). One committed hvictl write is accepted per cycle and takes effect
  * on the next cycle. IID implements exactly six WARL bits, including every value 0-63.
  * Encoding priority trees are balanced; physical timing/area remain unqualified.
  */
class AiaHartControl extends Module {
    val io = IO(new Bundle {
        val mCandidates = Input(UInt(64.W))
        val hsCandidates = Input(UInt(64.W))
        val vsip = Input(UInt(64.W))
        val vsie = Input(UInt(64.W))
        val vgein = Input(UInt(6.W))
        val guestFileValid = Input(Bool())
        val guestTopei = Input(UInt(32.W))
        val commit = Input(Bool())
        val hvictlWrite = Flipped(Valid(UInt(64.W)))
        val mtopi = Output(UInt(64.W))
        val stopi = Output(UInt(64.W))
        val vstopi = Output(UInt(64.W))
        val hvictl = Output(UInt(64.W))
        val vti = Output(Bool())
    })

    // AIA v1.0 section 4.1.1: standard interrupts, with the specified proposed order
    // for future local interrupts. Platform choice for otherwise unassigned/custom
    // IDs: below all these standard IDs, in ascending order, with 0/4/8 last.
    // Callers must mask interrupt identities which their hart does not implement.
    private val defaultOrder = Seq(47, 23, 46, 45, 22, 44, 43, 21, 42, 41, 20, 40,
        11, 3, 7, 9, 1, 5, 12, 10, 2, 6, 13, 39, 19, 38, 37, 18, 36,
        35, 17, 34, 33, 16, 32, 14, 15) ++ (24 to 31) ++ (48 to 63) ++ Seq(0, 4, 8)
    require(defaultOrder.sorted == (0 until 64))
    private val aboveSeiMask = defaultOrder.takeWhile(_ != 9)
        .foldLeft(BigInt(0))((mask, id) => mask.setBit(id))

    private def winner(mask: UInt): (Bool, UInt) = {
        def tree(entries: Seq[(Bool, UInt)]): (Bool, UInt) = {
            if (entries.size == 1) entries.head
            else {
                val (a, b) = entries.splitAt(entries.size / 2)
                val left = tree(a)
                val right = tree(b)
                (left._1 || right._1, Mux(left._1, left._2, right._2))
            }
        }
        tree(defaultOrder.map(id => (mask(id), id.U(6.W))))
    }
    private def topi(valid: Bool, iid: UInt, priority: UInt): UInt =
        Mux(valid, Cat(0.U(36.W), iid.pad(12), 0.U(8.W), priority), 0.U(64.W))

    // Simplified IPRIO=1 is explicitly permitted when all physical iprio bytes are RO0.
    private val machine = winner(io.mCandidates)
    private val supervisor = winner(io.hsCandidates)
    io.mtopi := topi(machine._1, machine._2, 1.U(8.W))
    io.stopi := topi(supervisor._1, supervisor._2, 1.U(8.W))

    private val control = RegInit(0.U(32.W))
    when(io.commit && io.hvictlWrite.valid) {
        control := io.hvictlWrite.bits(31, 0) & "h403f03ff".U
    }
    io.hvictl := control
    io.vti := control(30)
    private val injectedIid = control(21, 16)
    private val injectedPriority = control(7, 0)
    private val priorityMode = control(8)

    // AIA v1.0 section 5.1.3.3 has three mutually exclusive external candidates.
    // Guest TOPEI priority is eleven bits, even when the exported vstopi IPRIO is eight.
    private val externalValid = io.vsip(9) && io.vsie(9)
    private val externalFromFile = io.guestFileValid && io.guestTopei =/= 0.U
    private val externalEmulated = io.vgein === 0.U && injectedIid === 9.U && injectedPriority =/= 0.U
    private val externalPriority = Mux(externalFromFile, io.guestTopei(10, 0),
        Mux(externalEmulated, injectedPriority.pad(11), 256.U(11.W)))

    // With VTI clear, RO0 hviprio selects normal pending/enabled interrupts by default
    // order. With VTI set, IID != 9 asserts the second candidate regardless of vsip/vsie.
    private val localMask = io.vsip & io.vsie & "hfffffffffffffdff".U(64.W)
    private val local = winner(localMask)
    private val otherValid = Mux(io.vti, injectedIid =/= 9.U, local._1)
    private val otherIid = Mux(io.vti, injectedIid, local._2)
    private val otherPriority = Mux(io.vti, injectedPriority, 0.U(8.W))
    private val otherAboveSei = Mux(io.vti, !control(9), (localMask & aboveSeiMask.U(64.W)).orR)
    private val otherWins = Mux(otherPriority === 0.U, otherAboveSei,
        otherPriority < externalPriority || (otherPriority === externalPriority && otherAboveSei))
    private val chooseOther = otherValid && (!externalValid || otherWins)
    private val chosenIid = Mux(chooseOther, otherIid, 9.U(6.W))
    private val otherReportedPriority = Mux(otherPriority =/= 0.U, otherPriority,
        Mux(otherAboveSei, 0.U(8.W), 255.U(8.W)))
    private val externalReportedPriority = Mux(externalPriority > 255.U, 255.U(8.W), externalPriority(7, 0))
    private val reportedPriority = Mux(!priorityMode, 1.U(8.W),
        Mux(chooseOther, otherReportedPriority, externalReportedPriority))
    io.vstopi := topi(otherValid || externalValid, chosenIid, reportedPriority)
}
