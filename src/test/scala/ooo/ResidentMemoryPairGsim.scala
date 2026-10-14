package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._

class ResidentPairRow extends Bundle {
    val index = UInt(4.W)
    val tag = UInt(64.W)
    val source1 = UInt(6.W)
    val source2 = UInt(6.W)
    val immediate = UInt(64.W)
    val store = Bool()
    val atomic = Bool()
    val size = UInt(2.W)
}
class ResidentPairSaved extends Bundle {
    val index = UInt(4.W)
    val prepared = Bool()
    val address = UInt(64.W)
    val data = UInt(64.W)
}
class ResidentPairWrite extends Bundle {
    val address = UInt(6.W)
    val data = UInt(64.W)
}
class ResidentPairInput extends Bundle {
    val pending = UInt(16.W)
    val readyMask = UInt(48.W)
    val kill = UInt(16.W)
    val head = UInt(4.W)
    val commits = UInt(2.W)
    val fallbackQualified = UInt(16.W)
    val postedWindow = Bool()
    val poolSuppress = UInt(16.W)
    val authority = UInt(16.W)
    val startReady = Bool()
    val reserveMask = UInt(48.W)
    val mutation = UInt(3.W)
    val row = Valid(new ResidentPairRow)
    val saved = Valid(new ResidentPairSaved)
    val write0 = Valid(new ResidentPairWrite)
    val write1 = Valid(new ResidentPairWrite)
}
class ResidentPairObservation extends Bundle {
    val head = UInt(4.W)
    val originalMask = UInt(16.W)
    val preparationMask = UInt(16.W)
    val stageValid = Bool()
    val stageIndex = UInt(4.W)
    val stageTag = UInt(64.W)
    val stageAddress = UInt(64.W)
    val stageData = UInt(64.W)
    val stageSize = UInt(2.W)
    val residentLive = Bool()
    val offer = Bool()
    val fire = Bool()
    val nextValid = Bool()
    val nextIndex = UInt(4.W)
    val nextTag = UInt(64.W)
    val nextAddress = UInt(64.W)
    val nextData = UInt(64.W)
    val nextSize = UInt(2.W)
    val freshValid = Bool()
    val freshIndex = UInt(4.W)
    val reuse = Bool()
}

/** P1 boundary fixture, not a ROB/translation model. Both sides own their own
  * real PRF, immediate RAM, head mask and S. Authority is an explicit per-row
  * boundary input, while full-token validity and actual consumption are local.
  */
class ResidentMemoryPairSide(reuseResident: Boolean) extends Module {
    val p = OooParams(robEntries = 16, physicalRegs = 48, tagBits = 64)
    val io = IO(new Bundle {
        val in = Input(new ResidentPairInput)
        val out = Output(new ResidentPairObservation)
    })
    val rows = Reg(Vec(16, new ResidentPairRow))
    val savedValid = RegInit(VecInit(Seq.fill(16)(false.B)))
    val savedAddress = Reg(Vec(16, UInt(64.W)))
    val savedData = Reg(Vec(16, UInt(64.W)))
    when(io.in.row.valid) {
        rows(io.in.row.bits.index) := io.in.row.bits
        savedValid(io.in.row.bits.index) := false.B
    }
    when(io.in.saved.valid) {
        savedValid(io.in.saved.bits.index) := io.in.saved.bits.prepared
        savedAddress(io.in.saved.bits.index) := io.in.saved.bits.address
        savedData(io.in.saved.bits.index) := io.in.saved.bits.data
    }
    val head = RegInit(0.U(4.W))
    head := head + io.in.commits
    assert(io.in.head === head, "P1 host head must track the actual registered head")
    val headMask = Module(new RegisteredRobHeadMask(p))
    headMask.io.head := head
    headMask.io.commits := io.in.commits

