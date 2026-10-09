package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}

/** Narrow ownership/retirement fixture. Allocation deliberately has no register destination;
  * existing full ledger qualification owns RAT/free-list coverage. All completion, exception,
  * system, branch-retirement and recovery behavior is the real production RenameRob.
  */
class OlderPrefixRetirementGsim(p: OooParams) extends Module {
    require(p.loadOrderOlderRetire && p.registeredLoadReplay && p.registeredRobRetirement)
    require(p.registeredMemoryAddress && p.earlyRecoveryIssueBlock)
    require(p.renameWidth == 2 && p.commitWidth == 2 && p.completionWidth == 2)
    require(p.fastHeadTrapRecovery && p.fastHeadSystemRecovery && p.machineSystem)
    val io = IO(new Bundle {
        val allocate0 = Input(Valid(new RenameRequest))
        val allocate1 = Input(Valid(new RenameRequest))
        val complete0 = Input(Valid(new BackendCompletion(p)))
        val complete1 = Input(Valid(new BackendCompletion(p)))
        val sameCycleRetire = Input(UInt(2.W))
        val fastHeadRetire = Input(Valid(new BackendCompletion(p)))
        val loadOrderRetireLimit = Input(Valid(new RobToken(p)))
        val dispatchReady = Input(Bool())
        val commitEnable = Input(Bool())
        val recover = Input(Valid(new RecoveryRequest(p)))
        val headTrap = Input(Bool())
        val headSystem = Input(Bool())
        val renamed0 = Output(Valid(new RenamedInstruction(p)))
        val renamed1 = Output(Valid(new RenamedInstruction(p)))
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val completionAccepted0 = Output(Bool())
        val completionAccepted1 = Output(Bool())
        val recoveryAccepted = Output(Bool())
        val headTrapAccepted = Output(Bool())
        val headSystemAccepted = Output(Bool())
        val headSystemToken = Output(new RobToken(p))
        val recovering = Output(Bool())
        val occupancy = Output(UInt(p.countBits.W))
        val headException = Output(Valid(new HeadException(p)))
    })
    val ledger = Module(new RenameRob(p))
    ledger.io.allocate(0) := io.allocate0
    ledger.io.allocate(1) := io.allocate1
    ledger.io.rawRequests.foreach { raw =>
        raw(0) := io.allocate0.bits
        raw(1) := io.allocate1.bits
    }
    ledger.io.rawDestinations.foreach { rd =>
        rd(0) := io.allocate0.bits.rd
        rd(1) := io.allocate1.bits.rd
    }
    ledger.io.fetchFaultMask.foreach(_ := 0.U)
    ledger.io.complete(0) := io.complete0
    ledger.io.complete(1) := io.complete1
    ledger.io.sameCycleRetire := VecInit((0 until 2).map(io.sameCycleRetire(_)))
    ledger.io.sameCycleFault.foreach { faults =>
        faults(0) := io.complete0.bits.exception
        faults(1) := io.complete1.bits.exception
    }
    ledger.io.fastHeadRetire := io.fastHeadRetire
    ledger.io.loadOrderRetireLimit.get := io.loadOrderRetireLimit
    ledger.io.dispatchReady := io.dispatchReady
    ledger.io.commitEnable := io.commitEnable
    ledger.io.recover := io.recover
    ledger.io.recoveryProbe := io.recover
    ledger.io.parallelRecovery.foreach(_.local := 0.U.asTypeOf(Valid(new RecoveryRequest(p))))
    ledger.io.headTrap.get.valid := io.headTrap
    ledger.io.headSystem.get.valid := io.headSystem
    ledger.io.inspectRegister := 0.U
    io.renamed0 := ledger.io.renamed(0)
    io.renamed1 := ledger.io.renamed(1)
    io.commit0 := ledger.io.commit(0)
    io.commit1 := ledger.io.commit(1)
    io.completionAccepted0 := ledger.io.completionAccepted(0)
    io.completionAccepted1 := ledger.io.completionAccepted(1)
    io.recoveryAccepted := ledger.io.recoveryAccepted
    io.headTrapAccepted := ledger.io.headTrap.get.accepted
    io.headSystemAccepted := ledger.io.headSystem.get.accepted
    io.headSystemToken := ledger.io.headSystem.get.headToken
    io.recovering := ledger.io.recovering
    io.occupancy := ledger.io.occupancy
    io.headException := ledger.io.headException
}

object OlderPrefixRetirementGsimMain extends App {
    require(args.length == 1, "output directory is required")
    val target = args(0)
    val config = FpgaNextConfig.Selected.copy(physicalLoadIngressFlow = true, lsuEntries = 4,
        dmaLineTransfers = true, dmaLineEntries = 4)
    val baseline = config.coreParams
    val p = baseline.copy(loadOrderOlderRetire = true)
    require(p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64 && p.recoveryWidth == 4)
    Files.createDirectories(Paths.get(target))
    def quote(s: String): String = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
    def json(product: Product): String = product.productElementNames.zip(product.productIterator).map { case (name, value) =>
        "  " + quote(name) + ": " + quote(value.toString)
    }.mkString("{\n", ",\n", "\n}\n")
    Files.write(Paths.get(target, "effective-params.json"), json(p).getBytes(StandardCharsets.UTF_8))
    Files.write(Paths.get(target, "baseline-params.json"), json(baseline).getBytes(StandardCharsets.UTF_8))
    Files.write(Paths.get(target, "fixture-config.json"), json(config).getBytes(StandardCharsets.UTF_8))
    ChiselStage.emitCHIRRTLFile(new OlderPrefixRetirementGsim(p), Array("--target-dir", target))
}
