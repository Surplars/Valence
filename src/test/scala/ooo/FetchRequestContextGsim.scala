package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

/** Transport-only fixture: the real two-entry request buffer and its unchanged response path. */
class FetchRequestContextGsim(flowThrough: Boolean = false, independentCapture: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val requestValid = Input(Bool())
        val requestAddress = Input(UInt(64.W))
        val requestMask = Input(UInt(2.W))
        val requestPrivilege = Input(UInt(2.W))
        val requestReady = Output(Bool())
        val downstreamReady = Input(Bool())
        val downstreamValid = Output(Bool())
        val downstreamAddress = Output(UInt(64.W))
        val downstreamMask = Output(UInt(2.W))
        val downstreamPrivilege = Output(UInt(2.W))
        val responseReady = Input(Bool())
        val responseValid = Input(Bool())
        val responseData = Input(UInt(64.W))
        val responseError = Input(UInt(2.W))
        val responsePageFault = Input(UInt(2.W))
        val downstreamResponseReady = Output(Bool())
        val upstreamResponseValid = Output(Bool())
        val upstreamResponseData = Output(UInt(64.W))
        val upstreamResponseError = Output(UInt(2.W))
        val upstreamResponsePageFault = Output(UInt(2.W))
        // Identical top/host interface for all three elaborated implementations.
        val configuredFlowThrough = Output(Bool())
        val configuredIndependentCapture = Output(Bool())
    })
    val requests = Module(new InstructionRequestBuffer(
        packetWords = 2,
        flowThrough = flowThrough,
        independentCapture = independentCapture,
        withRequestContext = true
    ))
    requests.io.upstream.request.valid := io.requestValid
    requests.io.upstream.request.bits := io.requestAddress
    requests.io.upstream.requestMask := io.requestMask
    requests.io.upstream.requestContext.get.privilege := io.requestPrivilege
    io.requestReady := requests.io.upstream.request.ready
    requests.io.downstream.request.ready := io.downstreamReady
    io.downstreamValid := requests.io.downstream.request.valid
    io.downstreamAddress := requests.io.downstream.request.bits
    io.downstreamMask := requests.io.downstream.requestMask
    io.downstreamPrivilege := requests.io.downstream.requestContext.get.privilege
    requests.io.upstream.response.ready := io.responseReady
    requests.io.downstream.response.valid := io.responseValid
    requests.io.downstream.response.bits := io.responseData
    requests.io.downstream.responseError := io.responseError
    requests.io.downstream.responsePageFault := io.responsePageFault
    io.downstreamResponseReady := requests.io.downstream.response.ready
    io.upstreamResponseValid := requests.io.upstream.response.valid
    io.upstreamResponseData := requests.io.upstream.response.bits
    io.upstreamResponseError := requests.io.upstream.responseError
    io.upstreamResponsePageFault := requests.io.upstream.responsePageFault
    io.configuredFlowThrough := flowThrough.B
    io.configuredIndependentCapture := independentCapture.B
}

object FetchRequestContextGsimMain extends App {
    require(args.length >= 1 && args.length <= 2, "usage: output-dir [registered|flow|independent]")
    val mode = args.lift(1).getOrElse("registered")
    require(Set("registered", "flow", "independent").contains(mode), "unknown request-buffer mode")
    ChiselStage.emitCHIRRTLFile(
        new FetchRequestContextGsim(flowThrough = mode != "registered", independentCapture = mode == "independent"),
        Array("--target-dir", args.head)
    )
}
