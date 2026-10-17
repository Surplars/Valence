package soc.core.ooo

import chisel3._
import soc.ip.memory.AtomicMemory

/** DataPort adapter for the independent single-hart atomic/DMA memory boundary. */
class AtomicDataMemory(
    base: BigInt = BigInt("80010000", 16),
    bytes: BigInt = 4096,
    registerResponseOwners: Boolean = false,
    dmaLineTransfers: Boolean = false,
    dmaLineEntries: Int = 1
) extends Module {
    val io = IO(new Bundle {
        val cpu              = Flipped(new DataPort)
        val dma              = Flipped(new DataPort)
        val memory           = new DataPort
        val memoryRequestCpu = Output(Bool())
        val clearReservation = Input(Bool())
        val dmaLine = if (dmaLineTransfers) Some(Flipped(new soc.ip.dma.DmaLinePort(dmaLineEntries))) else None
        val memoryLine = if (dmaLineTransfers) Some(new soc.ip.dma.DmaLinePort(dmaLineEntries)) else None
    })
    val unit = Module(new AtomicMemory(base, bytes, registerResponseOwners, dmaLineTransfers, dmaLineEntries))
    if (dmaLineTransfers) {
        unit.io.dmaLine.get <> io.dmaLine.get
        io.memoryLine.get <> unit.io.memoryLine.get
    }
    io.memoryRequestCpu := unit.io.memoryRequestCpu
    unit.io.clearReservation           := io.clearReservation
    unit.io.cpu.request.valid          := io.cpu.request.valid
    unit.io.cpu.request.bits.address   := io.cpu.request.bits.address
    unit.io.cpu.request.bits.write     := io.cpu.request.bits.write
    unit.io.cpu.request.bits.size      := io.cpu.request.bits.size
    unit.io.cpu.request.bits.data      := io.cpu.request.bits.data
    unit.io.cpu.request.bits.mask      := io.cpu.request.bits.mask
    unit.io.cpu.request.bits.atomic    := io.cpu.request.bits.atomic
    unit.io.cpu.request.bits.operation := io.cpu.request.bits.atomicOp
    io.cpu.request.ready               := unit.io.cpu.request.ready
    io.cpu.response.valid              := unit.io.cpu.response.valid
    io.cpu.response.bits.data          := unit.io.cpu.response.bits.data
    io.cpu.response.bits.error         := unit.io.cpu.response.bits.error
    io.cpu.response.bits.pageFault     := false.B
    unit.io.cpu.response.ready         := io.cpu.response.ready
    unit.io.dma.request.valid          := io.dma.request.valid
    unit.io.dma.request.bits.address   := io.dma.request.bits.address
    unit.io.dma.request.bits.write     := io.dma.request.bits.write
    unit.io.dma.request.bits.size      := io.dma.request.bits.size
    unit.io.dma.request.bits.data      := io.dma.request.bits.data
    unit.io.dma.request.bits.mask      := io.dma.request.bits.mask
    io.dma.request.ready               := unit.io.dma.request.ready
    io.dma.response.valid              := unit.io.dma.response.valid
    io.dma.response.bits.data          := unit.io.dma.response.bits.data
    io.dma.response.bits.error         := unit.io.dma.response.bits.error
    io.dma.response.bits.pageFault     := false.B
    unit.io.dma.response.ready         := io.dma.response.ready
    io.memory.request.valid            := unit.io.memory.request.valid
    io.memory.request.bits             := 0.U.asTypeOf(new DataRequest)
    io.memory.request.bits.address     := unit.io.memory.request.bits.address
    io.memory.request.bits.write       := unit.io.memory.request.bits.write
    io.memory.request.bits.size        := unit.io.memory.request.bits.size
    io.memory.request.bits.data        := unit.io.memory.request.bits.data
    io.memory.request.bits.mask        := unit.io.memory.request.bits.mask
    unit.io.memory.request.ready       := io.memory.request.ready
    unit.io.memory.response.valid      := io.memory.response.valid
    unit.io.memory.response.bits.data  := io.memory.response.bits.data
    unit.io.memory.response.bits.error := io.memory.response.bits.error
    io.memory.response.ready           := unit.io.memory.response.ready
    when(io.dma.request.valid) { assert(!io.dma.request.bits.atomic, "DMA port accepts ordinary requests only") }
}
