package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.inorder._

object FiveStageArguments {
    def config(args: Array[String]): FiveStageConfig = {
        require(args.length >= 2, "output directory and XLEN required")
        val allowed = Set("--no-m", "--iterative", "--dsp-tiled", "--no-memory-bypass", "--rf-distributed", "--rf-auto",
            "--early-memory-issue", "--overlap-write-lookup", "--user", "--supervisor", "--sv39",
            "--no-fast-instruction-translation", "--c", "--a", "--f", "--d", "--timing-cuts",
            "--fast-data-translation", "--overlap-data-retirement", "--read-only-data-retirement", "--coherent-caches",
            "--coherent-control-cuts", "--coherent-bandwidth", "--coherent-whole-line", "--direct-fast-data-issue",
            "--cache-fetch-predecode", "--indexed-data-proofs", "--coherent-line-grants", "--coherent-miss-turnover",
            "--coherent-writeback-overlap", "--coherent-read-overlap", "--data-reply-handoff")
        require(args.drop(2).forall(a => allowed(a) || a.matches("--(icache|dcache|line|predictor|pmp|tlb|coherent-ways)=[0-9]+") ||
            a.matches("--pipeline=(compact5|balanced7|fpga8)")),
            "unknown option")
        require(args.drop(2).map(_.takeWhile(_ != '=')).distinct.length == args.length - 2, "duplicate option")
        def value(name: String, default: Int): Int = args.find(_.startsWith(name + "="))
            .map(_.split("=", -1)(1).toInt).getOrElse(default)
        require(!(args.contains("--rf-distributed") && args.contains("--rf-auto")), "conflicting RAM styles")
        require(!(args.contains("--iterative") && args.contains("--dsp-tiled")), "conflicting multiplier modes")
        FiveStageConfig(xlen = args(1).toInt, withM = !args.contains("--no-m"),
            multiplyMode = if (args.contains("--iterative")) "iterative"
                else if (args.contains("--dsp-tiled")) "dsp-tiled" else "dsp",
            memoryBypass = !args.contains("--no-memory-bypass"),
            registerFileStorage = if (args.contains("--rf-distributed")) "distributed"
                else if (args.contains("--rf-auto")) "auto" else "block",
            instructionCacheBytes = value("--icache", 0), dataCacheBytes = value("--dcache", 0),
            cacheLineBytes = value("--line", 64), branchPredictorEntries = value("--predictor", 0),
            earlyMemoryIssue = args.contains("--early-memory-issue"),
            overlapWriteLookup = args.contains("--overlap-write-lookup"),
            withUser = args.contains("--user") || args.contains("--supervisor") || args.contains("--sv39"),
            withSupervisor = args.contains("--supervisor") || args.contains("--sv39"),
            withSv39 = args.contains("--sv39"), pmpEntries = value("--pmp", 0), tlbEntries = value("--tlb", 4),
            fastInstructionTranslation = !args.contains("--no-fast-instruction-translation"),
            withC = args.contains("--c"), withA = args.contains("--a"),
            withF = args.contains("--f"), withD = args.contains("--d"),
            fpgaTimingCuts = args.contains("--timing-cuts"),
            fastDataTranslation = args.contains("--fast-data-translation"),
            directFastDataIssue = args.contains("--direct-fast-data-issue"),
            overlapDataRetirement = args.contains("--overlap-data-retirement"),
            readOnlyDataRetirement = args.contains("--read-only-data-retirement"),
            coherentCaches = args.contains("--coherent-caches"),
            coherentCacheWays = value("--coherent-ways", 1),
            coherentControlCuts = args.contains("--coherent-control-cuts"),
            coherentBandwidth = args.contains("--coherent-bandwidth"),
            coherentWholeLine = args.contains("--coherent-whole-line"),
            cacheFetchPredecode = args.contains("--cache-fetch-predecode"),
            indexedDataProofs = args.contains("--indexed-data-proofs"),
            coherentLineGrants = args.contains("--coherent-line-grants"),
            coherentMissTurnover = args.contains("--coherent-miss-turnover"),
            coherentWritebackOverlap = args.contains("--coherent-writeback-overlap"),
            coherentReadOverlap = args.contains("--coherent-read-overlap"),
            dataReplyHandoff = args.contains("--data-reply-handoff"),
            pipelineProfile = args.find(_.startsWith("--pipeline=")).map(_.stripPrefix("--pipeline="))
                .getOrElse("compact5"))
    }
}

object FiveStageMain extends App {
    val p = FiveStageArguments.config(args)
    ChiselStage.emitCHIRRTLFile(new FiveStageCore(p), Array("--target-dir", args.head))
}

