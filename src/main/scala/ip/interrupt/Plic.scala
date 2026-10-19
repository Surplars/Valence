package soc.ip.interrupt

import chisel3._
import chisel3.util._
import soc.ip.bus.RegisterPort

/** PLIC 1.0, level gateways; inputs already belong to this clock domain.
  * One 32-bit MMIO owner, one-cycle response, held under backpressure. Balanced priority tournament;
  * small control state uses registers, not reset payload RAM. Source zero is permanently absent.
  * Claim ignores threshold; completion checks current enable, NOT the most recent claim ID.
  */
class Plic(sources: Int = 8, contexts: Int = 1, priorityBits: Int = 3,
    base: BigInt = BigInt("0c000000", 16)) extends Module {
    require(sources >= 1 && sources <= 1023 && contexts >= 1 && contexts <= 16)
    require(priorityBits >= 1 && priorityBits <= 7 && base >= 0 && base % 4096 == 0)
    val io = IO(new Bundle {
        val mmio = Flipped(new RegisterPort)
        val levels = Input(Vec(sources + 1, Bool()))
        val irq = Output(Vec(contexts, Bool()))
    })
    val priorities = RegInit(VecInit(Seq.fill(sources + 1)(0.U(priorityBits.W))))
    val pending = RegInit(VecInit(Seq.fill(sources + 1)(false.B)))
    val blocked = RegInit(VecInit(Seq.fill(sources + 1)(false.B)))
    val enables = RegInit(VecInit(Seq.fill(contexts)(VecInit(Seq.fill(sources + 1)(false.B)))))
    val thresholds = RegInit(VecInit(Seq.fill(contexts)(0.U(priorityBits.W))))
    val idBits = log2Ceil(sources + 1).max(1)
    val winners = (0 until contexts).map { c =>
        var candidates: Seq[(UInt, UInt)] = (1 to sources).map { s =>
            val eligible = pending(s) && enables(c)(s) && priorities(s) =/= 0.U
            (Mux(eligible, priorities(s), 0.U), Mux(eligible, s.U(idBits.W), 0.U(idBits.W)))
        }
        while (candidates.size > 1) {
            candidates = candidates.grouped(2).map { pair =>
                if (pair.size == 1) pair.head else {
                    val (lp, li) = pair.head; val (rp, ri) = pair(1)
                    val left = lp > rp || (lp === rp && li <= ri)
                    (Mux(left, lp, rp), Mux(left, li, ri))
                }
            }.toSeq
        }
        val (priority, id) = candidates.head
        // Notification is presence above threshold, NOT the claim winner.
        // Keep the priority/lowest-ID tournament for MMIO claim, but do not
        // put that tournament before every live mip/sip read and IRQ snapshot.
        val notify = (1 to sources).map(s =>
            pending(s) && enables(c)(s) && priorities(s) > thresholds(c)).reduce(_ || _)
        io.irq(c) := notify
        assert(notify === (priority > thresholds(c)), "PLIC IRQ presence differs from thresholded maximum")
        id
    }
    val valid = RegInit(false.B)
    val data = Reg(UInt(64.W)); val error = Reg(Bool())
    io.mmio.request.ready := !valid
    io.mmio.response.valid := valid
    io.mmio.response.bits.data := data; io.mmio.response.bits.error := error
    when(io.mmio.response.fire) { valid := false.B }
    val r = io.mmio.request.bits
    val offset = r.address - base.U
    val geometry = r.address >= base.U && r.address < (base + 0x4000000).U &&
        r.address(1, 0) === 0.U && r.size === 2.U && r.byteEnable === 15.U
    val known = WireDefault(false.B)
    val value = WireDefault(0.U(64.W))
    val claim = Wire(Vec(sources + 1, Bool()))
    val complete = Wire(Vec(sources + 1, Bool()))
    claim.foreach(_ := false.B); complete.foreach(_ := false.B)
    val effect = io.mmio.request.fire && geometry
    for (s <- 0 to sources) {
        when(offset === (4 * s).U) {
            known := true.B; value := priorities(s)
            if (s != 0) when(effect && r.write) { priorities(s) := r.data(priorityBits - 1, 0) }
        }
    }
    val words = (sources + 32) / 32
    for (w <- 0 until words) {
        val ids = (32 * w until math.min(sources + 1, 32 * (w + 1)))
        when(offset === (0x1000 + 4 * w).U) {
            known := !r.write; value := VecInit(ids.map(s => pending(s))).asUInt
        }
        for (c <- 0 until contexts) when(offset === (0x2000 + c * 0x80 + 4 * w).U) {
            known := true.B; value := VecInit(ids.map(s => enables(c)(s))).asUInt
            for (s <- ids if s != 0) when(effect && r.write) { enables(c)(s) := r.data(s % 32) }
        }
    }
    for (c <- 0 until contexts) {
        when(offset === (0x200000 + c * 0x1000).U) {
            known := true.B; value := thresholds(c)
            when(effect && r.write) { thresholds(c) := r.data(priorityBits - 1, 0) }
        }
        when(offset === (0x200004 + c * 0x1000).U) {
            known := true.B; value := winners(c)
            for (s <- 1 to sources) {
                when(effect && !r.write && winners(c) === s.U) { claim(s) := true.B }
                when(effect && r.write && r.data(31, 0) === s.U && enables(c)(s)) { complete(s) := true.B }
            }
        }
    }
    for (s <- 1 to sources) {
        when(!blocked(s) && !pending(s) && io.levels(s)) { pending(s) := true.B; blocked(s) := true.B }
        when(claim(s)) { pending(s) := false.B }
        when(complete(s)) { blocked(s) := false.B }
    }
    when(io.mmio.request.fire) {
        valid := true.B; data := Mux(geometry && known, value, 0.U); error := !(geometry && known)
    }
    assert(!pending(0) && !blocked(0) && priorities(0) === 0.U, "PLIC source zero is reserved")
}
