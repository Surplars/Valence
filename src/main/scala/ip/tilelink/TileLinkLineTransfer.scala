package soc.ip.tilelink

import chisel3._
import chisel3.util._
import soc.bus.tilelink.{TLBundle, TLParams}

/** Independent 64-byte read and write queues on one TL-UH master port. The high source bit
  * separates reads from writes. Callers must wait for a write acknowledgement before relying
  * on a later read of the same address; this module does not impose cross-direction ordering.
  */
class TileLinkLineTransfer(params: TLParams = TLParams(), entries: Int = 4, tagBits: Int = 8,
    rawResponseMetadata: Boolean = false)
    extends Module {
    require(params.sourceBits <= 6)
    val io = IO(new Bundle {
        val readRequest  = Flipped(Decoupled(new LineFillRequest(params.addrWidth, tagBits)))
        val readResponse = Decoupled(new LineFillResponse(tagBits))
        val writeRequest = Flipped(Decoupled(new LineWriteRequest(params.addrWidth, tagBits)))
        val writeResponse = Decoupled(new LineWriteResponse(tagBits))
        val tl = new TLBundle(params.copy(sourceBits = params.sourceBits + 1))
    })
    val reader = Module(new TileLinkLineFillEngine(params, entries, tagBits))
    val writer = Module(new TileLinkLineWriteEngine(params, entries, tagBits))
    val arbiter = Module(new TwoMasterTileLinkArbiter(params, rawResponseMetadata))
    reader.io.request <> io.readRequest
    io.readResponse <> reader.io.response
    writer.io.request <> io.writeRequest
    io.writeResponse <> writer.io.response
    reader.io.tl <> arbiter.io.masters(0)
    writer.io.tl <> arbiter.io.masters(1)
    io.tl <> arbiter.io.manager
}
