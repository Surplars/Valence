package soc.ip.tilelink

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLParams}

/** Independent 64-byte read and write queues on one TL-UH master port. The high source bit
  * separates reads from writes. Callers must wait for a write acknowledgement before relying
  * on a later read of the same address; this module does not impose cross-direction ordering.
  */
class TileLinkLineTransfer(params: TLParams = TLParams(), entries: Int = 4, tagBits: Int = 8,
    rawResponseMetadata: Boolean = false, dispatchFlow: Boolean = false,
    lineReadChannel: Boolean = false, isolatedWriteLaunch: Boolean = false, serializedWrites: Boolean = false)
    extends Module {
    require(params.sourceBits <= 6)
    require(!lineReadChannel || tagBits <= 8)
    val io = IO(new Bundle {
        val readRequest  = Flipped(Decoupled(new LineFillRequest(params.addrWidth, tagBits)))
        val readResponse = Decoupled(new LineFillResponse(tagBits))
        val writeRequest = Flipped(Decoupled(new LineWriteRequest(params.addrWidth, tagBits)))
        val writeResponse = Decoupled(new LineWriteResponse(tagBits))
        val tl = new TLBundle(params.copy(sourceBits = params.sourceBits + 1))
        val lineRead = if (lineReadChannel) Some(new LineReadMemoryPort(params.addrWidth)) else None
    })
    val writer = if (serializedWrites) Module(new TileLinkSerializedLineWriteEngine(params, tagBits))
        else Module(new TileLinkLineWriteEngine(params, entries, tagBits, dispatchFlow, isolatedWriteLaunch))
    writer.io.request <> io.writeRequest
    io.writeResponse <> writer.io.response
    if (lineReadChannel) {
        // No private duplicate read-line payload RAM: the shared memory owner
        // retains bytes/error/tag until this final response handshake.
        val line = io.lineRead.get
        line.request.valid := io.readRequest.valid
        line.request.bits.address := io.readRequest.bits.address
        line.request.bits.tag := io.readRequest.bits.tag
        io.readRequest.ready := line.request.ready
        io.readResponse.valid := line.response.valid
        io.readResponse.bits.data := line.response.bits.data
        io.readResponse.bits.error := line.response.bits.error
        io.readResponse.bits.tag := line.response.bits.tag
        line.response.ready := io.readResponse.ready
        when(line.response.valid) {
            assert(line.response.bits.tag < (BigInt(1) << tagBits).U,
                "whole-line response truncated its caller tag")
        }
        io.tl.a <> writer.io.tl.a
        io.tl.a.bits.source := Cat(1.U(1.W), writer.io.tl.a.bits.source)
        writer.io.tl.d <> io.tl.d
        writer.io.tl.d.bits.source := io.tl.d.bits.source(params.sourceBits - 1, 0)
        when(io.tl.d.valid) {
            assert(io.tl.d.bits.source(params.sourceBits), "write-only line port returned a read source")
        }
        writer.io.tl.b <> io.tl.b
        io.tl.c <> writer.io.tl.c
        io.tl.e <> writer.io.tl.e
    } else {
        val reader = Module(new TileLinkLineFillEngine(params, entries, tagBits, dispatchFlow))
        val arbiter = Module(new TwoMasterTileLinkArbiter(params, rawResponseMetadata))
        reader.io.request <> io.readRequest
        io.readResponse <> reader.io.response
        reader.io.tl <> arbiter.io.masters(0)
        writer.io.tl <> arbiter.io.masters(1)
        io.tl <> arbiter.io.manager
    }
}
