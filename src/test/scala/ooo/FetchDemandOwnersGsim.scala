package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

class FetchDemandOwnersGsim extends Module {
    val io = IO(new Bundle {
        val candidate = Input(Bool())
        val base = Input(UInt(64.W))
        val context = Input(UInt(3.W))
        val mask = Input(UInt(2.W))
        val requestReady = Input(Bool())
        val response = Input(Bool())
        val invalidate = Input(Bool())
        val query0 = Input(UInt(64.W))
        val query1 = Input(UInt(64.W))
        val queryContext = Input(UInt(3.W))
        val requestValid = Output(Bool())
        val requestBase = Output(UInt(64.W))
        val requestContext = Output(UInt(3.W))
        val requestMask = Output(UInt(2.W))
        val headValid = Output(Bool())
        val headBase = Output(UInt(64.W))
        val headPlus = Output(UInt(64.W))
        val headMinus = Output(UInt(64.W))
        val headContext = Output(UInt(3.W))
        val headStale = Output(Bool())
        val owned = Output(UInt(2.W))
        val credit = Output(Bool())
        val held = Output(Bool())
        val idle = Output(Bool())
    })
    val owners = Module(new FetchDemandOwners)
    owners.io.candidate.valid := io.candidate
    owners.io.candidate.bits.base := io.base
    owners.io.candidate.bits.context := io.context
    owners.io.candidate.bits.mask := io.mask
    owners.io.request.ready := io.requestReady
    owners.io.response := io.response
    owners.io.invalidate := io.invalidate
    owners.io.queryBase(0) := io.query0
    owners.io.queryBase(1) := io.query1
    owners.io.queryContext := io.queryContext
    io.requestValid := owners.io.request.valid
    io.requestBase := owners.io.request.bits.base
    io.requestContext := owners.io.request.bits.context
    io.requestMask := owners.io.request.bits.mask
    io.headValid := owners.io.headValid
    io.headBase := owners.io.head.base
    io.headPlus := owners.io.head.plusEight
    io.headMinus := owners.io.head.minus(2)
    io.headContext := owners.io.head.context
    io.headStale := owners.io.head.stale
    io.owned := owners.io.owned.asUInt
    io.credit := owners.io.credit
    io.held := owners.io.held
    io.idle := owners.io.quiescent
}
object FetchDemandOwnersGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FetchDemandOwnersGsim, Array("--target-dir", args.head))
}
