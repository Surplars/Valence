package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.bus.RegisterPort

/** Parallel, non-overlapping MMIO decode with one ordered response-owner FIFO.
  * Eight requests outstanding, one request/response per cycle, no request stage.
  * Register lanes are right-justified; memory/atomic requests pass through intact.
  * Responses from faster ports wait behind earlier requests to any other port.
  * bypassMemoryShift keeps external-memory payload outside local-register lane
  * placement; invalid local payload is immaterial, valid controls all consumption.
  */
class ParallelRegisterRouter(windows: Seq[(BigInt, BigInt)], capacity: Int = 8,
    bypassMemoryShift: Boolean = false) extends Module {
    require(windows.nonEmpty && capacity >= 2)
    windows.foreach { case (base, bytes) =>
        require(base >= 0 && base % 8 == 0 && bytes > 0 && bytes % 8 == 0 &&
            base + bytes <= (BigInt(1) << 64))
    }
    for (i <- windows.indices; j <- 0 until i) {
        require(windows(i)._1 + windows(i)._2 <= windows(j)._1 ||
            windows(j)._1 + windows(j)._2 <= windows(i)._1, "MMIO windows overlap")
    }
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val memory = new DataPort
        val registers = Vec(windows.size, new RegisterPort)
    })
    val owners = Module(new Queue(new Bundle {
        val port = UInt(log2Ceil(windows.size + 1).W)
        val offset = UInt(3.W)
    }, capacity, pipe = false, flow = false))
    val request = io.upstream.request.bits
    val hits = VecInit(windows.map { case (base, bytes) =>
        !request.atomic && request.address >= base.U(65.W) &&
            request.address < (base + bytes).U(65.W)
    })
    val local = hits.asUInt.orR
    val shift = Cat(request.address(2, 0), 0.U(3.W))
    io.memory.request.valid := io.upstream.request.valid && owners.io.enq.ready && !local
    io.memory.request.bits := request
    for (i <- windows.indices) {
        val port = io.registers(i)
        port.request.valid := io.upstream.request.valid && owners.io.enq.ready && hits(i)
        port.request.bits.address := request.address
        port.request.bits.write := request.write
        port.request.bits.size := request.size
        port.request.bits.data := request.data >> shift
        port.request.bits.byteEnable := request.mask >> request.address(2, 0)
    }
    io.upstream.request.ready := owners.io.enq.ready &&
        Mux(local, Mux1H(hits, io.registers.map(_.request.ready)), io.memory.request.ready)
    owners.io.enq.valid := io.upstream.request.fire
    owners.io.enq.bits.port := Mux(local,
        Mux1H(hits, windows.indices.map(i => (i + 1).U)), 0.U)
    owners.io.enq.bits.offset := request.address(2, 0)
    val selected = VecInit((0 to windows.size).map(i => owners.io.deq.bits.port === i.U))
    val valid = Mux1H(selected, io.memory.response.valid +: io.registers.map(_.response.valid))
    val data = Mux1H(selected, io.memory.response.bits.data +: io.registers.map(_.response.bits.data))
    val error = Mux1H(selected, io.memory.response.bits.error +: io.registers.map(_.response.bits.error))
    val responseShift = Mux(owners.io.deq.valid && !selected(0),
        Cat(owners.io.deq.bits.offset, 0.U(3.W)), 0.U(6.W))
    io.upstream.response.valid := owners.io.deq.valid && valid
    io.upstream.response.bits.data := (if (bypassMemoryShift) {
        val localData = Mux1H(selected.tail, io.registers.map(_.response.bits.data))
        val localShift = Cat(owners.io.deq.bits.offset, 0.U(3.W))
        // Invalid owner RAM payload is unconstrained in the simulation model.
        // Fixed shifts keep that unused payload defined without feeding valid
        // back into data, and retain every legal byte offset exactly.
        val placedLocal = MuxLookup(localShift, 0.U(64.W))((0 until 8).map(i =>
            (i * 8).U -> (localData << (i * 8))(63, 0)))
        Mux(selected(0), io.memory.response.bits.data, placedLocal)
    } else (data << responseShift)(63, 0))
    io.upstream.response.bits.error := error
    io.upstream.response.bits.pageFault := selected(0) && io.memory.response.bits.pageFault
    io.memory.response.ready := owners.io.deq.valid && selected(0) && io.upstream.response.ready
    for (i <- windows.indices) {
        io.registers(i).response.ready := owners.io.deq.valid && selected(i + 1) && io.upstream.response.ready
    }
    owners.io.deq.ready := io.upstream.response.fire
}
