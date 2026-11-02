package fetchresponsequalification
import chisel3._
import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.core.ooo._

/** Exact real capacity-one boundary and engine; no ideal response model. */
class FinalResponseIsland(p: OooParams, enabled: Boolean) extends Module {
    val io = IO(new Bundle {
        val virtual = Flipped(new InstructionPort(2))
        val vmState = Input(new VmCsrState)
        val privilege = Input(UInt(2.W))
        val pmpState = Input(new PmpState)
        val physical = new InstructionPort(2, true)
        val translation = new SvTranslationPort
        val idle = Output(Bool())
    })
    val boundary = Module(new InstructionFetchTransactionBoundary(2, 64))
    val engine = Module(if (enabled) new RegisteredInstructionTranslationEngine(p, false, 64, true, true)
        else new RegisteredInstructionTranslationEngine(p, false, 64, true))
    boundary.io.upstream <> io.virtual
    boundary.io.vmState := io.vmState
    boundary.io.privilege := io.privilege
    engine.io.command <> boundary.io.command
    boundary.io.result <> engine.io.result
    engine.io.pmpState := io.pmpState
    io.physical <> engine.io.physical
    io.translation <> engine.io.translation
    io.idle := boundary.io.idle && engine.io.idle
    assert(boundary.io.idle === engine.io.idle,
        "fetch transaction boundary and engine must release their owner together")
}
object FinalResponseMain extends App {
    require(args.length == 2 && Set("off", "on").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out))
    // Component parameters plus the public OooParams constructor prerequisite closure.
    // All other OooParams fields use public defaults; this is not a CPU profile.
    val p = OooParams(
        machineSystem = true,
        registeredFabricBoundary = true,
        registeredTranslatedResponses = true,
        parallelHomeQualification = true,
        independentFetchCapture = true,
        flowThroughFetchRequests = true,
        bufferedFetchRequests = true,
        renameWidth = 2,
        robEntries = 32,
        physicalRegs = 64,
        memoryEntries = 4,
        alignedFetchPmp = true,
        registeredTranslationHeads = true,
        fetchReplyTurnover = true,
        fetchIdentityTranslation = true,
        pmpEntries = 16,
        virtualMemoryLevels = 3,
        compressedInstructions = true,
        fetchReadyDataClear = false,
        alignedFetchSinglePage = false
    )
    Files.createDirectories(out)
    val selected = Set("machineSystem","registeredFabricBoundary","registeredTranslatedResponses","parallelHomeQualification","independentFetchCapture","flowThroughFetchRequests","bufferedFetchRequests","renameWidth", "robEntries", "physicalRegs", "memoryEntries", "alignedFetchPmp", "registeredTranslationHeads", "fetchReplyTurnover", "fetchIdentityTranslation", "pmpEntries", "virtualMemoryLevels", "compressedInstructions", "fetchReadyDataClear", "alignedFetchSinglePage")
    val fields = p.productElementNames.zip(p.productIterator).filter(x => selected(x._1)).map { case (k, v) =>
        "\"" + k + "\":\"" + v.toString + "\""
    }.mkString("{", ",", "}\n")
    Files.writeString(out.resolve("component-profile.json"), fields)
    ChiselStage.emitSystemVerilogFile(new FinalResponseIsland(p, args(1) == "on"),
        Array("--target-dir",out.toString),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables", "--default-layer-specialization=enable",
            "--verification-flavor=if-else-fatal"))
}