    val sValid = RegInit(false.B)
    val sIndex = RegInit(0.U(4.W))
    val sToken = Reg(new RobToken(p))
    val sAddress = Reg(UInt(64.W))
    val sData = Reg(UInt(64.W))
    val sSize = RegInit(0.U(2.W))
    val live = sValid && io.in.pending(sIndex) && sToken.index === sIndex && rows(sIndex).tag === sToken.tag
    val offer = live && !io.in.kill(sIndex) && io.in.authority(sIndex)
    val fire = offer && io.in.startReady
    val originalMask = VecInit((0 until 16).map { i =>
        val src1 = Mux(io.in.pending(i), rows(i).source1, 0.U)
        val src2 = Mux(io.in.pending(i), rows(i).source2, 0.U)
        val sourcesReady = io.in.readyMask(src1) &&
            (!(rows(i).store || rows(i).atomic) || io.in.readyMask(src2))
        io.in.pending(i) && (!rows(i).store || i.U === head) && (savedValid(i) || sourcesReady)
    }).asUInt
    val fallback = VecInit((0 until 16).map { i =>
        io.in.pending(i) && rows(i).store && !rows(i).atomic && i.U =/= head &&
            savedValid(i) && io.in.fallbackQualified(i)
    }).asUInt
    val earlyExcluded = originalMask & ~Mux(fire, UIntToOH(sIndex, 16), 0.U)
    val baseOriginal = if (reuseResident) Mux(io.in.mutation === 4.U, earlyExcluded, originalMask) else originalMask
    val ordinary = Mux(baseOriginal.orR, baseOriginal, fallback)
    val pool = Mux(io.in.postedWindow && baseOriginal.orR, baseOriginal | fallback, ordinary) & ~io.in.poolSuppress

