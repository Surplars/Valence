package soc.core.ooo

import chisel3._
import chisel3.util._

/** Four combinational operand read ports for the two ranked issue owners.
  * Decode each queued source ID in parallel, then select physical values directly
  * with one-hot masks in legacy mode. The opt-in owner-banked PRF instead
  * selects narrow source IDs and uses external asynchronous RAM read ports.
  * No state/backpressure/cycle; empty owner has a defined zero payload. Actual
  * issue/grant/kill authorization remains in the backend. No late preview bypass.
  * Decoder/read fanout and area are physical-design costs, not assumed free.
  */
class IssuePhysicalOperands(p: OooParams, sharedSourceDecode: Boolean = false) extends Module {
    require(p.completionWidth == 2)
    val io = IO(new Bundle {
        val owners = Input(Vec(2, UInt(p.robEntries.W)))
        val source1 = Input(Vec(p.robEntries, UInt(p.physBits.W)))
        val source2 = Input(Vec(p.robEntries, UInt(p.physBits.W)))
        // Only the pure queued-source equality masks may be shared. Each
        // consumer still owns two independent early owner masks and four
        // physical value reads; no grant, ready, kill or value enters decode.
        val decoded1 = if (sharedSourceDecode)
            Some(Input(Vec(p.physicalRegs, UInt(p.robEntries.W)))) else None
        val decoded2 = if (sharedSourceDecode)
            Some(Input(Vec(p.physicalRegs, UInt(p.robEntries.W)))) else None
        val values = Input(Vec(p.physicalRegs, UInt(64.W)))
        val readAddress = if (p.lvtPhysicalRegisterFile) Some(Output(Vec(4, UInt(p.physBits.W)))) else None
        val readData = if (p.lvtPhysicalRegisterFile) Some(Input(Vec(4, UInt(64.W)))) else None
        val left = Output(Vec(2, UInt(64.W)))
        val right = Output(Vec(2, UInt(64.W)))
    })
    val decode1 = if (p.lvtPhysicalRegisterFile) Seq.empty[UInt] else io.decoded1.map(_.toSeq).getOrElse(
        (0 until p.physicalRegs).map(r => VecInit(io.source1.map(_ === r.U)).asUInt))
    val decode2 = if (p.lvtPhysicalRegisterFile) Seq.empty[UInt] else io.decoded2.map(_.toSeq).getOrElse(
        (0 until p.physicalRegs).map(r => VecInit(io.source2.map(_ === r.U)).asUInt))
    def read(owner: UInt, decoded: Seq[UInt], source: Vec[UInt], port: Int): UInt = {
        if (p.lvtPhysicalRegisterFile) {
            // Real address port: encoding and RAM/LVT delay replace the wide OR.
            io.readAddress.get(port) := CircularIssueSelector.selectPayload(owner, source.toSeq)
            Mux(owner.orR, io.readData.get(port), 0.U)
        } else {
            val physicalMask = VecInit(decoded.map(mask => (mask & owner).orR)).asUInt
            CircularIssueSelector.selectPayload(physicalMask, io.values.toSeq)
        }
    }
    for (lane <- 0 until 2) {
        io.left(lane) := read(io.owners(lane), decode1, io.source1, 2 * lane)
        io.right(lane) := read(io.owners(lane), decode2, io.source2, 2 * lane + 1)
        assert(PopCount(io.owners(lane)) <= 1.U, "physical operands require a one-hot issue owner")
        for (slot <- 0 until p.robEntries) {
            when(io.owners(lane)(slot)) {
                assert(io.source1(slot) < p.physicalRegs.U && io.source2(slot) < p.physicalRegs.U,
                    "selected issue owner must contain valid physical source IDs")
            }
        }
    }
}
