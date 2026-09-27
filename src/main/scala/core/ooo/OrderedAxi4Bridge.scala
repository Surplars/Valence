package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.axi._

/** Ordered DataPort to single-beat AXI4 baseline. Read and write cohorts pipeline separately.
  * The downstream memory window must guarantee successful writes, as buffered stores can retire before BRESP.
  */
class OrderedAxi4Bridge(
    maxReads: Int = 8,
    maxWrites: Int = 4,
    addressWidth: Int = 64,
    idWidth: Int = 1
) extends Module {
    require(maxReads >= 1 && maxReads <= 16 && maxWrites >= 1 && maxWrites <= 16)
    val io = IO(new Bundle {
        val data = Flipped(new DataPort)
        val axi  = new Axi4MemoryPort(addressWidth, idWidth)
    })
    val reads = RegInit(0.U(log2Ceil(maxReads + 1).W))
    // AW and W advance independently; writeCount only falls when their ordered B is consumed.
    val writeCount = RegInit(0.U(log2Ceil(maxWrites + 1).W))
    val awUnsent = RegInit(0.U(log2Ceil(maxWrites + 1).W))
    val wUnsent = RegInit(0.U(log2Ceil(maxWrites + 1).W))
    val writeIndexBits = math.max(1, log2Ceil(maxWrites))
    val writeTail = RegInit(0.U(writeIndexBits.W))
    val awHead = RegInit(0.U(writeIndexBits.W))
    val wHead = RegInit(0.U(writeIndexBits.W))
    val writeRequests = Reg(Vec(maxWrites, new DataRequest))
    def advance(index: UInt): UInt = Mux(index === (maxWrites - 1).U, 0.U, index + 1.U)
    val incoming = io.data.request.bits
    val canRead = writeCount === 0.U && reads < maxReads.U
    val canWrite = reads === 0.U && writeCount < maxWrites.U

    io.axi.ar.valid := io.data.request.valid && !incoming.write && canRead
    io.axi.ar.bits  := 0.U.asTypeOf(io.axi.ar.bits)
    io.axi.ar.bits.id    := 0.U
    io.axi.ar.bits.addr  := incoming.address(addressWidth - 1, 0)
    io.axi.ar.bits.len   := 0.U
    io.axi.ar.bits.size  := incoming.size
    io.axi.ar.bits.burst := 1.U // INCR, one beat
    io.data.request.ready := Mux(incoming.write, canWrite, canRead && io.axi.ar.ready)
    when(io.data.request.fire) {
        assert(!incoming.atomic, "AXI memory bridge accepts ordinary requests only")
        val bytes = 1.U(4.W) << incoming.size
        val lanes = ((255.U(8.W) >> (8.U - bytes)) << incoming.address(2, 0))(7, 0)
        assert((incoming.address(2, 0) & (bytes - 1.U)) === 0.U && incoming.mask === lanes,
            "AXI memory request must be aligned and have exact byte strobes")
        if (addressWidth < 64) {
            assert(incoming.address(63, addressWidth) === 0.U, "AXI address truncation")
        }
        when(incoming.write) {
            writeRequests(writeTail) := incoming
            writeTail := advance(writeTail)
        }
    }
    io.axi.aw.valid := awUnsent =/= 0.U
    io.axi.aw.bits  := 0.U.asTypeOf(io.axi.aw.bits)
    io.axi.aw.bits.id    := 0.U
    io.axi.aw.bits.addr  := writeRequests(awHead).address(addressWidth - 1, 0)
    io.axi.aw.bits.len   := 0.U
    io.axi.aw.bits.size  := writeRequests(awHead).size
    io.axi.aw.bits.burst := 1.U
    io.axi.w.valid := wUnsent =/= 0.U
    io.axi.w.bits.data := writeRequests(wHead).data
    io.axi.w.bits.strb := writeRequests(wHead).mask
    io.axi.w.bits.last := true.B
    when(io.axi.aw.fire) { awHead := advance(awHead) }
    when(io.axi.w.fire) { wHead := advance(wHead) }

    val writeReply = writeCount > awUnsent && writeCount > wUnsent
    io.axi.b.ready := writeReply && io.data.response.ready
    io.axi.r.ready := reads =/= 0.U && io.data.response.ready
    io.data.response.valid := Mux(writeCount =/= 0.U, writeReply && io.axi.b.valid,
        reads =/= 0.U && io.axi.r.valid)
    io.data.response.bits.data := Mux(writeCount =/= 0.U, 0.U, io.axi.r.bits.data)
    io.data.response.bits.error := writeCount === 0.U && io.axi.r.bits.resp(1)
    io.data.response.bits.pageFault := false.B
    when(io.axi.b.fire) {
        assert(io.axi.b.bits.id === 0.U, "AXI write response ID mismatch")
        assert(!io.axi.b.bits.resp(1), "AXI memory window must guarantee successful writes")
    }
    when(io.axi.r.fire) {
        assert(io.axi.r.bits.id === 0.U && io.axi.r.bits.last, "AXI read response ID or RLAST mismatch")
    }
    when(io.axi.ar.fire =/= io.axi.r.fire) {
        reads := Mux(io.axi.ar.fire, reads + 1.U, reads - 1.U)
    }
    val writeRequestFire = io.data.request.fire && incoming.write
    when(writeRequestFire =/= io.axi.b.fire) {
        writeCount := Mux(writeRequestFire, writeCount + 1.U, writeCount - 1.U)
    }
    when(writeRequestFire =/= io.axi.aw.fire) {
        awUnsent := Mux(writeRequestFire, awUnsent + 1.U, awUnsent - 1.U)
    }
    when(writeRequestFire =/= io.axi.w.fire) {
        wUnsent := Mux(writeRequestFire, wUnsent + 1.U, wUnsent - 1.U)
    }
    assert(reads <= maxReads.U)
    assert(writeCount <= maxWrites.U && awUnsent <= writeCount && wUnsent <= writeCount)
    assert(reads === 0.U || writeCount === 0.U)
}
