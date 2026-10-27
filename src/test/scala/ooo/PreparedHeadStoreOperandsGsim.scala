package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

class PreparedHeadStoreProbe extends Bundle {
    val valid = Bool()
    val index = UInt(4.W)
    val tag = UInt(64.W)
    val address = UInt(64.W)
    val data = UInt(64.W)
    val size = UInt(2.W)
}

/** Two token shapes in one tiny model; all observed payload comes from the production row. */
class PreparedHeadStoreOperandsGsim extends Module {
    val io = IO(new Bundle {
        val candidateValid = Input(Bool())
        val candidateIndex = Input(UInt(4.W))
        val candidateTag = Input(UInt(64.W))
        val candidateAddress = Input(UInt(64.W))
        val candidateData = Input(UInt(64.W))
        val candidateSize = Input(UInt(2.W))
        val ownerLive = Input(Bool())
        val atHead = Input(Bool())
        val flush = Input(Bool())
        val consumeValid = Input(Bool())
        val consumeIndex = Input(UInt(4.W))
        val consumeTag = Input(UInt(64.W))
        val standard = Output(new PreparedHeadStoreProbe)
        val compact = Output(new PreparedHeadStoreProbe)
    })
    for ((output, entries, tags) <- Seq((io.standard, 16, 64), (io.compact, 8, 9))) {
        val p = OooParams(robEntries = entries, physicalRegs = 48, tagBits = tags)
        val row = Module(new PreparedHeadStoreOperands(p))
        row.io.candidate.valid := io.candidateValid
        row.io.candidate.bits.token.index := io.candidateIndex
        row.io.candidate.bits.token.tag := io.candidateTag
        row.io.candidate.bits.address := io.candidateAddress
        row.io.candidate.bits.data := io.candidateData
        row.io.candidate.bits.size := io.candidateSize
        row.io.ownerLive := io.ownerLive
        row.io.atHead := io.atHead
        row.io.flush := io.flush
        row.io.consume.valid := io.consumeValid
        row.io.consume.bits.index := io.consumeIndex
        row.io.consume.bits.tag := io.consumeTag
        output.valid := row.io.prepared.valid
        output.index := row.io.prepared.bits.token.index
        output.tag := row.io.prepared.bits.token.tag
        output.address := row.io.prepared.bits.address
        output.data := row.io.prepared.bits.data
        output.size := row.io.prepared.bits.size
    }
}

object PreparedHeadStoreOperandsGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PreparedHeadStoreOperandsGsim, Array("--target-dir", args.head))
}
