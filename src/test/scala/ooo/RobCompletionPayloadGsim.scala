package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import java.nio.file.{Files, Paths}
import soc.core.ooo._

class RobCompletionPayloadInput(p: OooParams) extends Bundle {
    val allocate0 = Valid(new RenameRequest)
    val allocate1 = Valid(new RenameRequest)
    val complete0 = Valid(new BackendCompletion(p))
    val complete1 = Valid(new BackendCompletion(p))
    val intent = UInt(2.W)
    val sameCycleRetire = UInt(2.W)
    val dispatchReady = Bool()
    val commitEnable = Bool()
    val external = Valid(new RecoveryRequest(p))
    val local = Valid(new RecoveryRequest(p))
    val headTrap = Bool()
    val headSystem = Bool()
    val loadOrderLimit = Valid(new RobToken(p))
}

class RobCompletionPayloadObservation(p: OooParams) extends Bundle {
    val renamed0 = Valid(new RenamedInstruction(p))
    val renamed1 = Valid(new RenamedInstruction(p))
    val commit0 = Valid(new CommitRecord(p))
    val commit1 = Valid(new CommitRecord(p))
    val completionAccepted0 = Bool()
    val completionAccepted1 = Bool()
    val externalAccepted = Bool()
    val externalWins = Bool()
    val selected = Valid(new RecoveryRequest(p))
    val killed = UInt(p.robEntries.W)
    val recoveryAccepted = Bool()
    val headTrapAccepted = Bool()
    val headSystemAccepted = Bool()
    val headSystemToken = new RobToken(p)
    val recovering = Bool()
    val occupancy = UInt(p.countBits.W)
    val headValid = Bool()
    val headDone = Bool()
    val headPc = UInt(64.W)
    val headException = Valid(new HeadException(p))
    val freeCount = UInt(log2Ceil(p.physicalRegs + 1).W)
    val tagExhausted = Bool()
}

class RobCompletionPayloadPort(p: OooParams) extends Bundle {
    val in = Input(new RobCompletionPayloadInput(p))
    val reference = Output(new RobCompletionPayloadObservation(p))
    val candidate = Output(new RobCompletionPayloadObservation(p))
}

class RobPayloadRamWrite extends Bundle {
    val index = UInt(5.W)
    val nextPc = UInt(64.W)
    val tval = UInt(64.W)
}
class RobPayloadRamObservation extends Bundle {
    val nextPc0 = UInt(64.W)
    val nextPc1 = UInt(64.W)
    val tval = UInt(64.W)
}
class RobPayloadRamPort extends Bundle {
    val head = Input(UInt(5.W))
    val write0 = Input(Valid(new RobPayloadRamWrite))
    val write1 = Input(Valid(new RobPayloadRamWrite))
    val rows4 = Output(new RobPayloadRamObservation)
    val rows8 = Output(new RobPayloadRamObservation)
    val rows16 = Output(new RobPayloadRamObservation)
    val rows32 = Output(new RobPayloadRamObservation)
}

/** Paired complete public-interface ROBs. The only constructor difference is
  * the completion-payload storage. The program-order oracle remains unchanged.
  * No test injects owners, done state or payloads into the ledger hierarchy.
  */