object FiveStageRtlMain extends App {
    val p = FiveStageArguments.config(args)
    ChiselStage.emitSystemVerilogFile(new FiveStageCore(p), Array("--target-dir", args.head),
        Array("--split-verilog", "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}

object FiveStageRegisterFileMain extends App {
    ChiselStage.emitCHIRRTLFile(new SynchronousRegisterFile(args.lift(1).map(_.toInt).getOrElse(64)),
        Array("--target-dir", args.head))
}

object FiveStageCachedMain extends App {
    val p = FiveStageArguments.config(args)
    ChiselStage.emitCHIRRTLFile(new FiveStageCachedCore(p), Array("--target-dir", args.head))
}

object FiveStageCacheMain extends App {
    val p = FiveStageArguments.config(args.filterNot(a => a == "--flow-hits" || a == "--read-pma"))
    ChiselStage.emitCHIRRTLFile(new FiveStageWordCache(p, p.dataCacheBytes, args.contains("--flow-hits"),
        args.contains("--read-pma")),
        Array("--target-dir", args.head))
}

object FiveStagePredictorMain extends App {
    val p = FiveStageArguments.config(args)
    ChiselStage.emitCHIRRTLFile(new FiveStageBranchPredictor(p), Array("--target-dir", args.head))
}

object FiveStageCachedRtlMain extends App {
    val p = FiveStageArguments.config(args)
    ChiselStage.emitSystemVerilogFile(new FiveStageCachedCore(p), Array("--target-dir", args.head),
        Array("--split-verilog", "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}

object FiveStageMulDivMain extends App {
    val p = FiveStageArguments.config(args)
    ChiselStage.emitCHIRRTLFile(new FiveStageMulDiv(p), Array("--target-dir", args.head))
}

/** Independent raw-input fixture for the production optional EX helpers and ALU. */
class I1ExecuteDatapathFixture(p: FiveStageConfig) extends Module {
    val io = IO(new Bundle {
        val index = Input(UInt(5.W))
        val offers = Input(UInt(5.W))
        val available = Input(UInt(6.W))
        // The pinned GSIM's scalar setter emitter does not support top-level
        // Vec input ports. Keep the exact same six operands as scalar ports.
        val value0 = Input(UInt(p.xlen.W)); val value1 = Input(UInt(p.xlen.W))
        val value2 = Input(UInt(p.xlen.W)); val value3 = Input(UInt(p.xlen.W))
        val value4 = Input(UInt(p.xlen.W)); val value5 = Input(UInt(p.xlen.W))
        val usePc = Input(Bool())
        val useRs1 = Input(Bool())
        val useImmediate = Input(Bool())
        val pc = Input(UInt(p.xlen.W))
        val immediate = Input(UInt(p.xlen.W))
        val operation = Input(UInt(4.W))
        val word = Input(Bool())
        val resultFlags = Input(UInt(4.W))
        val other0 = Input(UInt(p.xlen.W)); val other1 = Input(UInt(p.xlen.W))
        val other2 = Input(UInt(p.xlen.W)); val other3 = Input(UInt(p.xlen.W))
        val operand = Output(UInt(p.xlen.W))
        val left = Output(UInt(p.xlen.W))
        val right = Output(UInt(p.xlen.W))
        val alu = Output(UInt(p.xlen.W))
        val result = Output(UInt(p.xlen.W))
        val operandMask = Output(UInt(6.W))
        val ownerMask = Output(UInt(6.W))
        val resultMask = Output(UInt(5.W))
    })
    val values = Seq(io.value0, io.value1, io.value2, io.value3, io.value4, io.value5)
    val otherResults = Seq(io.other0, io.other1, io.other2, io.other3)
    val owners = I1ExecuteDatapath.operandMasks(io.index, (0 until 5).map(io.offers(_)) :+ true.B)
    val masks = I1ExecuteDatapath.admittedMasks(owners, (0 until 6).map(io.available(_)))
    io.ownerMask := VecInit(owners).asUInt
    io.operandMask := VecInit(masks).asUInt
    io.operand := I1ExecuteDatapath.operand(masks, values)
    io.left := I1ExecuteDatapath.overrideOperand(masks, values, io.usePc, io.pc, io.useRs1)
    io.right := I1ExecuteDatapath.overrideOperand(masks, values, io.useImmediate, io.immediate)
    val unit = Module(new FiveStageAlu(p.xlen, p.fpgaTimingCuts))
    unit.io.resultEnable.foreach(_ := io.resultMask(4))
    unit.io.operation := io.operation; unit.io.word := io.word
    unit.io.left := io.left; unit.io.right := io.right; io.alu := unit.io.result
    io.resultMask := I1ExecuteDatapath.resultMask(
        io.resultFlags(0), io.resultFlags(1), io.resultFlags(2), io.resultFlags(3))
    io.result := (if (p.fpgaTimingCuts) I1ExecuteDatapath.resultFromEnabledAlu(io.resultMask, otherResults, io.alu)
        else I1ExecuteDatapath.result(io.resultMask, otherResults :+ io.alu))
}

object FiveStageExecuteDatapathMain extends App {
    val p = FiveStageArguments.config(args)
    ChiselStage.emitCHIRRTLFile(new I1ExecuteDatapathFixture(p), Array("--target-dir", args.head))
}
