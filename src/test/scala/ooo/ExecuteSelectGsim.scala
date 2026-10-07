package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

/** Pure combinational fixture: deterministic distinct full-field source payloads.
  * Selection is checked by a procedural independent priority oracle; ALU by the
  * existing independent unsigned ISA interpreter, not old/new DUT equivalence alone.
  */
class ExecuteSelectGsim(parallelAddressSums: Boolean = false, parallelMinMax: Boolean = false,
    parallelMinMaxWord: Boolean = false, earlyWordResults: Boolean = false) extends Module {
    val p = OooParams(robEntries = 16)
    val io = IO(new Bundle {
        val operation = Input(UInt(6.W))
        val word = Input(Bool())
        val left = Input(UInt(64.W))
        val right = Input(UInt(64.W))
        val result = Output(UInt(64.W))
        val legal = Output(Bool())
        val baselineResult = Output(UInt(64.W))
        val baselineLegal = Output(Bool())
        val present = Input(UInt(5.W))
        val seed = Input(UInt(64.W))
        val selected = Output(new BackendCompletion(p))
        val grants = Output(UInt(6.W))
    })
    for ((parallel, isNew) <- Seq(true -> true, false -> false)) {
        val alu = Module(new IntegerAlu(parallel, parallel && parallelAddressSums, parallel && parallelMinMax,
            parallel && parallelMinMaxWord, parallel && earlyWordResults))
        alu.io.operation := io.operation
        alu.io.word := io.word
        alu.io.left := io.left
        alu.io.right := io.right
        if (isNew) { io.result := alu.io.result; io.legal := alu.io.legal }
        else { io.baselineResult := alu.io.result; io.baselineLegal := alu.io.legal }
    }
    def source(i: Int): BackendCompletion = {
        val c = Wire(new BackendCompletion(p))
        c.token.index := io.seed(p.robBits - 1, 0) ^ i.U(p.robBits.W)
        c.token.tag := ~io.seed ^ (BigInt(i + 1) << 32).U(64.W)
        c.data := io.seed ^ BigInt(i + 1).U(64.W)
        c.nextPc := io.seed ^ BigInt((i + 1) * 17).U(64.W)
        c.exception := io.seed(i)
        c.cause := io.seed ^ BigInt((i + 1) * 257).U(64.W)
        c.tval := ~io.seed ^ BigInt((i + 1) * 65537).U(64.W)
        c
    }
    val payload = Module(new ParallelCompletionPayload(p))
    payload.io.present := io.present
    for (i <- 0 until 5) { payload.io.candidates(i) := source(i) }
    payload.io.fallback := source(5)
    io.selected := payload.io.selected
    io.grants := payload.io.grants
}
object ExecuteSelectGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new ExecuteSelectGsim(args.drop(1).contains("parallel-address-sums"),
        args.drop(1).contains("parallel-minmax-results"), args.drop(1).contains("parallel-minmax-word-results"), args.drop(1).contains("early-alu-word-results")),
        Array("--target-dir", args.head))
}