class RobCompletionPayloadGsim extends Module {
    val p = TimingReady73Profile.on.coreParams
    require(p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2)
    require(p.robEntries == 16 && p.tagBits == 64 && p.recoveryWidth == 4)
    require(p.physicalRegs == 48 && p.registeredRobRetirement && p.retirementIntent && p.retirementSlotIdentity)
    require(p.parallelRecoveryAdmission && p.fastHeadTrapRecovery && p.fastHeadSystemRecovery)
    val io = IO(new Bundle {
        val rob = new RobCompletionPayloadPort(p)
        val ram = new RobPayloadRamPort
    })
    for ((rows, out) <- Seq(4 -> io.ram.rows4, 8 -> io.ram.rows8, 16 -> io.ram.rows16, 32 -> io.ram.rows32)) {
        val payload = Module(new WriterBankedRobCompletionPayload(rows))
        val bits = log2Ceil(rows)
        payload.io.head := io.ram.head(bits - 1, 0)
        for ((write, lane) <- Seq(io.ram.write0, io.ram.write1).zipWithIndex) {
            payload.io.write(lane).valid := write.valid
            payload.io.write(lane).bits.index := write.bits.index(bits - 1, 0)
            payload.io.write(lane).bits.nextPc := write.bits.nextPc
            payload.io.write(lane).bits.tval := write.bits.tval
        }
        out.nextPc0 := payload.io.nextPc(0)
        out.nextPc1 := payload.io.nextPc(1)
        out.tval := payload.io.headTval
    }
    for ((out, enabled) <- Seq((io.rob.reference, false), (io.rob.candidate, true))) {
        val ledger = Module(new RenameRob(p, retirementSlotIdentity = p.retirementSlotIdentity,
            bankedCompletionPayload = enabled))
        require(ledger.p == p && ledger.bankedCompletionPayload == enabled)
        ledger.io.allocate(0) := io.rob.in.allocate0
        ledger.io.allocate(1) := io.rob.in.allocate1
        ledger.io.rawRequests.foreach { raw =>
            raw(0) := io.rob.in.allocate0.bits
            raw(1) := io.rob.in.allocate1.bits
        }
        ledger.io.rawDestinations.foreach { rd =>
            rd(0) := io.rob.in.allocate0.bits.rd
            rd(1) := io.rob.in.allocate1.bits.rd
        }
        ledger.io.fetchFaultMask.foreach(_ := 0.U)
        ledger.io.complete(0) := io.rob.in.complete0
        ledger.io.complete(1) := io.rob.in.complete1
        ledger.io.retirementIntentValid.foreach { intents =>
            intents(0) := io.rob.in.intent(0)
            intents(1) := io.rob.in.intent(1)
        }
        ledger.io.sameCycleRetire := VecInit((0 until 2).map(io.rob.in.sameCycleRetire(_)))
        ledger.io.sameCycleFault.foreach { faults =>
            faults(0) := io.rob.in.complete0.bits.exception
            faults(1) := io.rob.in.complete1.bits.exception
        }
        ledger.io.fastHeadRetire := 0.U.asTypeOf(Valid(new BackendCompletion(p)))
        ledger.io.loadOrderRetireLimit.foreach(_ := io.rob.in.loadOrderLimit)
        ledger.io.dispatchReady := io.rob.in.dispatchReady
        ledger.io.commitEnable := io.rob.in.commitEnable
        ledger.io.recover := io.rob.in.external
        ledger.io.recoveryProbe := io.rob.in.external
        ledger.io.parallelRecovery.get.local := io.rob.in.local
        ledger.io.headTrap.get.valid := io.rob.in.headTrap
        ledger.io.headSystem.get.valid := io.rob.in.headSystem
        ledger.io.inspectRegister := 0.U

        out.renamed0 := ledger.io.renamed(0)
        out.renamed1 := ledger.io.renamed(1)
        out.commit0 := ledger.io.commit(0)
        out.commit1 := ledger.io.commit(1)
        out.completionAccepted0 := ledger.io.completionAccepted(0)
        out.completionAccepted1 := ledger.io.completionAccepted(1)
        out.externalAccepted := ledger.io.recoveryProbeAccepted
        out.externalWins := ledger.io.parallelRecovery.get.externalWins
        out.selected := ledger.io.parallelRecovery.get.selected
        out.killed := ledger.io.parallelRecovery.get.killed
        out.recoveryAccepted := ledger.io.recoveryAccepted
        out.headTrapAccepted := ledger.io.headTrap.get.accepted
        out.headSystemAccepted := ledger.io.headSystem.get.accepted
        out.headSystemToken := ledger.io.headSystem.get.headToken
        out.recovering := ledger.io.recovering
        out.occupancy := ledger.io.occupancy
        out.headValid := ledger.io.headValid
        out.headDone := ledger.io.headDone
        out.headPc := ledger.io.headPc
        out.headException := ledger.io.headException
        out.freeCount := ledger.io.freeCount
        out.tagExhausted := ledger.io.tagExhausted
    }
}

object RobCompletionPayloadGsimMain extends App {
    require(args.nonEmpty, "usage: RobCompletionPayloadGsimMain OUTPUT_DIRECTORY")
    ChiselStage.emitCHIRRTLFile(new RobCompletionPayloadGsim, Array("--target-dir", args.head))
    val directory = Paths.get(args.head)
    Files.createDirectories(directory)
    for (side <- Seq("reference", "candidate")) {
        Files.writeString(directory.resolve(s"actual-core-$side.json"),
            PostedBoardConfiguration.json(TimingReady73Profile.on.coreParams) + "\n")
    }
    Files.writeString(directory.resolve("rob-completion-payload-profile.txt"),
        "referenceBankedCompletionPayload=false\ncandidateBankedCompletionPayload=true\n" +
        "sameOooParams=true\nretirementSlotIdentity=true\nprimitiveRows=4,8,16,32\n" +
        "robEntries=16\ncompletionWidth=2\ncommitWidth=2\ntagBits=64\n" +
        "oracle=unchanged-retirement_slot_rob_oracle.h+rob_completion_payload_oracle.h\n")
}