    val readCount = if (reuseResident) 1 else 2
    val owners = Wire(Vec(readCount, UInt(16.W)))
    val indices = Wire(Vec(readCount, UInt(4.W)))
    val valid = Wire(Vec(readCount, Bool()))
    val nextValid = Wire(Bool())
    val nextIndex = Wire(UInt(4.W))
    val selectOld = WireDefault(false.B)
    val selectSecond = WireDefault(false.B)
    if (reuseResident) {
        val planner = Module(new ResidentMemoryPreparationSelector(p, predecodedHead = true))
        planner.io.eligible := pool
        planner.io.head := head
        planner.io.headMask.get := headMask.io.afterHead
        planner.io.resident.valid := Mux(io.in.mutation === 1.U, sValid && io.in.pending(sIndex), live)
        planner.io.resident.bits := sIndex
        planner.io.issued := fire && io.in.mutation =/= 2.U
        owners(0) := planner.io.freshOwner
        indices(0) := planner.io.freshIndex
        valid(0) := planner.io.freshValid
        selectOld := planner.io.useResident
        nextValid := planner.io.selectedValid
        nextIndex := planner.io.selectedIndex
    } else {
        val planner = Module(new MemoryPreparationSelector(p, parallelRanks = true, predecodedHead = true))
        planner.io.eligible := pool
        planner.io.head := head
        planner.io.headMask.get := headMask.io.afterHead
        planner.io.issued := fire
        planner.io.issuedIndex := sIndex
        owners := VecInit(Seq(planner.io.firstOwner, planner.io.secondOwner))
        indices := VecInit(Seq(planner.io.firstIndex, planner.io.secondIndex))
        valid := VecInit(Seq(planner.io.firstValid, planner.io.secondValid))
        selectSecond := planner.io.useSecond
        nextValid := planner.io.selectedValid
        nextIndex := planner.io.selectedIndex
    }
    val payload = Module(new BankedIssuePayload(16, Seq.fill(readCount)(Set("immediate"))))
    payload.io.write := 0.U.asTypeOf(payload.io.write)
    payload.io.write(0).valid := io.in.row.valid
    payload.io.write(0).bits.index := io.in.row.bits.index
    payload.io.write(0).bits.data.immediate := io.in.row.bits.immediate
    val prf = Module(new OwnerBankedPhysicalRegisterFile(48, 2 * readCount))
    for ((write, lane) <- Seq(io.in.write0, io.in.write1).zipWithIndex) {
        prf.io.write(lane).valid := write.valid
        prf.io.write(lane).bits.address := write.bits.address
        prf.io.write(lane).bits.data := write.bits.data
    }
    val tokens = Wire(Vec(readCount, new RobToken(p)))
    val addresses = Wire(Vec(readCount, UInt(64.W)))
    val data = Wire(Vec(readCount, UInt(64.W)))
    val sizes = Wire(Vec(readCount, UInt(2.W)))
    for (rank <- 0 until readCount) {
        def selected(words: Seq[UInt]): UInt = CircularIssueSelector.selectPayload(owners(rank), words)
        val row = selected(rows.map(_.asUInt).toSeq).asTypeOf(new ResidentPairRow)
        payload.io.address(rank) := indices(rank)
        payload.io.enable(rank) := valid(rank)
        prf.io.address(2 * rank) := row.source1
        prf.io.address(2 * rank + 1) := row.source2
        val saved = valid(rank) && row.store && (owners(rank) & savedValid.asUInt).orR
        tokens(rank).index := row.index
        tokens(rank).tag := row.tag
        addresses(rank) := Mux(saved, selected(savedAddress.toSeq),
            TimingArithmetic.add64(prf.io.data(2 * rank), payload.io.data(rank).immediate))
        val savedValue = selected(savedData.toSeq)
        val savedCandidate = if (reuseResident) savedValue ^ (io.in.mutation === 3.U).asUInt else savedValue
        data(rank) := Mux(saved, savedCandidate, prf.io.data(2 * rank + 1))
        sizes(rank) := row.size
    }
    val nextToken = if (reuseResident) Mux(selectOld, sToken, tokens(0))
        else Mux(selectSecond, tokens(1), tokens(0))
    val nextAddress = if (reuseResident) Mux(selectOld, sAddress, addresses(0))
        else Mux(selectSecond, addresses(1), addresses(0))
    val nextData = if (reuseResident) Mux(selectOld, sData, data(0))
        else Mux(selectSecond, data(1), data(0))
    val nextSize = if (reuseResident) Mux(selectOld, sSize, sizes(0))
        else Mux(selectSecond, sizes(1), sizes(0))
    sValid := nextValid
    when(nextValid) { sIndex := nextIndex }
    sToken := nextToken
    sAddress := nextAddress
    sData := nextData
    sSize := nextSize
    when(live) {
        assert(sSize === rows(sIndex).size, "P1 immutable resident size")
        when(rows(sIndex).store && savedValid(sIndex)) {
            assert(sAddress === savedAddress(sIndex) && sData === savedData(sIndex), "P1 saved tuple mismatch")
        }
    }
    val rawNeeded = live && !io.in.kill(sIndex) && !(rows(sIndex).store && savedValid(sIndex))
    val raw1 = Mux(rawNeeded, rows(sIndex).source1, 0.U)
    val raw2 = Mux(rawNeeded, rows(sIndex).source2, 0.U)
    val needsData = rows(sIndex).store || rows(sIndex).atomic
    when(rawNeeded) {
        assert(io.in.readyMask(raw1) && (!needsData || io.in.readyMask(raw2)), "P1 raw source not ready")
        def overlaps(address: UInt): Bool = (raw1 =/= 0.U && address === raw1) ||
            (needsData && raw2 =/= 0.U && address === raw2)
        assert(!io.in.reserveMask(raw1) && (!needsData || !io.in.reserveMask(raw2)), "P1 live source reserve")
        for (write <- Seq(io.in.write0, io.in.write1)) {
            assert(!write.valid || !overlaps(write.bits.address), "P1 live source write")
        }
    }
    io.out.head := head
    io.out.originalMask := originalMask
    io.out.preparationMask := pool
    io.out.stageValid := sValid
    io.out.stageIndex := sIndex
    io.out.stageTag := sToken.tag
    io.out.stageAddress := sAddress
    io.out.stageData := sData
    io.out.stageSize := sSize
    io.out.residentLive := live
    io.out.offer := offer
    io.out.fire := fire
    io.out.nextValid := nextValid
    io.out.nextIndex := nextIndex
    io.out.nextTag := nextToken.tag
    io.out.nextAddress := nextAddress
    io.out.nextData := nextData
    io.out.nextSize := nextSize
    io.out.freshValid := valid(0)
    io.out.freshIndex := indices(0)
    io.out.reuse := selectOld
}

class ResidentMemoryPairGsim extends Module {
    val io = IO(new Bundle {
        val in = Input(new ResidentPairInput)
        val off = Output(new ResidentPairObservation)
        val on = Output(new ResidentPairObservation)
    })
    val off = Module(new ResidentMemoryPairSide(false))
    val on = Module(new ResidentMemoryPairSide(true))
    off.io.in := io.in
    on.io.in := io.in
    io.off := off.io.out
    io.on := on.io.out
}

object ResidentMemoryPairGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new ResidentMemoryPairGsim, Array("--target-dir", args(0)))
}
