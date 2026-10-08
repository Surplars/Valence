package soc.core.ooo

import chisel3._
import chisel3.util._

/** Raw supply authorization before the existing reservoir capture edge.
  * Combinational, width instructions/cycle; no extra stage or credit. Each
  * four-byte execute check retains the historical XLEN wrap/first-overlap rule,
  * even for a compressed instruction. Virtual fetch is authorized by the
  * existing physical translation adapter, not by PMP on the virtual cursor.
  * The consumer must invalidate all captured permissions after a context/PMP
  * change. The ROB-head PMP/SATP/xRET barriers and every trap redirect already
  * discard younger reservoir entries before they can retire in a new context.
  */
class FetchPacketPermission(entries: Int, width: Int, wordSpan: Boolean, balanced: Boolean,
    sharedRelations: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val base = Input(UInt(64.W))
        val state = Input(new PmpState)
        val privilege = Input(UInt(2.W))
        val virtualized = Input(Bool())
        val instructionLow = Input(Vec(width, UInt(2.W)))
        val denied = Output(Vec(width, Bool()))
        val addresses = Output(Vec(width, UInt(64.W)))
    })
    val checks = Module(new PacketFetchPmp(entries, width, wordSpan, balanced, sharedRelations))
    checks.io.base := io.base
    checks.io.state := io.state
    checks.io.privilege := io.privilege
    val offsets = Wire(Vec(width, UInt(log2Ceil(2 * width + 1).W)))
    val addresses = (0 until 2 * width - 1).map(offset => offset.U -> (io.base + (2 * offset).U))
    for (lane <- 0 until width) {
        offsets(lane) := (if (lane == 0) 0.U else
            offsets(lane - 1) + Mux(io.instructionLow(lane - 1) === 3.U, 2.U, 1.U))
        io.denied(lane) := !io.virtualized && MuxLookup(offsets(lane), checks.io.denied(0))(
            checks.io.denied.zipWithIndex.map { case (denied, offset) => offset.U -> denied })
        io.addresses(lane) := MuxLookup(offsets(lane), io.base)(addresses)
    }
}
