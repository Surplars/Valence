package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Scalar boundary for independent mixed-length, wrapping-PC and fault checks. */
class FetchOffsetsGsim(width: Int, stableFaultMetadata: Boolean = false,
    alignedFetchPmp: Boolean = false, rawFetchPresence: Boolean = false,
    parallelFetchTagLookup: Boolean = false, parallelAlignment: Boolean = false,
    independentPayloadCapture: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val pc = Input(UInt(64.W))
        val enable = Input(Bool())
        val invalidate = Input(Bool())
        val pause = Input(Bool())
        val virtualized = Input(Bool())
        val requestReady = Input(Bool())
        val requestValid = Output(Bool())
        val requestAddress = Output(UInt(64.W))
        val requestMask = Output(UInt(4.W))
        val responseValid = Input(Bool())
        val responseLow = Input(UInt(64.W))
        val responseHigh = Input(UInt(64.W))
        val responseErrors = Input(UInt(4.W))
        val responsePages = Input(UInt(4.W))
        val responseReady = Output(Bool())
        val lane0 = Output(Valid(UInt(32.W)))
        val lane1 = Output(Valid(UInt(32.W)))
        val lane2 = Output(Valid(UInt(32.W)))
        val lane3 = Output(Valid(UInt(32.W)))
        val errors = Output(UInt(4.W))
        val pages = Output(UInt(4.W))
        val fault0 = Output(UInt(64.W))
        val fault1 = Output(UInt(64.W))
        val fault2 = Output(UInt(64.W))
        val fault3 = Output(UInt(64.W))
    })
    val fetch = Module(new SynchronousFetch(pmpEntries = 0, compressed = true,
        cacheSets = 8, fetchWidth = width, stableFaultMetadata = stableFaultMetadata, alignedFetchPmp = alignedFetchPmp,
        rawFetchPresence = rawFetchPresence, parallelFetchTagLookup = parallelFetchTagLookup, parallelAlignment = parallelAlignment,
        independentPayloadCapture = independentPayloadCapture))
    fetch.io.pc := io.pc
    fetch.io.enable := io.enable
    fetch.io.invalidate := io.invalidate
    fetch.io.pause := io.pause
    fetch.io.virtualized := io.virtualized
    fetch.io.privilege := 3.U
    fetch.io.pmpState := 0.U.asTypeOf(new PmpState)
    fetch.io.memory.request.ready := io.requestReady
    io.requestValid := fetch.io.memory.request.valid
    io.requestAddress := fetch.io.memory.request.bits
    io.requestMask := fetch.io.memory.requestMask
    fetch.io.memory.response.valid := io.responseValid
    fetch.io.memory.response.bits := (if (width == 4) Cat(io.responseHigh, io.responseLow) else io.responseLow)
    fetch.io.memory.responseError := io.responseErrors
    fetch.io.memory.responsePageFault := io.responsePages
    io.responseReady := fetch.io.memory.response.ready
    val outputs = Seq(io.lane0, io.lane1, io.lane2, io.lane3)
    val addresses = Seq(io.fault0, io.fault1, io.fault2, io.fault3)
    val errors = Wire(Vec(4, Bool()))
    val pages = Wire(Vec(4, Bool()))
    for (lane <- 0 until 4) {
        if (lane < width) {
            outputs(lane) := fetch.io.instructions(lane)
            addresses(lane) := fetch.io.instructionFaultAddresses(lane)
            errors(lane) := fetch.io.instructionFaults(lane)
            pages(lane) := fetch.io.instructionPageFaults(lane)
        } else {
            outputs(lane) := 0.U.asTypeOf(outputs(lane))
            addresses(lane) := 0.U
            errors(lane) := false.B
            pages(lane) := false.B
        }
    }
    io.errors := errors.asUInt
    io.pages := pages.asUInt
}
object FetchOffsetsGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FetchOffsetsGsim(args(1).toInt, args.drop(2).contains("stable-fault-metadata"),
        args.drop(2).contains("aligned-fetch-pmp"), args.drop(2).contains("raw-fetch-presence"),
        args.drop(2).contains("parallel-fetch-tags"), args.drop(2).contains("parallel-alignment"),
        args.contains("--independent-payload-capture")),
        Array("--target-dir", args.head))
}
