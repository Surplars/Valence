package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.bus.RegisterPort

/** Parallel, non-overlapping MMIO decode with an ordered response-owner FIFO by default.
  * Eight requests outstanding, one request/response per cycle, no request stage.
  * Register lanes are right-justified; memory/atomic requests pass through intact.
  * With CPU return handles, memory replies select exact owners; ID-less local CSR requests use drained exclusive intervals.
  * bypassMemoryShift keeps external-memory payload outside local-register lane
  * placement; invalid local payload is immaterial, valid controls all consumption.
  */
class ParallelRegisterRouter(windows: Seq[(BigInt, BigInt)], capacity: Int = 8,
    bypassMemoryShift: Boolean = false, returnConfig: Option[CpuReturnConfig] = None) extends Module {
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
        val upstream = Flipped(new DataPort(returnConfig.map(_.handleBits).getOrElse(0)))
        val memory = new DataPort(returnConfig.map(_.handleBits).getOrElse(0))
        val registers = Vec(windows.size, new RegisterPort)
    })
    class RouteOwner extends Bundle {
        val port = UInt(log2Ceil(windows.size + 1).W)
        val offset = UInt(3.W)
    }
    val owners = CpuReturnTransport.ownerView(new RouteOwner, capacity)
    val request = io.upstream.request.bits
    val hits = VecInit(windows.map { case (base, bytes) =>
        !request.atomic && request.address >= base.U(65.W) &&
            request.address < (base + bytes).U(65.W)
    })
    val local = hits.asUInt.orR
    returnConfig match {
        case None => CpuReturnTransport.orderedOwners(owners, new RouteOwner, capacity, flow = false)
        case Some(config) =>
            val live = RegInit(VecInit(Seq.fill(config.tableEntries)(false.B)))
            val routes = Reg(Vec(config.tableEntries, new RouteOwner))
            val localHandle = Reg(UInt(config.handleBits.W))
            val localLive = VecInit((0 until config.tableEntries).map(i =>
                live(i) && routes(i).port =/= 0.U)).asUInt.orR
            val requestHandle = request.returnHandle.get
            val memoryHandle = io.memory.response.bits.returnHandle.get
            val responseHandle = Mux(localLive, localHandle, memoryHandle)
            val count = PopCount(live)
            // Local ID-less CSR ports occupy an exclusive drained interval.
            owners.io.enq.ready := config.legal(requestHandle) && !live(requestHandle) &&
                count < capacity.U && !localLive && (!local || count === 0.U)
            owners.io.deq.valid := live(responseHandle)
            owners.io.deq.bits := routes(responseHandle)
            owners.io.count := count
            io.upstream.response.bits.returnHandle.get := responseHandle
            when(owners.io.enq.fire) {
                live(requestHandle) := true.B
                routes(requestHandle) := owners.io.enq.bits
                when(local) { localHandle := requestHandle }
            }
            when(owners.io.deq.fire) { live(responseHandle) := false.B }
            when(io.memory.response.valid) {
                val entering = io.memory.request.fire && memoryHandle === io.memory.request.bits.returnHandle.get
                assert(!localLive && config.legal(memoryHandle) &&
                    ((live(memoryHandle) && routes(memoryHandle).port === 0.U) || entering),
                    "router memory return lost its exact owner")
            }
            when(localLive) { assert(count === 1.U && !io.upstream.request.fire) }
            assert(count <= capacity.U)
            CpuReturnTransport.held(io.upstream.response)
    }
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
