package soc.core.ooo

import chisel3._
import chisel3.util._

/** One naturally aligned eight-byte cache packet, including both word faults. */
class FetchWindowPacket extends Bundle {
    val data = UInt(64.W)
    val accessFaults = UInt(2.W)
    val pageFaults = UInt(2.W)
}

/** Registered cache window, not an outstanding memory-request queue.
  *
  * Input row i belongs to queryBase + 8*i in queryContext. All rows and their
  * context are captured together on every edge, with minimum latency one.
  * Output row i names readBase + 8*i in readContext. A changed cursor may reuse
  * an overlapping captured window; it must never receive a packet at another
  * address or from another context. Missing rows are invalid, not zero-fill hits.
  *
  * Three stored rows cover consecutive two-wide 16/32-bit supply while cached;
  * five permit the equivalent four-wide overlap. Cache/memory scheduling and
  * architectural PMP authorization remain outside this snapshot boundary.
  * Invalidation kills validity now and at the next edge, but does not enter the
  * payload mux. There is no combinational cache-data path to the output.
  * Capacity, latency and II are structural targets, not measured FPGA timing.
  */
class RegisteredFetchWindow(val capacity: Int, val outputPackets: Int = 3) extends Module {
    require(capacity >= outputPackets && capacity <= 5)
    require(outputPackets >= 1 && outputPackets <= 3)
    val io = IO(new Bundle {
        val queryBase = Input(UInt(64.W))
        val queryContext = Input(UInt(3.W))
        val query = Input(Vec(capacity, Valid(new FetchWindowPacket)))
        val readBase = Input(UInt(64.W))
        val readContext = Input(UInt(3.W))
        val invalidate = Input(Bool())
        val packets = Output(Vec(outputPackets, Valid(new FetchWindowPacket)))
    })
    val contents = Reg(Vec(capacity, new FetchWindowPacket))
    val present = RegInit(VecInit(Seq.fill(capacity)(false.B)))
    val context = Reg(UInt(3.W))
    // Pre-shift keys at capture: the read cursor never launches an XLEN adder
    // before the packet match. Equality retains all bits and wraps modulo XLEN.
    private val firstStep = -(outputPackets - 1)
    // At most seven packet keys straddle three adjacent 64-byte regions.
    // Share their full high-address comparisons instead of replicating XLEN
    // equality for every row/output pair. Region tags still wrap modulo XLEN.
    val regions = Reg(Vec(3, UInt(58.W)))
    regions(0) := io.queryBase(63, 6) - 1.U
    regions(1) := io.queryBase(63, 6)
    regions(2) := io.queryBase(63, 6) + 1.U
    val offsets = Reg(Vec(capacity + outputPackets - 1, UInt(3.W)))
    val regionIds = Reg(Vec(offsets.length, UInt(2.W)))
    for (key <- 0 until offsets.length) {
        val step = firstStep + key
        val biased = io.queryBase(5, 3) +& (step + 8).U(4.W)
        offsets(key) := biased(2, 0)
        regionIds(key) := Mux(biased < 8.U, 0.U, Mux(biased < 16.U, 1.U, 2.U))
    }
    context := io.queryContext
    for (row <- 0 until capacity) {
        contents(row) := io.query(row).bits
        present(row) := io.query(row).valid && !io.invalidate
    }
    val sameContext = context === io.readContext
    val regionMatches = VecInit(regions.map(_ === io.readBase(63, 6)))
    val keyMatches = VecInit((0 until offsets.length).map { key =>
        val highMatch = (0 until 3).map(r => regionIds(key) === r.U && regionMatches(r)).reduce(_ || _)
        sameContext && highMatch && offsets(key) === io.readBase(5, 3)
    })
    for (packet <- 0 until outputPackets) {
        val matches = (0 until capacity).map { row =>
            keyMatches(row - packet - firstStep)
        }
        io.packets(packet).valid := !io.invalidate &&
            (0 until capacity).map(row => matches(row) && present(row)).reduce(_ || _)
        io.packets(packet).bits := Mux1H(
            (0 until capacity).map(row => matches(row) -> contents(row)))
        // Uninitialized keys after reset are harmless while every row is empty.
        assert(PopCount((0 until capacity).map(row => matches(row) && present(row))) <= 1.U,
            "registered fetch window cannot alias distinct packet addresses")
    }
    assert(io.queryBase(2, 0) === 0.U, "fetch-window query must be packet aligned")
    assert(io.readBase(2, 0) === 0.U, "fetch-window read must be packet aligned")
}
