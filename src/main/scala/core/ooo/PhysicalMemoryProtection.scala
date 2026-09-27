package soc.core.ooo

import chisel3._
import chisel3.util._

/** RV64 PMP state: 16 entries, 56-bit physical addresses and four-byte minimum granularity. */
class PmpState extends Bundle {
    val cfg  = Vec(16, UInt(8.W))
    val addr = Vec(16, UInt(54.W))
}

object PmpAccess {
    val read      = 0.U(2.W)
    val write     = 1.U(2.W)
    val execute   = 2.U(2.W)
    val readWrite = 3.U(2.W)
}

/** Parallel range comparison followed by a priority encoder; no serial sixteen-entry decision chain.
  * A matching entry is the first one overlapping any byte, and must cover every byte.
  */
class PmpChecker(entries: Int = 16) extends Module {
    require(Set(0, 8, 16).contains(entries))
    val io = IO(new Bundle {
        val state     = Input(new PmpState)
        val address   = Input(UInt(64.W))
        val size      = Input(UInt(3.W))
        val privilege = Input(UInt(2.W))
        val access    = Input(UInt(2.W))
        val denied    = Output(Bool())
    })
    if (entries == 0) {
        io.denied := false.B
    } else {
        val start = Cat(0.U(1.W), io.address)
        val end   = start + (1.U(65.W) << io.size) - 1.U
        val overlap = Wire(Vec(entries, Bool()))
        val covers  = Wire(Vec(entries, Bool()))
        val allowed = Wire(Vec(entries, Bool()))
        for (i <- 0 until entries) {
            val cfg  = io.state.cfg(i)
            val mode = cfg(4, 3)
            val top  = Cat(0.U(9.W), io.state.addr(i), 0.U(2.W))
            val low  = if (i == 0) 0.U(65.W) else Cat(0.U(9.W), io.state.addr(i - 1), 0.U(2.W))
            val napotAddress = Cat(0.U(1.W), io.state.addr(i))
            val napotMask = (((napotAddress ^ (napotAddress + 1.U)) << 2) | 3.U)(55, 0)
            val napotBase = Cat(io.state.addr(i), 0.U(2.W)) & ~napotMask
            val regionLow = Mux(mode === 1.U, low,
                Mux(mode === 2.U, top, Cat(0.U(9.W), napotBase)))
            val regionEnd = Mux(mode === 1.U, top - 1.U,
                Mux(mode === 2.U, top + 3.U, Cat(0.U(9.W), napotBase | napotMask)))
            val nonempty = mode =/= 0.U && (mode =/= 1.U || top > low)
            overlap(i) := nonempty && start <= regionEnd && end >= regionLow
            covers(i)  := start >= regionLow && end <= regionEnd
            val permission = MuxLookup(io.access, false.B)(Seq(
                PmpAccess.read      -> cfg(0),
                PmpAccess.write     -> cfg(1),
                PmpAccess.execute   -> cfg(2),
                PmpAccess.readWrite -> (cfg(0) && cfg(1))
            ))
            allowed(i) := io.privilege === 3.U && !cfg(7) || permission
        }
        val hit = overlap.asUInt.orR
        val selected = PriorityEncoder(overlap)
        io.denied := Mux(hit, !covers(selected) || !allowed(selected), io.privilege =/= 3.U)
    }
}
