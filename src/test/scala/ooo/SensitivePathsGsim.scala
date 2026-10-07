package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util.Cat
import soc.core.ooo._

object PredictionSourceGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PredictionSourceQualification, Array("--target-dir", args.head))
}
object InstructionRequestGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new InstructionRequestGsim(args.lift(1).map(_.toInt).getOrElse(2), args.drop(2).contains("flow-through"), args.drop(2).contains("independent-capture")),
        Array("--target-dir", args.head))
}

class InstructionRequestGsim(words: Int, flowThrough: Boolean = false, independentCapture: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val requestValid = Input(Bool())
        val requestAddress = Input(UInt(64.W))
        val requestMask = Input(UInt(words.W))
        val requestReady = Output(Bool())
        val downstreamReady = Input(Bool())
        val downstreamValid = Output(Bool())
        val downstreamAddress = Output(UInt(64.W))
        val downstreamMask = Output(UInt(words.W))
        val responseReady = Input(Bool())
        val responseValid = Input(Bool())
        val responseLow = Input(UInt(64.W))
        val responseHigh = Input(UInt(64.W))
        val responseError = Input(UInt(words.W))
        val responsePageFault = Input(UInt(words.W))
        val downstreamResponseReady = Output(Bool())
        val upstreamResponseValid = Output(Bool())
        val upstreamResponseLow = Output(UInt(64.W))
        val upstreamResponseHigh = Output(UInt(64.W))
        val upstreamResponseError = Output(UInt(words.W))
        val upstreamResponsePageFault = Output(UInt(words.W))
    })
    val requests = Module(new InstructionRequestBuffer(words, flowThrough, independentCapture))
    requests.io.upstream.request.valid := io.requestValid
    requests.io.upstream.request.bits := io.requestAddress
    requests.io.upstream.requestMask := io.requestMask
    io.requestReady := requests.io.upstream.request.ready
    requests.io.downstream.request.ready := io.downstreamReady
    io.downstreamValid := requests.io.downstream.request.valid
    io.downstreamAddress := requests.io.downstream.request.bits
    io.downstreamMask := requests.io.downstream.requestMask
    requests.io.upstream.response.ready := io.responseReady
    requests.io.downstream.response.valid := io.responseValid
    requests.io.downstream.response.bits := (if (words == 4) Cat(io.responseHigh, io.responseLow) else io.responseLow)
    requests.io.downstream.responseError := io.responseError
    requests.io.downstream.responsePageFault := io.responsePageFault
    io.downstreamResponseReady := requests.io.downstream.response.ready
    io.upstreamResponseValid := requests.io.upstream.response.valid
    io.upstreamResponseLow := requests.io.upstream.response.bits(63, 0)
    io.upstreamResponseHigh := (if (words == 4) requests.io.upstream.response.bits(127, 64) else 0.U)
    io.upstreamResponseError := requests.io.upstream.responseError
    io.upstreamResponsePageFault := requests.io.upstream.responsePageFault
}
