package vpu

import chisel3._
import chisel3.util._

/** Single-owner vector compute engine with VLEN128/ELEN64 and fractional LMUL.
  * Architectural data and uncommitted results reside in versioned RAM.
  * A single 128-bit mask cache and scalar element staging are independent of
  * LMUL. Integer elements may overlap in the lane pipeline; instruction ownership
  * remains exclusive until completion or flush. Successful arithmetic publishes
  * its destination versions only on completion.fire.
  *
  * This module handles arithmetic, reductions, permutations, configuration and
  * local CSR operations. Physical vector memory operations use the separate LSU
  * and its exclusive context/progress connection through MemoryRamVector.
  *
  * @param useRam Select synchronous RAM storage; the flop implementation is a reference variant.
  * @param chunkBits Integer lane carry/shift pipeline partition, in bits.
  * @param enableFp Elaborate the shared floating-point lane and conversion units.
  * @param enableMemoryCommit Expose the LSU's exclusive architectural vstart update port.
  * @param stageControl Retain decode and candidate-write stages in an integer-only build.
  * @param hostFcsr Use the host's architectural FCSR and return per-instruction flags.
  * @param stageOperands Register RAM window selection before operand extension and masking.
  */
class RamVector(useRam: Boolean = true, chunkBits: Int = 32, enableFp: Boolean = false, enableMemoryCommit: Boolean = false, stageControl: Boolean = false, hostFcsr: Boolean = false, stageOperands: Boolean = false) extends Module {
  require(!hostFcsr || enableFp,"Host FCSR mode requires FP")
  val staged=enableFp || stageControl
  override def desiredName = if(enableMemoryCommit && !enableFp) (if(chunkBits==16) "RamVectorIntegerMemory16" else "RamVectorIntegerMemory") else if(enableMemoryCommit) (if(chunkBits==16) "RamVectorFpMemory16" else "RamVectorFpMemory") else if(enableFp) (if(chunkBits==16) "RamVectorFp16" else "RamVectorFp") else if (!useRam) "RamVectorFlops" else if (chunkBits==16) "RamVector16" else "RamVector"
  val io = IO(new Bundle {
    val flush = Input(Bool())
    val command = Flipped(Decoupled(new Command))
    val completion = Decoupled(new Completion)
    val context = Flipped(Decoupled(new ContextAccess))
    val contextResult = Valid(UInt(64.W))
    val vl = Output(UInt(8.W))
    val vtype = Output(UInt(64.W))
    val vstart = Output(UInt(7.W))
    val vxrm = Output(UInt(2.W))
    val vxsat = Output(Bool())
    val versions = Output(UInt(32.W))
    val frm = if(enableFp) Some(Output(UInt(3.W))) else None
    val fflags = if(enableFp) Some(Output(UInt(5.W))) else None
    val fcsrHost = if(hostFcsr) Some(new FcsrHostPort) else None
    val busy = Output(Bool())
  })
  // Arithmetic follows decode -> candidate copy -> operand/execute/writeback
  // -> finish. Optional states split timing paths without adding another owner.
  val memoryCommit = if(enableMemoryCommit) Some(IO(Flipped(Decoupled(UInt(7.W))))) else None
  val stateCount=if(staged)38 else 36
  val states=Enum(stateCount+(if(stageOperands)3 else 0))
  val Seq(idle, decode, copyRead, copyWrite, maskRead, maskCapture, dispatch,
    readA, captureA, readB, captureB, launch, awaitResult, maskOldRead, maskWrite, finish) = states.take(16)
  val readC=states(if(staged)16 else 29)
  val captureC=states(if(staged)17 else 30)
  val checkVector=if(staged)states(18) else idle
  val reductionSeedRead=states(if(staged)19 else 16)
  val reductionSeedCapture=states(if(staged)20 else 17)
  val reductionWrite=states(if(staged)21 else 18)
  val scalarRead=states(if(staged)22 else 19)
  val scalarCapture=states(if(staged)23 else 20)
  val Seq(maskByteReadA,maskByteCaptureA,maskByteReadB,maskByteCaptureB,
    maskByteOldRead,maskByteWrite,maskByteScan)=states.slice(if(staged)24 else 21,if(staged)31 else 28)
  val slideAddress=states(if(staged)31 else 28)
  val macLaunch=states(if(staged)32 else 31)
  val macAwait=states(if(staged)33 else 32)
  val checkedVector=if(staged)states(34) else idle
  val wholeRead=states(if(staged)35 else 33)
  val wholeWrite=states(if(staged)36 else 34)
  val wholeCheck=states(if(staged)37 else 35)
  val fetchA=if(stageOperands)states(stateCount) else captureA
  val fetchB=if(stageOperands)states(stateCount+1) else captureB
  val fetchC=if(stageOperands)states(stateCount+2) else captureC
  val wholeMove=RegInit(false.B)
  val copyLast=Reg(Bool())
  // Freeze FP width controls at admission, before operand fetch. Raw selector
  // decode must not feed estimate classification in the launch cycle.
  val fpWidthMode=Reg(UInt(3.W));val fpOperandDouble=Reg(Bool())
  val reverseInteger=Reg(Bool());val invertComparison=Reg(Bool())
  // Committed architectural state is separate from the pending instruction's
  // nextVl/nextVtype/csrData values below. Context reads see committed RAM.
  val state = RegInit(idle)
  val command = Reg(new Command)
  val vl = RegInit(0.U(8.W))
  val vtype = RegInit((BigInt(1)<<63).U(64.W))
  val vstart = RegInit(0.U(7.W))
  val vxrm = RegInit(0.U(2.W))
  val vxsat = RegInit(false.B)
  val frm=if(enableFp)RegInit(0.U(3.W)) else WireDefault(0.U(3.W))
  val fflags=if(hostFcsr)WireDefault(io.fcsrHost.get.fflags) else if(enableFp)RegInit(0.U(5.W)) else WireDefault(0.U(5.W))
  // Execution-unit controls and sticky flags belong to the current instruction.
  // A canceled instruction must never merge these flags into architectural CSRs.
  val fp=if(enableFp)RegInit(false.B) else WireDefault(false.B)
  val fpOp=Reg(UInt(5.W)); val fpDestMultiply=Reg(Bool()); val fpReverse=Reg(Bool())
  val fpFlags=if(enableFp)RegInit(0.U(5.W)) else WireDefault(0.U(5.W))
  val c=Reg(UInt(64.W))
  val fractional=RegInit(false.B)
  val fixed=RegInit(false.B);val fixedMode=Reg(UInt(4.W));val fixedCarry=Reg(Bool());val fixedFlags=RegInit(false.B)
  val integerMac=RegInit(false.B)
  val macDestMultiply=Reg(Bool());val macSubtract=Reg(Bool())
  io.frm.foreach(x=>x:=(if(hostFcsr)io.fcsrHost.get.frm else frm)); io.fflags.foreach(x=>x:=fflags)
  val illegal = Reg(Bool())
  val kind = Reg(UInt(2.W)) // 0 arithmetic, 1 vset, 2 CSR
  val scalarResult = Reg(UInt(64.W))
  val scalarWrite = Reg(Bool())
  val nextVl = Reg(UInt(8.W))
  val nextVtype = Reg(UInt(64.W))
  val csrWrite = Reg(Bool())
  val csrData = Reg(UInt(64.W))
  // Element traversal keeps independent source, execution and destination widths.
  // Widening/narrowing operations therefore do not reuse one SEW for every port.
  val index = Reg(UInt(8.W))
  val sew = Reg(UInt(2.W))
  val arithmeticSew=Reg(UInt(2.W)) // decoded execution width, off the ALU input mask path
  val sourceSew = Reg(UInt(2.W)) // vs2 EEW, independently of configured and destination SEW
  val op = Reg(UInt(Op.width.W))
  val comparison = Reg(Bool())
  val destinationCount = Reg(UInt(4.W))
  val commitMask = Reg(UInt(32.W))
  val hasElements = Reg(Bool())
  val copyIndex = Reg(UInt(4.W))
  val mask = Reg(UInt(128.W))
  val sourceOffset = Reg(UInt(3.W))
  val bitOffset = Reg(UInt(7.W))
  val destination = Reg(UInt(5.W))
  val byteMask = Reg(UInt(16.W))
  // Scalar-sized operand and reduction scratch stays constant with LMUL. The
  // outstanding counter tracks elements in the integer lane, not instructions.
  val a = Reg(UInt(64.W))
  val b = Reg(UInt(64.W))
  val resultBit = Reg(Bool())
  val outstanding = RegInit(0.U(5.W))
  val reduction=RegInit(false.B)
  val maskLogic=RegInit(false.B)
  val scalarMove=RegInit(0.U(2.W)) // 0 ordinary, 1 vmv.x.s, 2 vmv.s.x
  val maskScalar=RegInit(false.B) // vcpop.m / vfirst.m, no vector destination
  val maskPrefix=RegInit(false.B) // vmsbf.m / vmsof.m / vmsif.m
  val indexGenerate=RegInit(0.U(2.W)) // 1 viota.m, 2 vid.v, 3 vcompress.vm; scalarResult holds prefix count
  val gatherCached=RegInit(false.B) // scalar-index splat reuses the existing b operand
  val gather=RegInit(0.U(2.W)) // 1 vrgather, 2 vrgatherei16
  val slide=RegInit(false.B)
  val slideAmount=Reg(UInt(8.W));val slideHuge=Reg(Bool())
  val prefixSeen=RegInit(false.B) // an active source bit in an earlier byte
  // Eight mask elements per iteration. Sources stay in committed RAM; only a
  // byte and its result/valid bits are staged, independent of VLEN and LMUL.
  val maskByteA=Reg(UInt(8.W))
  val maskByteResult=Reg(UInt(8.W))
  val maskByteEnable=Reg(UInt(8.W))
  val reductionAccumulator=Reg(UInt(64.W)) // one scalar element, never a group snapshot
  // The core arbitrates one RAM read and one byte-masked write. Arithmetic
  // writes select the candidate version; explicit context writes select committed.
  val streaming = WireDefault(false.B)
  val rf = Module(new VersionedRegisterFile(useRam))
  rf.io.readEnable := false.B; rf.io.readAddress := 0.U; rf.io.readCandidate := false.B
  val writeEnable = WireDefault(false.B)
  val writeAddress = WireDefault(0.U(5.W))
  val writeCandidate = WireDefault(false.B)
  val writeData = WireDefault(0.U(128.W))
  val writeMask = WireDefault(0.U(16.W))
  val writePending = if(staged) RegInit(false.B) else WireDefault(false.B)
  rf.io.commit := false.B; rf.io.commitMask := commitMask
  io.versions := rf.io.versions
  io.vl := vl; io.vtype := vtype; io.vstart := vstart; io.vxrm := vxrm; io.vxsat := vxsat
  io.busy := state =/= idle
  io.command.ready := state === idle && !io.context.valid && !writePending && !io.flush
  io.context.ready := state === idle && !writePending && !io.flush
  // LSU progress can publish only while arithmetic and context traffic are idle.
  // This handshake is separate from arithmetic's atomic version-map commit.
  memoryCommit.foreach { port =>
    port.ready := state === idle && !writePending && !io.context.valid && !io.command.valid && !io.flush
    when(port.fire) {
      assert(!io.contextResult.valid,"memory progress overlaps context response")
      vstart := port.bits
    }
  }
  // Context access addresses one 64-bit half of a vector register. The Valid
  // response arrives one cycle after acceptance and has no local backpressure.
  val contextValid = RegNext(io.context.fire,false.B)
  val contextWrite = Reg(Bool())
  val contextChunk = Reg(Bool())
  io.contextResult.valid := contextValid && !io.flush
  io.contextResult.bits := Mux(contextWrite,0.U,Mux(contextChunk,rf.io.readData(127,64),rf.io.readData(63,0)))
  when(io.context.fire) {
    contextWrite := io.context.bits.write; contextChunk := io.context.bits.address(0)
    rf.io.readEnable := !io.context.bits.write
    rf.io.readAddress := io.context.bits.address(5,1)
    writeEnable := io.context.bits.write
    writeAddress := io.context.bits.address(5,1)
    writeData := Fill(2,io.context.bits.data)
    writeMask := Mux(io.context.bits.address(0),"hff00".U,"h00ff".U)
  }
  // Drain the final candidate write before exposing completion. Merely holding
  // completion.valid does not publish RAM versions, CSRs or accumulated flags.
  io.completion.valid := state === finish && !writePending && !io.flush
  io.completion.bits.token := command.token
  io.completion.bits.instruction := command.instruction
  io.completion.bits.scalar := Mux(illegal || (kind===0.U && indexGenerate=/=0.U),0.U,scalarResult)
  io.completion.bits.writesScalar := scalarWrite && !illegal
  io.completion.bits.illegal := illegal
  if(hostFcsr) {
    val port=io.fcsrHost.get
    port.flags.valid:=io.completion.valid && !illegal && kind===0.U && fp
    port.flags.bits:=Mux(port.flags.valid,fpFlags,0.U)
  }
  when(io.command.fire) {
    command := io.command.bits; state := decode
    // Normalize only VSET operands at the existing owner-capture edge. The
    // decode phase reads captured VTYPE/AVL directly, without format muxes.
    val incoming = io.command.bits
    val instruction = incoming.instruction
    when(instruction(6,0) === 0x57.U && instruction(14,12) === 7.U) {
      val (selectedType, selectedAvl) = VectorTiming.vsetOperands(
        instruction, incoming.scalar2, incoming.avl, vl)
      command.scalar2 := selectedType
      command.avl := selectedAvl
    }
    if(hostFcsr) {frm:=io.fcsrHost.get.frm}
  }
  // Decode uses the captured owner command, so operand reads and a stalled
  // completion cannot be affected by subsequent host input changes.
  val inst = command.instruction
  val f3 = inst(14,12); val f6 = inst(31,26)
  val vd = inst(11,7); val vs2 = inst(24,20); val vs1 = inst(19,15)
  val vm = inst(25)
  val vv = f3 === 0.U; val vx = f3 === 4.U; val vi = f3 === 3.U
  val fpVV=enableFp.B && f3===1.U; val fpVF=enableFp.B && f3===5.U
  val fpUnary=fpVV && (f6===0x13.U || f6===0x12.U)
  val mulVV=f3===2.U; val mulVX=f3===6.U
  val bitUnary=mulVV && f6===0x12.U &&
    (vs1===8.U || vs1===9.U || vs1===10.U || vs1===12.U || vs1===13.U || vs1===14.U)
  val widenShift=f6===0x35.U && (vv || vx || vi)
  val carryEncoding=f6(5,2)===4.U && (vv || vx || (vi && !f6(1)))
  val saturatingEncoding=f6(5,2)===8.U && (vv || vx || (vi && !f6(1)))
  val averagingEncoding=f6(5,2)===2.U && (mulVV || mulVX)
  val roundingShiftEncoding=f6(5,1)===0x15.U && (vv || vx || vi)
  val clipEncoding=f6(5,1)===0x17.U && (vv || vx || vi)
  val fpWideConvert=fpVV && f6===0x12.U && (vs1>=8.U && vs1<=12.U || vs1===14.U || vs1===15.U)
  val fpNarrowConvert=fpVV && f6===0x12.U && vs1>=16.U && vs1<=23.U
  val fpResizeEncoding=fpWideConvert || fpNarrowConvert
  val narrowingGeometry=(f6(5,2)===11.U && (vv || vx || vi)) || fpNarrowConvert
  val fractionalEncoding=f6===0x27.U && (vv || vx)
  val fixedEncoding=carryEncoding || saturatingEncoding || averagingEncoding || roundingShiftEncoding || clipEncoding
  val fixedDecoded=Mux(carryEncoding,Cat(0.U(2.W),f6(0),f6(1)),
    Mux(saturatingEncoding,Cat(1.U(2.W),f6(1,0)),
      Mux(averagingEncoding,Cat(2.U(2.W),f6(1,0)),Mux(clipEncoding,Cat(7.U(3.W),f6(0)),Cat(6.U(3.W),f6(0))))))
  // Width-changing families share geometry checks below, but retain distinct
  // signedness and old-destination operand rules for widening multiply-add.
  val integerMacEncoding=f6(5,3)===5.U && f6(0) && (mulVV || mulVX)
  val extensionEncoding=mulVV && f6===0x12.U && vs1(4,3)===0.U && vs1(2,1)=/=0.U
  val narrowEncoding=f6(5,1)===0x16.U && (vv || vx || vi) // vnsrl/vnsra.wv/wx/wi
  val widenAddSub=f6(5,3)===6.U && (mulVV || mulVX) // vwadd[u]/vwsub[u], including .w sources
  val widenMultiply=(f6===0x38.U || f6===0x3a.U || f6===0x3b.U) && (mulVV || mulVX)
  val widenMac=f6(5,2)===15.U && (mulVX || (mulVV && f6(1,0)=/=2.U))
  val fpWidenAddSub=(fpVV || fpVF) && (f6===0x30.U || f6===0x32.U || f6===0x34.U || f6===0x36.U)
  val fpWidenMultiply=(fpVV || fpVF) && f6===0x38.U
  val fpWidenMac=(fpVV || fpVF) && f6(5,2)===15.U
  val fpWidenEncoding=fpWidenAddSub || fpWidenMultiply || fpWidenMac
  val widenEncoding=widenAddSub || widenMultiply || widenMac || fpWidenEncoding || fpWideConvert || widenShift
  val wideSource2=(widenAddSub || fpWidenAddSub) && f6(2)
  val widenSignedA=Mux(widenMac,f6(1,0)===1.U || f6(1,0)===2.U,Mux(widenMultiply,f6(1),f6(0)))
  val widenSignedB=Mux(widenMac,f6(0),Mux(widenMultiply,f6(1) && f6(0),f6(0)))
  // Reductions consume a scalar vector seed; mask scans and permutations use
  // their own cursors rather than treating every encoding as binary arithmetic.
  val integerReductionEncoding=mulVV && f6<=7.U
  val fpReductionEncoding=fpVV && f6(5,3)===0.U && f6(0) // 1/3 sum, 5 min, 7 max
  val wideningReductionEncoding=vv && f6(5,1)===0x18.U // vwredsumu/sum, f6=0x30/31
  val fpWidenReductionEncoding=fpVV && f6(5,2)===12.U && f6(0) // f6=0x31/33
  val anyWidenReduction=wideningReductionEncoding || fpWidenReductionEncoding
  val reductionEncoding=integerReductionEncoding || fpReductionEncoding || anyWidenReduction
  val maskLogicEncoding=mulVV && f6>=0x18.U && f6<=0x1f.U
  val fpScalarRead=fpVV && f6===0x10.U && vm && vs1===0.U
  val fpScalarWrite=fpVF && f6===0x10.U && vm && vs2===0.U
  val fpSlide=fpVF && (f6===0x0e.U || f6===0x0f.U)
  // FP broadcast/merge are bit transfers through the integer select lane.
  // Keep FP width/boxing validation, but never enter the FP arithmetic unit.
  val fpSelect=fpVF && f6===0x17.U && (!vm || vs2===0.U)
  val fpTransfer=fpScalarRead || fpScalarWrite || fpSlide || fpSelect
  val fpScalarValue=Mux(vtype(4,3)===2.U && !command.scalar(63,32).andR,"h7fc00000".U(64.W),command.scalar)
  val scalarReadEncoding=fpScalarRead || mulVV && f6===0x10.U && vm && vs1===0.U
  val scalarWriteEncoding=fpScalarWrite || mulVX && f6===0x10.U && vm && vs2===0.U
  val maskScalarEncoding=mulVV && f6===0x10.U && (vs1===16.U || vs1===17.U)
  val maskPrefixEncoding=mulVV && f6===0x14.U && vs1>=1.U && vs1<=3.U
  val compressEncoding=mulVV && f6===0x17.U
  val indexGenerateEncoding=Mux(compressEncoding,3.U(2.W),Mux(mulVV && f6===0x14.U,
    Mux(vs1===16.U,1.U(2.W),Mux(vs1===17.U && vs2===0.U,2.U(2.W),0.U(2.W))),0.U(2.W)))
  val slideEncoding=(f6===0x0e.U || f6===0x0f.U) && (vx || vi || mulVX || fpVF)
  val gatherEncoding=Mux(f6===0x0c.U && (vv || vx || vi),1.U(2.W),
    Mux(f6===0x0e.U && vv,2.U(2.W),0.U(2.W)))
  val scalarMoveEncoding=Mux(scalarReadEncoding,1.U(2.W),Mux(scalarWriteEncoding,2.U(2.W),0.U(2.W)))
  val vectorSource1=(vv || mulVV || (fpVV && !fpUnary)) && !reductionEncoding && !extensionEncoding && !bitUnary && indexGenerateEncoding===0.U && gatherEncoding===0.U
  // Numerical FP opcodes feed the FP lane. Transfers keep their FP legality
  // checks but reuse the integer data-selection path.
  val fpSupported=WireDefault(false.B)
  val fpDecoded=WireDefault(0.U(5.W)); val fpMask=WireDefault(false.B)
  if(enableFp) {
    def entryFp(code: Int, operation: Int, mask: Boolean=false, scalarOnly: Boolean=false): Unit = {
      when(f6===code.U && (fpVF || (fpVV && !scalarOnly.B))) {
        fpSupported:=true.B; fpDecoded:=operation.U; fpMask:=mask.B
      }
    }
    when(fpTransfer) {fpSupported:=true.B}
    when(fpWidenEncoding) {
      fpSupported:=true.B
      fpDecoded:=Mux(fpWidenAddSub,Mux(f6(1),FpOp.sub.U,FpOp.add.U),Mux(fpWidenMultiply,FpOp.mul.U,
        MuxLookup(f6(1,0),FpOp.fma.U)(Seq(1.U->FpOp.fnmadd.U,2.U->FpOp.fmsub.U,3.U->FpOp.fnmsub.U))))
    }
    when(fpReductionEncoding) {
      fpSupported:=true.B
      fpDecoded:=Mux(f6(2),Mux(f6(1),FpOp.max.U,FpOp.min.U),FpOp.add.U)
    }
    when(fpWidenReductionEncoding) {fpSupported:=true.B;fpDecoded:=FpOp.widenAdd.U}
    entryFp(0x00,FpOp.add); entryFp(0x02,FpOp.sub)
    entryFp(0x04,FpOp.min); entryFp(0x06,FpOp.max)
    entryFp(0x08,FpOp.sgnj); entryFp(0x09,FpOp.sgnjn); entryFp(0x0a,FpOp.sgnjx)
    entryFp(0x18,FpOp.eq,true); entryFp(0x19,FpOp.le,true)
    entryFp(0x1b,FpOp.lt,true); entryFp(0x1c,FpOp.ne,true)
    entryFp(0x1d,FpOp.gt,true,true); entryFp(0x1f,FpOp.ge,true,true)
    entryFp(0x20,FpOp.div); entryFp(0x21,FpOp.div,false,true)
    entryFp(0x24,FpOp.mul); entryFp(0x27,FpOp.sub,false,true)
    for (base<-Seq(0x28,0x2c)) {
      entryFp(base,FpOp.fma); entryFp(base+1,FpOp.fnmadd)
      entryFp(base+2,FpOp.fmsub); entryFp(base+3,FpOp.fnmsub)
    }
    when(fpVV && f6===0x13.U && (vs1===4.U || vs1===5.U)) {
      fpSupported:=true.B;fpDecoded:=Mux(vs1===5.U,30.U,31.U)
    }
    when(fpVV && f6===0x13.U && (vs1===0.U || vs1===16.U)) {
      fpSupported:=true.B; fpDecoded:=Mux(vs1===0.U,FpOp.sqrt.U,FpOp.classify.U)
    }
  }
    // Conversion selectors distinguish source/destination width and fixed RTZ
    // or round-to-odd modes before the common FP operation is registered.
    if(enableFp) {
      for((sub,operation)<-Seq((0,FpOp.toUInt),(1,FpOp.toInt),(2,FpOp.fromUInt),(3,FpOp.fromInt),(6,FpOp.toUIntRtz),(7,FpOp.toIntRtz),(8,FpOp.toUInt),(9,FpOp.toInt),(10,FpOp.fromUInt),(11,FpOp.fromInt),(12,FpOp.convertFloat),(14,FpOp.toUIntRtz),(15,FpOp.toIntRtz),(16,FpOp.toUInt),(17,FpOp.toInt),(18,FpOp.fromUInt),(19,FpOp.fromInt),(20,FpOp.convertFloat),(21,FpOp.convertOdd),(22,FpOp.toUIntRtz),(23,FpOp.toIntRtz))) {
        when(fpVV && f6===0x12.U && vs1===sub.U) { fpSupported:=true.B;fpDecoded:=operation.U }
      }
    }
  // Integer lane operations use a shared decode helper; special families below
  // override the operation and mask-result controls where their encodings overlap.
  val decodedOp = WireDefault(0.U(Op.width.W))
  val supported = WireDefault(false.B)
  val decodedMask = WireDefault(false.B)
  def entry(code: Int, operation: Int, immediate: Boolean = true, producesMask: Boolean = false): Unit = {
    when(f6 === code.U && (vv || vx || vi) && (immediate.B || !vi)) {
      decodedOp := operation.U; supported := true.B; decodedMask := producesMask.B
    }
  }
  entry(0x00,Op.add); entry(0x02,Op.sub,false)
  when(f6===3.U && (vx || vi)) {supported:=true.B;decodedOp:=Op.sub.U}
  when((f6===0x1e.U || f6===0x1f.U) && (vx || vi)) {
    supported:=true.B;decodedMask:=true.B;decodedOp:=Mux(f6(0),Op.le.U,Op.leu.U)
  }
  entry(0x01,Op.andn,false)
  entry(0x15,Op.rol,false); entry(0x14,Op.ror,false)
  // vror.vi uses instruction[26] as immediate bit 5, not an opcode bit.
  when(vi && f6(5,1)===0x0a.U) {supported:=true.B;decodedOp:=Op.ror.U}
  when(bitUnary) {
    supported:=true.B
    decodedOp:=MuxLookup(vs1,Op.brev8.U)(Seq(8.U->Op.brev8.U,9.U->Op.rev8.U,
      10.U->Op.brev.U,12.U->Op.clz.U,13.U->Op.ctz.U,14.U->Op.cpop.U))
  }
  entry(0x09,Op.and); entry(0x0a,Op.or); entry(0x0b,Op.xor)
  entry(0x25,Op.sll); entry(0x28,Op.srl); entry(0x29,Op.sra)
  entry(0x04,Op.minu,false); entry(0x05,Op.min,false)
  entry(0x06,Op.maxu,false); entry(0x07,Op.max,false)
  entry(0x18,Op.eq,true,true); entry(0x19,Op.ne,true,true)
  entry(0x1a,Op.ltu,false,true); entry(0x1b,Op.lt,false,true)
  entry(0x1c,Op.leu,true,true); entry(0x1d,Op.le,true,true)
  when(f6 === 0x17.U && (vv || vx || vi)) {
    supported := !vm || vs2 === 0.U
    decodedOp := Mux(vm,Op.move.U,Op.merge.U)
  }
  when(fpSelect) {supported:=true.B;decodedOp:=Mux(vm,Op.move.U,Op.merge.U)}
  // Multiply/divide and reduction encodings occupy the OPMVV/OPMVX space.
  // Their operation values also select the serialized execution units later.
  for((code,operation)<-Seq((0x20,Op.divu),(0x21,Op.div),(0x22,Op.remu),(0x23,Op.rem),(0x25,Op.mul),(0x27,Op.mulh),(0x24,Op.mulhu),(0x26,Op.mulhsu))) {
    when(f6===code.U && (mulVV || mulVX)) { supported:=true.B;decodedOp:=operation.U }
  }
  when(integerMacEncoding) {supported:=true.B;decodedOp:=Op.mul.U}
  when(wideningReductionEncoding) {supported:=true.B;decodedOp:=Op.add.U}
  when(integerReductionEncoding) {
    supported:=true.B
    decodedOp:=MuxLookup(f6,Op.add.U)(Seq(0.U->Op.add.U,1.U->Op.and.U,
      2.U->Op.or.U,3.U->Op.xor.U,4.U->Op.minu.U,5.U->Op.min.U,
      6.U->Op.maxu.U,7.U->Op.max.U))
  }
  when(maskLogicEncoding) {
    supported:=vm;decodedMask:=true.B
    decodedOp:=MuxLookup(f6,Op.and.U)(Seq(
      0x1a.U->Op.or.U,0x1b.U->Op.xor.U,0x1c.U->Op.or.U,
      0x1e.U->Op.or.U,0x1f.U->Op.xor.U))
  }
  // Data movement reuses the lane's move operation while fetch/writeback supplies
  // the appropriate scalar, gathered, shifted or extended element.
  when(scalarReadEncoding || scalarWriteEncoding) {supported:=true.B;decodedOp:=Op.move.U}
  when(maskScalarEncoding) {supported:=true.B;decodedOp:=Op.move.U}
  when(maskPrefixEncoding) {supported:=true.B;decodedOp:=Op.move.U;decodedMask:=true.B}
  when(indexGenerateEncoding=/=0.U) {supported:= !compressEncoding || vm;decodedOp:=Op.move.U}
  when(slideEncoding) {supported:=true.B;decodedOp:=Op.move.U}
  when(gatherEncoding=/=0.U) {supported:=true.B;decodedOp:=Op.move.U}
  when(extensionEncoding) {supported:=true.B;decodedOp:=Op.move.U}
  when(narrowEncoding) {supported:=true.B;decodedOp:=Mux(f6(0),Op.sra.U,Op.srl.U)}
  when(widenEncoding) {supported:=true.B;decodedOp:=Mux(widenMultiply || widenMac,Op.mul.U,Mux(f6(1),Op.sub.U,Op.add.U))}
  when(widenShift) {supported:=true.B;decodedOp:=Op.sll.U}
  when(fixedEncoding) {
    supported:= !carryEncoding || f6(0) || !vm
    decodedMask:=carryEncoding && f6(0)
    decodedOp:=Mux(roundingShiftEncoding || clipEncoding,Mux(f6(0),Op.sra.U,Op.srl.U),
      Mux(f6(1),Op.sub.U,Op.add.U))
  }
  when(fractionalEncoding) {supported:=true.B;decodedOp:=Op.fractionalMul.U}
  val producesMask=Mux(fpSupported,fpMask,decodedMask)
  // Register decode before alignment/overlap/permission checks in the FP top.
  val selectedOp=if(staged)Reg(UInt(Op.width.W)) else decodedOp
  val selectedFpOp=Reg(UInt(5.W))
  val selectedFp=if(staged)Reg(Bool()) else fpSupported
  val selectedMask=if(staged)Reg(Bool()) else producesMask
  val selectedSupported=if(staged)Reg(Bool()) else (supported||fpSupported)
  val selectedReduction=if(staged)Reg(Bool()) else reductionEncoding
  val selectedMaskLogic=if(staged)Reg(Bool()) else maskLogicEncoding
  val selectedScalarMove=if(staged)Reg(UInt(2.W)) else scalarMoveEncoding
  val selectedMaskScalar=if(staged)Reg(Bool()) else maskScalarEncoding
  val selectedMaskPrefix=if(staged)Reg(Bool()) else maskPrefixEncoding
  val selectedIndexGenerate=if(staged)Reg(UInt(2.W)) else indexGenerateEncoding
  val selectedSlide=if(staged)Reg(Bool()) else slideEncoding
  val selectedGather=if(staged)Reg(UInt(2.W)) else gatherEncoding
  // Five input bits select a compile-time EMUL table; the count is registered
  // before overlap/alignment checks. Zero marks an unsupported index EMUL.
  val ei16Count=MuxLookup(vtype(4,0),0.U(4.W))((for {
    m<-Seq(0,1,2,3,5,6,7);s<-0 until 4
    if m<4 || s<=m-5
  } yield {
    val exponent=(if(m<4)m else m-8)+1-s
    ((s<<3)|m).U -> (if(exponent>3 || exponent < -3)0 else 1<<math.max(0,exponent)).U(4.W)
  }))
  val selectedEi16Count=if(staged)Reg(UInt(4.W)) else ei16Count
  // Unary selector 2/3, 4/5, 6/7 denotes vf8, vf4, vf2 respectively.
  // [6]=source EMUL>=1, [5:2]=occupied register count (zero=reserved),
  // [1:0]=log2(source bytes). Register this small table before validation.
  val extensionGeometry=MuxLookup(Cat(vtype(4,0),vs1(2,1)),0.U(7.W))((for {
    m<-Seq(0,1,2,3,5,6,7);s<-0 until 4;factor<-1 to 3
    exponent=if(m<4)m else m-8
    if (m<4 || s<=m-5) && s>=factor && exponent-factor>= -3
  } yield {
    (((s<<3)|m)*4+(4-factor)).U ->
      (((if(exponent>=factor)1 else 0)<<6)|((1<<math.max(0,exponent-factor))<<2)|(s-factor)).U(7.W)
  }))
  val selectedExtensionGeometry=if(staged)Reg(UInt(7.W)) else extensionGeometry
  /** Maximum element count for a validated VTYPE, including fractional LMUL. */
  def maxVl(t: UInt): UInt = {
    val base = 16.U(8.W) >> t(4,3)
    MuxLookup(t(2,0),0.U(8.W))(Seq(
      0.U -> base,1.U -> (base<<1)(7,0),2.U -> (base<<2)(7,0),3.U -> (base<<3)(7,0),
      5.U -> (base>>3),6.U -> (base>>2),7.U -> (base>>1)))
  }
  val groupLog = Mux(vtype(2,0) <= 3.U,vtype(1,0),0.U(2.W))
  val groupCount = (1.U(4.W)<<groupLog)(3,0)
  val alignment = VectorConfig.groupAlignment(groupLog)
  val destinationLog=Mux(widenEncoding,VectorConfig.doubleGroupLog(vtype(2,0)),groupLog)
  val destinationAlignment=VectorConfig.groupAlignment(destinationLog)
  val destinationGroupCount=(1.U(4.W)<<destinationLog)(3,0)
  // Mask destinations have EEW=1: overlap may only use the lowest register
  // of a wider source group (generic narrowing-overlap rule).
  val badMaskOverlap = selectedMask && !selectedMaskLogic && !selectedMaskPrefix && ((vd=/=vs2 && VectorConfig.alignedGroupContains(vd,vs2,alignment)) ||
    (vectorSource1 && vd=/=vs1 && VectorConfig.alignedGroupContains(vd,vs1,alignment)))
  /** Validate typed register groups before any candidate write or source access.
    * In staged builds, checkVector registers the decision; checkedVector applies
    * it and captures execution geometry on the following cycle.
    */
  def validateVector(): Unit = {
    val needsVs2 = selectedFp || selectedOp =/= Op.move.U || extensionEncoding || selectedSlide || selectedGather=/=0.U || selectedIndexGenerate===3.U
    val extensionCount=selectedExtensionGeometry(5,2)
    val extensionAlignment=VectorConfig.countAlignment(extensionCount)
    val narrowAlignment=VectorConfig.narrowAlignment(vtype(2,0))
    val sourceAlignment=Mux(extensionEncoding,extensionAlignment,Mux(narrowingGeometry || wideSource2,narrowAlignment,alignment))
    val extensionOverlap=VectorConfig.alignedGroupsOverlap(vd,alignment,vs2,extensionAlignment)
    val extensionHighPart=(vd^vs2)===(alignment^extensionAlignment)
    val extensionBad=extensionEncoding && (extensionCount===0.U ||
      (extensionOverlap && !(selectedExtensionGeometry(6) && extensionHighPart)))
    // Destination may only occupy the lowest part of its wider source.
    // The two explicit sources cannot share a physical register at different EEW.
    val narrowBad=narrowingGeometry && (vtype(4,3)===3.U || vtype(2,0)===3.U ||
      (vd=/=vs2 && VectorConfig.alignedGroupsOverlap(vd,alignment,vs2,narrowAlignment)) ||
      (vv && VectorConfig.alignedGroupsOverlap(vs1,alignment,vs2,narrowAlignment)))
    def badWidenOverlap(source:UInt):Bool =
      VectorConfig.alignedGroupsOverlap(vd,destinationAlignment,source,alignment) &&
        (vtype(2) || (vd^source)=/=(destinationAlignment^alignment))
    val widenBad=widenEncoding && (vtype(4,3)===3.U || vtype(2,0)===3.U ||
      (!wideSource2 && badWidenOverlap(vs2)) || ((mulVV || fpVV && !fpUnary || widenShift && vv) && badWidenOverlap(vs1)) ||
      // Old vd is also a 2*SEW source: even high-part narrow overlap would
      // read the same register at two EEWs and is reserved for widening MAC.
      ((widenMac || fpWidenMac) && (VectorConfig.alignedGroupsOverlap(vd,destinationAlignment,vs2,alignment) ||
        ((mulVV || fpVV) && VectorConfig.alignedGroupsOverlap(vd,destinationAlignment,vs1,alignment)))) ||
      (wideSource2 && (mulVV || fpVV) && VectorConfig.alignedGroupsOverlap(vs2,narrowAlignment,vs1,alignment)))
    // Scalar and mask destinations occupy one register. Gather indices can have
    // an independent EMUL, so their alignment and overlap use a separate group.
    val singleRegister=selectedMaskLogic || selectedScalarMove=/=0.U || selectedMaskScalar || selectedMaskPrefix
    val misaligned = !singleRegister && ((needsVs2 && (vs2&sourceAlignment) =/= 0.U) || (vectorSource1 && (vs1&alignment) =/= 0.U) ||
      (!selectedMask && !selectedReduction && (vd&destinationAlignment) =/= 0.U))
    val indexCount=Mux(selectedGather===2.U,selectedEi16Count,groupCount)
    val indexAlignment=VectorConfig.countAlignment(indexCount)
    val gatherBad=selectedGather=/=0.U && (
      vd===vs2 || (vv && ((vs1&indexAlignment)=/=0.U || indexCount===0.U ||
        VectorConfig.alignedGroupsOverlap(vd,alignment,vs1,indexAlignment))) ||
      (selectedGather===2.U && vtype(4,3)=/=1.U && VectorConfig.alignedGroupsOverlap(vs2,alignment,vs1,indexAlignment)) ||
      (!vm && (vs2===0.U || (vv && vs1===0.U))))
    // Execution mask is an EEW=1 source; a data source cannot read v0 at SEW.
    // Reductions also read the scalar vector seed, unlike unary selectors.
    val badMaskSourceAlias = !vm && ((needsVs2 && vs2===0.U) ||
      ((vectorSource1 || selectedReduction) && vs1===0.U))
    val compressBad=selectedIndexGenerate===3.U && (
      vd===vs2 || VectorConfig.alignedGroupContains(vs1,vd,alignment) ||
      VectorConfig.alignedGroupContains(vs1,vs2,alignment))
    val wideningReductionBad=anyWidenReduction && (vtype(4,3)===3.U ||
      VectorConfig.alignedGroupContains(vs1,vs2,alignment))
    // Half-width conversions are admitted only for the implemented conversion
    // directions. Rounding-mode legality exempts instructions with a fixed mode.
    val smallFpConvert=fpResizeEncoding && vtype(4,3)===1.U &&
      (fpWideConvert && (selectedFpOp===FpOp.fromUInt.U || selectedFpOp===FpOp.fromInt.U || selectedFpOp===FpOp.convertFloat.U) ||
       fpNarrowConvert && (selectedFpOp===FpOp.toUInt.U || selectedFpOp===FpOp.toInt.U || selectedFpOp===FpOp.toUIntRtz.U || selectedFpOp===FpOp.toIntRtz.U || selectedFpOp===FpOp.convertFloat.U))
    val fpIllegal=selectedFp && (vtype(4,3)<2.U && !smallFpConvert || (!fpTransfer && frm>4.U && selectedFpOp=/=FpOp.toUIntRtz.U && selectedFpOp=/=FpOp.toIntRtz.U && selectedFpOp=/=FpOp.convertOdd.U && selectedFpOp=/=31.U))
    val bad=vtype(63) || !selectedSupported || fpIllegal || extensionBad || narrowBad || widenBad || wideningReductionBad || misaligned || badMaskOverlap || gatherBad || badMaskSourceAlias || compressBad ||
      ((!vm || carryEncoding) && !selectedMask && !selectedReduction && !selectedMaskScalar && vd === 0.U) ||
      ((selectedReduction || selectedMaskScalar || selectedMaskPrefix || selectedIndexGenerate===1.U || selectedIndexGenerate===3.U) && vstart=/=0.U) ||
      (selectedMaskPrefix && (vd===vs2 || (!vm && vd===0.U))) ||
      (selectedIndexGenerate===1.U && VectorConfig.alignedGroupContains(vs2,vd,alignment)) ||
      (selectedSlide && !f6(0) && vd===vs2)
    if(staged) {
      when(state===checkVector) {illegal:=bad;state:=checkedVector}
    }
    when(!staged.B || state===checkedVector) {
    when(if(staged)illegal else bad) {
      illegal := true.B; state := finish
    }.otherwise {
      // Capture all geometry before the RAM traversal. An empty active range
      // can finish without copying a destination or consuming an element.
      val destinationSew=Mux(selectedMaskLogic || selectedMaskPrefix,0.U,
        Mux(widenEncoding,Cat(vtype(4)^vtype(3),!vtype(3)),vtype(4,3)))
      sew:=destinationSew;op:=selectedOp;comparison:=selectedMask
      arithmeticSew:=Mux(anyWidenReduction || narrowingGeometry,
        Cat(destinationSew(1)||destinationSew(0),!destinationSew(0)),destinationSew)
      sourceSew:=Mux(extensionEncoding,selectedExtensionGeometry(1,0),
        Mux(narrowingGeometry || wideSource2,Cat(vtype(4)^vtype(3),!vtype(3)),vtype(4,3)))
      reduction:=selectedReduction
      maskLogic:=selectedMaskLogic;scalarMove:=selectedScalarMove
      maskScalar:=selectedMaskScalar
      maskPrefix:=selectedMaskPrefix;prefixSeen:=false.B;indexGenerate:=selectedIndexGenerate;slide:=selectedSlide;gather:=selectedGather;gatherCached:=false.B
      when(selectedSlide || selectedGather=/=0.U) {
        slideAmount:=Mux(mulVX || fpSlide,1.U,Mux(vi,vs1.pad(8),command.scalar(7,0)))
        slideHuge:= !mulVX && !fpSlide && !vi && command.scalar(63,8).orR
        nextVl:=maxVl(vtype) // private VLMAX scratch; kind=0 never publishes nextVl
      }
      if(enableFp) {
        fp:=selectedFp && !fpTransfer; fpOp:=selectedFpOp
        fpWidthMode:=Mux(fpResizeEncoding,Cat(vtype(4,3)===1.U,Mux(fpWideConvert,1.U(2.W),2.U(2.W))),0.U(3.W))
        fpOperandDouble:=Mux(fpResizeEncoding,fpWideConvert && vtype(4,3)===2.U,
          Mux(anyWidenReduction || narrowingGeometry,Cat(destinationSew(1)||destinationSew(0),!destinationSew(0)),destinationSew)===3.U)
        fpDestMultiply:=f6>=0x28.U && f6<=0x2b.U
        fpReverse:=fpVF && (f6===0x21.U || f6===0x27.U)
      }
      // The version-map mask names exactly the candidate registers published
      // together. Untouched bytes survive through the initial committed copy.
      destinationCount := Mux(selectedMask || selectedReduction || singleRegister,1.U,destinationGroupCount)
      val maskBase = Mux(selectedMask || selectedReduction || singleRegister,1.U(32.W),MuxLookup(destinationLog,1.U(32.W))(Seq(
        1.U -> 3.U(32.W),2.U -> 15.U(32.W),3.U -> 255.U(32.W))))
      commitMask := (maskBase<<vd)(31,0)
      copyIndex := 0.U; index := vstart
      hasElements := vl =/= 0.U && vstart < vl && selectedScalarMove=/=1.U && !selectedMaskScalar
      scalarWrite:=(selectedScalarMove===1.U || selectedMaskScalar) && (vd=/=0.U || fpScalarRead)
      when(selectedMaskScalar) {scalarResult:=Mux(vs1===17.U,"hffffffffffffffff".U,0.U)}
      state := Mux(selectedMaskScalar,Mux(vl===0.U,finish,maskRead),
        Mux(selectedScalarMove===1.U,scalarRead,Mux(vl === 0.U || vstart >= vl,finish,copyRead)))
    }
    }
  }
  when(state === decode) {
    // Keep instruction decode out of the multiplier/ALU operand paths.
    fractional:=fractionalEncoding
    fixed:=fixedEncoding;fixedMode:=fixedDecoded;fixedCarry:=carryEncoding && !vm;fixedFlags:=false.B
    integerMac:=integerMacEncoding || widenMac;macDestMultiply:=integerMacEncoding && !f6(2);macSubtract:=integerMacEncoding && f6(1)
    reverseInteger:=f6===3.U && (vx || vi)
    invertComparison:=(f6===0x1e.U || f6===0x1f.U) && (vx || vi)
    wholeMove:=false.B
    illegal := false.B; scalarResult := 0.U; scalarWrite := false.B; kind := 0.U
    hasElements := false.B; csrWrite := false.B
    if(enableFp) { fpFlags:=0.U }
    // CSR decode captures the old value but defers any write until
    // completion.fire. Host-owned FCSR addresses are deliberately absent here.
    when(inst(6,0) === 0x73.U) {
      kind := 2.U
      val address = inst(31,20)
      val old = WireDefault(0.U(64.W))
      val known = WireDefault(true.B)
      switch(address) {
        is(0x008.U) { old := vstart }
        is(0x009.U) { old := vxsat }
        is(0x00a.U) { old := vxrm }
        is(0x00f.U) { old := Cat(vxrm,vxsat) }
        is(0xc20.U) { old := vl }
        is(0xc21.U) { old := vtype }
        is(0xc22.U) { old := 16.U }
      }
      if(enableFp && !hostFcsr) {
        switch(address) {
          is(0x001.U) { old:=fflags }
          is(0x002.U) { old:=frm }
          is(0x003.U) { old:=Cat(frm,fflags) }
        }
      }
      known := (Seq(0x008,0x009,0x00a,0x00f,0xc20,0xc21,0xc22)++
        (if(enableFp && !hostFcsr)Seq(0x001,0x002,0x003) else Seq.empty)).map(x => address === x.U).reduce(_||_)
      val action = f3(1,0)
      val source = Mux(f3(2),vs1.pad(64),command.scalar)
      val write = action === 1.U || (vs1 =/= 0.U && action =/= 0.U)
      csrWrite := write
      csrData := MuxLookup(action,source)(Seq(2.U -> (old|source),3.U -> (old & ~source)))
      scalarResult := old; scalarWrite := vd =/= 0.U
      illegal := !known || action === 0.U || (write && address(11,10) === 3.U)
      state := finish
    }.elsewhen(inst(6,0) =/= 0x57.U) {
      illegal := true.B; state := finish
    }.elsewhen(f3 === 7.U) {
      // VSET captures a proposed VL/VTYPE pair. Unsupported VTYPE produces vill;
      // the rs1=x0, rd=x0 form may retain VL only when VLMAX stays compatible.
      kind := 1.U
      val setvl = inst(31,25) === 0x40.U
      val setivli = inst(31,30) === 3.U
      val setvli = !inst(31)
      val t = command.scalar2
      val fractionalLegal = VectorConfig.fractionalLegal(t)
      val keepVl = !setivli && vs1 === 0.U && vd === 0.U
      val legal = t(63,8) === 0.U && t(5,3) <= 3.U && fractionalLegal &&
        (!keepVl || (!vtype(63) && maxVl(t) === maxVl(vtype)))
      val avl = command.avl
      val maximum=maxVl(t)
      val length = Mux(VectorConfig.belowLimit(avl,maximum),avl(7,0),maximum)
      nextVl := Mux(legal,length,0.U)
      nextVtype := Mux(legal,t,(BigInt(1)<<63).U(64.W))
      scalarResult := Mux(legal,length,0.U); scalarWrite := vd =/= 0.U
      illegal := !(setvl || setivli || setvli)
      state := finish
    }.elsewhen(f6===0x27.U && vi) {
      // Whole moves ignore VL/LMUL/vill. SEW only scales the restart index.
      // Candidate copies preserve bytes before vstart; no group FF snapshot.
      val count=vs1(3,0)+1.U
      val align=vs1
      val legal=vm && (vs1===0.U || vs1===1.U || vs1===3.U || vs1===7.U) &&
        (vd&align)===0.U && (vs2&align)===0.U
      val startByte=(vstart.pad(10)<<vtype(4,3))(9,0)
      illegal:= !legal;wholeMove:=true.B
      if(enableFp) {fp:=false.B}
      destinationCount:=count;copyIndex:=0.U
      commitMask:=((255.U(32.W) >> (8.U-count))<<vd)(31,0)
      a:=startByte
      state:=wholeCheck
    }.otherwise {
      if(staged) {
        selectedOp:=decodedOp;selectedFpOp:=fpDecoded;selectedFp:=fpSupported
        selectedMask:=producesMask;selectedSupported:=supported||fpSupported
        selectedReduction:=reductionEncoding
        selectedMaskLogic:=maskLogicEncoding;selectedScalarMove:=scalarMoveEncoding
        selectedMaskScalar:=maskScalarEncoding
        selectedMaskPrefix:=maskPrefixEncoding;selectedIndexGenerate:=indexGenerateEncoding;selectedSlide:=slideEncoding;selectedGather:=gatherEncoding;selectedEi16Count:=ei16Count
        selectedExtensionGeometry:=extensionGeometry
        state:=checkVector
      } else {
        validateVector()
      }
    }
  }
  if(staged) { when(state===checkVector || state===checkedVector) { validateVector() } }
  // Whole-register moves preserve the byte prefix preceding vstart. Copy the
  // committed destination first so every unwritten candidate byte remains valid.
  when(state===wholeCheck) {
    val work=a(9,0)<Cat(destinationCount,0.U(4.W)) && vd=/=vs2
    hasElements:= !illegal && work;state:=Mux(!illegal && work,copyRead,finish)
  }
  when(state===copyRead || state===wholeRead) {
    copyLast:=copyIndex+1.U>=destinationCount
  }
  when(state === copyRead) {
    rf.io.readEnable := true.B; rf.io.readAddress := (vd+copyIndex)(4,0)
    state := copyWrite
  }
  when(state === copyWrite) {
    writeEnable := true.B; writeAddress := (vd+copyIndex)(4,0)
    writeCandidate := true.B; writeData := rf.io.readData; writeMask := "hffff".U
    copyIndex := copyIndex+1.U
    state := Mux(copyLast,Mux(wholeMove,wholeRead,Mux(scalarMove===2.U,reductionWrite,maskRead)),copyRead)
    when(wholeMove && copyLast) {copyIndex:=0.U}
  }
  // Whole moves then copy the committed source, updating only bytes at or after
  // the restart offset. Source/destination overlap never reads candidate data.
  when(state===wholeRead) {
    rf.io.readEnable:=true.B;rf.io.readAddress:=(vs2+copyIndex)(4,0);state:=wholeWrite
  }
  when(state===wholeWrite) {
    writeEnable:=true.B;writeCandidate:=true.B;writeAddress:=(vd+copyIndex)(4,0)
    writeData:=rf.io.readData
    writeMask:=VecInit((0 until 16).map(j=>Cat(copyIndex,j.U(4.W)).pad(10)>=a(9,0))).asUInt
    copyIndex:=copyIndex+1.U;state:=Mux(copyLast,finish,wholeRead)
  }
  // Cache the execution mask once. Compress reads its selector from vs1 instead
  // of v0; reductions obtain their seed before entering the element dispatcher.
  when(state === maskRead) {
    rf.io.readEnable := true.B; rf.io.readAddress := Mux(indexGenerate===3.U,vs1,0.U); state := maskCapture
  }
  when(state === maskCapture) { mask := rf.io.readData; state := Mux(reduction,reductionSeedRead,dispatch) }
  // Dispatch chooses an active element and registers its byte geometry. Masked
  // or skipped elements preserve copied destination bytes without issuing a lane op.
  when(state === dispatch) {
    when(index >= vl) { state := Mux(reduction,reductionWrite,Mux(streaming && outstanding=/=0.U,awaitResult,finish)) }
      .elsewhen(maskLogic || maskScalar || maskPrefix) {
        maskByteEnable:=VecInit((0 until 8).map { bit =>
          val position=Cat(0.U(1.W),index(6,3),bit.U(3.W))
          position>=index && position<vl
        }).asUInt
        state:=maskByteReadA
      }
      .elsewhen((indexGenerate===3.U && !mask(index(6,0))) || (!vm && !(fixed && fixedMode<4.U) && !mask(index(6,0)) && (fp || op =/= Op.merge.U))) { index := ParallelIncrement(index,true.B) }
      .otherwise {
        val offset = (index<<sew)(6,0)
        sourceOffset := offset(6,4)
        bitOffset := Cat(offset(3,0),0.U(3.W))
        destination := Mux(comparison,vd,(vd+offset(6,4))(4,0))
        val widthMask = VecInit(Seq(1,3,15,255).map(_.U(16.W)))(sew)
        byteMask := (widthMask<<offset(3,0))(15,0)
        when(extensionEncoding || narrowingGeometry || widenEncoding) {
          val source=(index<<sourceSew)(6,0)
          sourceOffset:=source(6,4);bitOffset:=Cat(source(3,0),0.U(3.W))
        }
        state := Mux(slide,slideAddress,Mux(indexGenerate===2.U,captureA,readA))
        when(slide) {
          // Stage the mathematical 9-bit source index in the existing a
          // operand register. Arithmetic and RAM address/shift are separate.
          a:=Mux(f6(0),index.pad(9)+slideAmount.pad(9),index.pad(9)-slideAmount.pad(9))
        }
        when(gather=/=0.U) {
          when(vv) {
            val idxOffset=(index<<Mux(gather===2.U,1.U,sew))(6,0)
            sourceOffset:=idxOffset(6,4);bitOffset:=Cat(idxOffset(3,0),0.U(3.W))
            state:=readB // read the committed index vector before the data source
          }.otherwise {a:=Mux(vi,vs1.pad(64),command.scalar);state:=Mux(gatherCached,launch,slideAddress)}
        }
      }
  }
  // Permutation addressing is staged separately from RAM selection. Out-of-range
  // gather/slidedown supplies zero; slideup's low prefix preserves the destination.
  when(state===slideAddress) {
    when(indexGenerate===3.U) {
      // Source data was captured first. Independently form its dense target
      // address from the selected-element count, keeping RAM selection separate.
      val offset=(scalarResult(7,0)<<sew)(6,0)
      destination:=(vd+offset(6,4))(4,0)
      bitOffset:=Cat(offset(3,0),0.U(3.W))
      byteMask:=(VecInit(Seq(1,3,15,255).map(_.U(16.W)))(sew)<<offset(3,0))(15,0)
      state:=launch
    }.otherwise {
    val up= !f6(0)
    val scalarElement=(mulVX || fpSlide) && Mux(up,index===0.U,a(8,0)===vl.pad(9))
    val zero= !up && (slideHuge || a(8,0)>=nextVl.pad(9))
    val offset=(a(6,0)<<sew)(6,0)
    sourceOffset:=offset(6,4);bitOffset:=Cat(offset(3,0),0.U(3.W))
    when(gather=/=0.U) {
      when(!VectorConfig.belowLimit(a,nextVl)) {
        b:=0.U;state:=launch;when(!vv) {gatherCached:=true.B}
      }
        .otherwise {state:=readA}
    }.elsewhen(up && !mulVX && !fpSlide && (slideHuge || a(8))) {
      index:=ParallelIncrement(index,true.B);state:=dispatch // below OFFSET: preserve destination
    }.elsewhen(scalarElement || zero) {
      b:=Mux(scalarElement,Mux(fpSlide,fpScalarValue,command.scalar) & VecInit(Seq(8,16,32,64).map(w=>((BigInt(1)<<w)-1).U(64.W)))(sew),0.U);state:=launch
    }.otherwise {state:=readA}
    }
  }

  // Mask operations process one byte of predicates at a time. The optional
  // operand stage also preserves the RAM byte used by viota's prefix feedback.
  val stagedRamByte=if(stageOperands)Some(Reg(UInt(8.W))) else None
  val ramByte=if(stageOperands)Mux(state===captureA,stagedRamByte.get,
    VecInit((0 until 16).map(i=>rf.io.readData(8*i+7,8*i)))(index(6,3))) else
    VecInit((0 until 16).map(i=>rf.io.readData(8*i+7,8*i)))(index(6,3))
  val predicateByte=VecInit((0 until 16).map(i=>mask(8*i+7,8*i)))(index(6,3))
  // Preserve the eighth index bit: advancing the last byte must yield 128,
  // never wrap to zero. vstart may begin in the middle of the first byte.
  val nextMaskByte=Cat(ParallelIncrement(Cat(0.U(1.W),index(6,3)),true.B),0.U(3.W))
  when(state===maskByteReadA) {
    rf.io.readEnable:=true.B;rf.io.readAddress:=vs2;state:=maskByteCaptureA
  }
  when(state===maskByteCaptureA) {
    when(maskScalar || maskPrefix) {
      val active=maskByteEnable & Mux(vm,255.U(8.W),predicateByte)
      maskByteResult:=ramByte & active
      when(maskPrefix) {maskByteEnable:=active}
      state:=maskByteScan
    }.otherwise {maskByteA:=ramByte;state:=maskByteReadB}
  }
  // Separate RAM byte selection/predicate filtering from count/priority and
  // scalar accumulation. The result byte register is shared with mask logic.
  when(state===maskByteScan) {
    when(maskPrefix) {
      maskByteResult:=MaskPrefixByte(maskByteResult,prefixSeen,vs1(1,0))
      prefixSeen:=prefixSeen || maskByteResult.orR
      state:=maskByteOldRead
    }.otherwise {
      index:=nextMaskByte;state:=dispatch
      when(vs1===17.U) {
        when(maskByteResult.orR) {
          scalarResult:=Cat(index(6,3),PriorityEncoder(maskByteResult));state:=finish
        }
      }.otherwise {scalarResult:=scalarResult(7,0)+PopCount(maskByteResult)}
    }
  }
  // Mask logic combines source bytes, then reads the candidate destination byte
  // so inactive bits and the partial first/last byte retain their old values.
  when(state===maskByteReadB) {
    rf.io.readEnable:=true.B;rf.io.readAddress:=vs1;state:=maskByteCaptureB
  }
  when(state===maskByteCaptureB) {
    val rhs=ramByte ^ Fill(8,f6===0x18.U || f6===0x1c.U)
    val logical=MuxLookup(op,maskByteA & rhs)(Seq(
      Op.or.U->(maskByteA | rhs),Op.xor.U->(maskByteA ^ rhs)))
    maskByteResult:=logical ^ Fill(8,f6>=0x1d.U)
    state:=maskByteOldRead
  }
  when(state===maskByteOldRead) {
    rf.io.readEnable:=true.B;rf.io.readAddress:=vd;rf.io.readCandidate:=true.B
    state:=maskByteWrite
  }
  when(state===maskByteWrite) {
    val result=(ramByte & ~maskByteEnable) | (maskByteResult & maskByteEnable)
    writeEnable:=true.B;writeAddress:=vd;writeCandidate:=true.B
    writeMask:=(1.U(16.W)<<index(6,3))(15,0);writeData:=Fill(16,result)
    index:=nextMaskByte;state:=dispatch
  }
  val elementMask = VecInit(Seq(8,16,32,64).map(w => ((BigInt(1)<<w)-1).U(64.W)))(sew)
  // Keep source geometry at SEW, but operate and commit the scalar at 2*SEW.
  // Owner instruction is stable until completion/flush; no extra mode register.
  val accumulatorMask=VecInit(Seq(8,16,32,64).map(w=>((BigInt(1)<<w)-1).U(64.W)))(arithmeticSew)
  val configuredMask=VecInit(Seq(8,16,32,64).map(w=>((BigInt(1)<<w)-1).U(64.W)))(vtype(4,3))
  def configuredSignExtend(value:UInt):UInt = MuxLookup(vtype(4,3),value)(Seq(
    0.U->Cat(Fill(56,value(7)),value(7,0)),
    1.U->Cat(Fill(48,value(15)),value(15,0)),
    2.U->Cat(Fill(32,value(31)),value(31,0))))
  // Scalar extraction reads element zero irrespective of the element cursor.
  // Integer results sign-extend; FP32 results use the scalar NaN-boxing format.
  when(state===scalarRead) {rf.io.readEnable:=true.B;rf.io.readAddress:=vs2;state:=scalarCapture}
  when(state===scalarCapture) {
    val value=rf.io.readData(63,0)
    scalarResult:=MuxLookup(sew,value)(Seq(
      0.U->Cat(Fill(56,value(7)),value(7,0)),
      1.U->Cat(Fill(48,value(15)),value(15,0)),
      2.U->Cat(Fill(32,value(31)),value(31,0))))
    when(fpScalarRead) {scalarResult:=Mux(sew===2.U,Cat("hffffffff".U(32.W),value(31,0)),value)}
    state:=finish
  }
  // A reduction carries one scalar accumulator across elements and writes only
  // destination element zero. Scalar insertion shares that final write path.
  when(state===reductionSeedRead) {
    rf.io.readEnable:=true.B;rf.io.readAddress:=vs1;state:=reductionSeedCapture
  }
  when(state===reductionSeedCapture) {
    reductionAccumulator:=rf.io.readData(63,0)&accumulatorMask;state:=dispatch
  }
  when(state===reductionWrite) {
    writeEnable:=true.B;writeCandidate:=true.B;writeAddress:=vd
    writeMask:=VecInit(Seq(1,3,15,255).map(_.U(16.W)))(arithmeticSew)
    writeData:=Mux(scalarMove===2.U,Mux(fpScalarWrite,fpScalarValue,command.scalar),reductionAccumulator).pad(128);state:=finish
  }
  // One-hot byte selection is registered alongside the synchronous RAM
  // request. It removes a barrel-select decode from the RAM-return path.
  val elementByteSelect=Reg(UInt(16.W))
  when(state===readA || state===readB || state===readC) {
    elementByteSelect:=UIntToOH(bitOffset(6,3),16)
  }
  val ramElement=if(stageOperands) {
    val rawRamElement=PackedElementRead(rf.io.readData,elementByteSelect)
    // Isolated integer configuration: separate RAM/window selection from
    // extension, width masking and the operand priority muxes.
    val captured=Reg(UInt(64.W))
    when(state===fetchA || state===fetchB || state===fetchC) {captured:=rawRamElement}
    when(state===fetchA) {
      stagedRamByte.get:=VecInit((0 until 16).map(i=>rf.io.readData(8*i+7,8*i)))(index(6,3));state:=captureA
    }
    when(state===fetchB) {state:=captureB}
    when(state===fetchC) {state:=captureC}
    captured
  } else PackedElementRead(rf.io.readData,elementByteSelect)
  when(state === readA) {
    rf.io.readEnable := true.B; rf.io.readAddress := Mux(indexGenerate===1.U,vs2,(vs2+sourceOffset)(4,0)); state := fetchA
  }
  // Extend each source according to its own EEW before selecting scalar/immediate
  // substitutes. The second vector read may require a different byte offset.
  when(state === captureA) {
    val value=ramElement
    val signExtended=MuxLookup(sourceSew,value)(Seq(
      0.U->Cat(Fill(56,value(7)),value(7,0)),
      1.U->Cat(Fill(48,value(15)),value(15,0)),
      2.U->Cat(Fill(32,value(31)),value(31,0))))
    a := Mux(wideningReductionEncoding && f6(0),signExtended,value&elementMask)
    when(narrowingGeometry) {a:=value&accumulatorMask}
    when(widenEncoding) {a:=Mux(wideSource2,value&elementMask,Mux(!widenShift && widenSignedA,signExtended,value&configuredMask))}
    val immediate = Cat(Fill(59,vs1(4)),vs1)
    val isShift = op === Op.sll.U || op === Op.srl.U || op === Op.sra.U || op === Op.rol.U || op === Op.ror.U
    val fpScalar=Mux(sew===2.U && !command.scalar(63,32).andR,"h7fc00000".U,command.scalar)
    b := Mux(reduction,reductionAccumulator,Mux(fp || fpSelect,fpScalar,Mux(vx || mulVX,command.scalar,Mux(isShift,vs1.pad(64),immediate))))&accumulatorMask
    when(widenEncoding) {b:=Mux(fpWidenEncoding,fpScalarValue,Mux(widenShift && vi,vs1.pad(64),Mux(!widenShift && widenSignedB,configuredSignExtend(command.scalar),command.scalar&configuredMask)))}
    when(vi && op===Op.ror.U) {b:=Cat(0.U(58.W),f6(0),vs1)}
    when(reverseInteger) {
      a:=Mux(vx,command.scalar,immediate)&elementMask
      b:=value&elementMask
    }
    // Small registered prefix feedback; RAM bit selection never feeds the
    // 64-bit arithmetic result chain. Masked-out elements bypass captureA.
    when(indexGenerate=/=0.U) {
      b:=Mux(indexGenerate===2.U,index,scalarResult(7,0)).pad(64)
      when(indexGenerate===1.U) {
        scalarResult:=ParallelIncrement(scalarResult(7,0),ramByte(index(2,0)))
      }
    }
    when(slide || gather=/=0.U || indexGenerate===3.U) {b:=value&elementMask}
    when(extensionEncoding) {
      val sourceMask=VecInit(Seq(8,16,32,64).map(w=>((BigInt(1)<<w)-1).U(64.W)))(sourceSew)
      b:=Mux(vs1(0),signExtended,value&sourceMask)
    }
    when((narrowingGeometry && vv) || (widenEncoding && (mulVV || fpVV && !fpUnary || widenShift && vv))) {
      // The second vector uses configured SEW, independently of the vs2 EEW.
      val offset=(index<<Mux(widenEncoding,vtype(4,3),sew))(6,0)
      sourceOffset:=offset(6,4);bitOffset:=Cat(offset(3,0),0.U(3.W))
    }
    when(((widenMultiply || widenMac) && mulVX) || (fpWidenEncoding && fpVF) || fpResizeEncoding || (clipEncoding && !vv)) {
      // Serialized multiply retires using bitOffset, unlike tag-based ALU writes.
      bitOffset:=Cat((index<<sew)(3,0),0.U(3.W))
    }
    when(gather=/=0.U && !vv) {gatherCached:=true.B}
    val fused=integerMac || (fp && fpOp>=FpOp.fma.U && fpOp<=FpOp.fnmadd.U)
    state := Mux(indexGenerate===3.U,slideAddress,Mux(vectorSource1,readB,Mux(fused,readC,launch)))
  }
  when(state === readB) {
    rf.io.readEnable := true.B; rf.io.readAddress := (vs1+sourceOffset)(4,0); state := fetchB
  }
  when(state === captureB) {
    val value=ramElement
    b := value&elementMask
    when(widenEncoding) {b:=Mux(!widenShift && widenSignedB,configuredSignExtend(value),value&configuredMask)}
    when(widenMultiply || widenMac || fpWidenEncoding || fpWideConvert) {bitOffset:=Cat((index<<sew)(3,0),0.U(3.W))}
    state := Mux(integerMac || (fp && fpOp>=FpOp.fma.U && fpOp<=FpOp.fnmadd.U),readC,launch)
    when(gather=/=0.U) {
      a:=Mux(gather===2.U,value(15,0).pad(64),value&elementMask)
      state:=slideAddress
    }
  }
  when(state===readC) {
    // Read the committed destination, never a partially updated candidate.
    rf.io.readEnable:=true.B; rf.io.readAddress:=destination; state:=fetchC
  }
  when(state===captureC) { c:=ramElement&elementMask; state:=launch }
  // Only independent integer elements stream: tags preserve each destination
  // offset while the dispatcher advances. All other units retain one element owner.
  val lane = Module(new IntegerLane(true,chunkBits))
  lane.io.flush := io.flush
  val isMul=op===Op.fractionalMul.U || op===Op.mul.U || op===Op.mulh.U || op===Op.mulhu.U || op===Op.mulhsu.U
  val isDiv=op===Op.div.U || op===Op.divu.U || op===Op.rem.U || op===Op.remu.U
  lane.io.in.valid := ((state === launch && !fixed && !fp && !isMul && !isDiv) || state===macLaunch) && !io.flush
  lane.io.in.bits.a := Mux(state===macLaunch && !macDestMultiply,c,a)
  lane.io.in.bits.b := Mux(state===macLaunch,reductionAccumulator,b)
  lane.io.in.bits.sew := arithmeticSew
  lane.io.in.bits.op := Mux(state===macLaunch,Mux(macSubtract,Op.sub.U,Op.add.U),op)
  lane.io.in.bits.select := mask(index(6,0)); lane.io.in.bits.tag := index
  streaming := !fixed && !fp && !comparison && !isMul && !isDiv && !reduction && !maskScalar && scalarMove===0.U && indexGenerate=/=3.U
  val streamActive=state===slideAddress || state===dispatch || state===readA || state===captureA || state===readB || state===captureB || state===launch || state===awaitResult || (if(stageOperands)state===fetchA || state===fetchB || state===fetchC else false.B)
  lane.io.out.ready := ((Mux(streaming,streamActive,state===awaitResult) && !fixed && !fp && !isMul && !isDiv) || state===macAwait) && !io.flush
  when(lane.io.in.fire) {
    when(streaming) { index:=ParallelIncrement(index,true.B);state:=dispatch }.otherwise { state:=Mux(state===macLaunch,macAwait,awaitResult) }
  }
  when(streaming && (lane.io.in.fire =/= lane.io.out.fire)) {
    outstanding:=Mux(lane.io.in.fire,outstanding+1.U,outstanding-1.U)
  }
  when(streaming && state===awaitResult && outstanding===0.U) { state:=finish }
  when(lane.io.out.fire && streaming) { assert(outstanding=/=0.U,"integer response without owner") }
  when(io.completion.valid) { assert(outstanding===0.U,"completion before element drain") }
  // The serialized multiplier shares lane request fields. MAC retains its low
  // product in scalar scratch, then launches an ALU add/subtract as a second step.
  val multiplier=Module(new IntegerMultiply(enableFractional=true))
  multiplier.fractionalRounding.get:=vxrm
  multiplier.io.flush:=io.flush;multiplier.io.in.bits:=lane.io.in.bits
  multiplier.io.in.bits.a:=Mux(integerMac && macDestMultiply,c,a)
  multiplier.io.in.valid:=state===launch && !fp && isMul && !io.flush
  multiplier.io.out.ready:=state===awaitResult && !fp && isMul && !io.flush
  when(multiplier.io.in.fire) { state:=awaitResult }
  when(multiplier.io.out.fire && fractional) {fixedFlags:=fixedFlags || multiplier.fractionalSaturated.get}
  when(multiplier.io.out.fire && integerMac) {
    // Reuse the reduction scratch for the registered low product. Keep this
    // return mux off the RAM -> shift/extend -> a/b critical read path.
    // vnms* subtracts the product FROM the addend, via the staged ALU.
    reductionAccumulator:=multiplier.io.out.bits.data;state:=macLaunch
  }
  // Division and fixed-point arithmetic hold the element cursor until a result
  // arrives. Saturation is accumulated privately and published with the instruction.
  val divider=Module(new IntegerDivide)
  divider.io.flush:=io.flush;divider.io.in.bits:=lane.io.in.bits
  divider.io.in.valid:=state===launch && !fp && isDiv && !io.flush
  divider.io.out.ready:=state===awaitResult && !fp && isDiv && !io.flush
  when(divider.io.in.fire) { state:=awaitResult }
  val integerFire=Mux(integerMac,lane.io.out.fire,Mux(isDiv,divider.io.out.fire,Mux(isMul,multiplier.io.out.fire,lane.io.out.fire)))
  val integerData=Mux(integerMac,lane.io.out.bits.data,Mux(isDiv,divider.io.out.bits.data,Mux(isMul,multiplier.io.out.bits.data,lane.io.out.bits.data)))
  val fixedUnit=Module(new FixedPointLane)
  fixedUnit.io.flush:=io.flush
  fixedUnit.io.in.valid:=state===launch && fixed && !io.flush
  fixedUnit.io.in.bits.a:=a;fixedUnit.io.in.bits.b:=b;fixedUnit.io.in.bits.sew:=sew
  fixedUnit.io.in.bits.mode:=fixedMode;fixedUnit.io.in.bits.rounding:=vxrm
  fixedUnit.io.in.bits.carry:=fixedCarry && mask(index(6,0));fixedUnit.io.in.bits.tag:=index
  fixedUnit.io.out.ready:=state===awaitResult && fixed && !io.flush
  when(fixedUnit.io.in.fire) {state:=awaitResult}
  when(fixedUnit.io.out.fire) {fixedFlags:=fixedFlags || fixedUnit.io.out.bits.saturated}
  val nonFpFire=Mux(fixed,fixedUnit.io.out.fire,integerFire)
  val nonFpData=Mux(fixed,fixedUnit.io.out.bits.data,integerData)
  val resultFire=WireDefault(nonFpFire)
  val resultData=WireDefault(nonFpData)
  // FP arithmetic and seven-bit estimates share ownership and flag collection.
  // Their result-valid paths are selected only for the captured operation class.
  if(enableFp) {
    val unit=Module(new FloatingPointLane(enableWiden=true,enableResize=true))
    unit.conversionWidths.get:=fpWidthMode
    unit.narrowOperands.get:=Mux(fpWidenEncoding,Mux(wideSource2,2.U,3.U),0.U)
    unit.io.flush:=io.flush
    val estimate=Module(new FloatingPointEstimate)
    val isEstimate=fpOp>=30.U
    estimate.io.flush:=io.flush;estimate.io.in.bits:=unit.io.in.bits
    estimate.io.in.valid:=state===launch && fp && isEstimate && !io.flush
    estimate.io.out.ready:=state===awaitResult && fp && isEstimate && !io.flush
    unit.io.in.valid:=state===launch && fp && !isEstimate && !io.flush
    unit.io.in.bits.a:=Mux(fpReverse,b,Mux(fpDestMultiply,c,a))
    unit.io.in.bits.b:=Mux(fpReverse,a,b)
    unit.io.in.bits.c:=Mux(fpDestMultiply,a,c)
    unit.io.in.bits.op:=fpOp; unit.io.in.bits.double:=fpOperandDouble
    unit.io.in.bits.rounding:=frm; unit.io.in.bits.tag:=index
    unit.io.out.ready:=state===awaitResult && fp && !isEstimate && !io.flush
    val fpFire=Mux(isEstimate,estimate.io.out.fire,unit.io.out.fire)
    val fpResult=Mux(isEstimate,estimate.io.out.bits,unit.io.out.bits)
    when(unit.io.in.fire || estimate.io.in.fire) { state:=awaitResult }
    when(fpFire) {
      fpFlags:=fpFlags | fpResult.flags
      when(fpResult.illegal) { illegal:=true.B; state:=finish }
    }
    resultFire:=Mux(fp,fpFire && !fpResult.illegal,nonFpFire)
    resultData:=Mux(fp,fpResult.data,nonFpData)
  }
  // Results either update a reduction accumulator, a mask bit, or candidate RAM.
  // Streaming writes use the response tag rather than the advanced issue cursor.
  when(resultFire) {
    when(indexGenerate===3.U) {scalarResult:=ParallelIncrement(scalarResult(7,0),true.B)}
    when(reduction) {reductionAccumulator:=resultData;index:=ParallelIncrement(index,true.B);state:=dispatch}
      .elsewhen(comparison) { resultBit := resultData(0) ^ invertComparison; state := maskOldRead }
      .otherwise {
        writeEnable := true.B; writeAddress := destination; writeCandidate := true.B
        val retiredOffset=(lane.io.out.bits.tag<<sew)(6,0)
        val retiredBits=Cat(retiredOffset(3,0),0.U(3.W))
        val retiredMask=(VecInit(Seq(1,3,15,255).map(_.U(16.W)))(sew)<<retiredOffset(3,0))(15,0)
        writeAddress:=Mux(streaming,(vd+retiredOffset(6,4))(4,0),destination)
        writeMask := Mux(streaming,retiredMask,byteMask)
        writeData := (resultData.pad(128)<<Mux(streaming,retiredBits,bitOffset))(127,0)
        when(!streaming) { index := ParallelIncrement(index,true.B); state := dispatch }
      }
  }
  // Comparison results replace a single predicate bit through a byte read/modify/
  // write, preserving all other bits in the candidate destination register.
  when(state === maskOldRead) {
    rf.io.readEnable := true.B; rf.io.readAddress := vd; rf.io.readCandidate := true.B; state := maskWrite
  }
  when(state === maskWrite) {
    val oldByte = (rf.io.readData>>Cat(index(6,3),0.U(3.W)))(7,0)
    val bit = (1.U(8.W)<<index(2,0))(7,0)
    val newByte = (oldByte & ~bit) | Mux(resultBit,bit,0.U)
    writeEnable := true.B; writeAddress := vd; writeCandidate := true.B
    writeMask := (1.U(16.W)<<index(6,3))(15,0); writeData := Fill(16,newByte)
    index := ParallelIncrement(index,true.B); state := dispatch
  }
  // This is the arithmetic/configuration publication boundary. A legal completion
  // flips the version map or updates CSRs; an illegal completion publishes neither.
  when(io.completion.fire) {
    when(!illegal) {
      when(kind === 1.U) { vl := nextVl; vtype := nextVtype; vstart := 0.U }
        .elsewhen(kind === 2.U) {
          when(csrWrite) {
            switch(inst(31,20)) {
              is(0x008.U) { vstart := csrData(6,0) }
              is(0x009.U) { vxsat := csrData(0) }
              is(0x00a.U) { vxrm := csrData(1,0) }
              is(0x00f.U) { vxrm := csrData(2,1); vxsat := csrData(0) }
            }
            if(enableFp && !hostFcsr) {
              switch(inst(31,20)) {
                is(0x001.U) { fflags:=csrData(4,0) }
                is(0x002.U) { frm:=csrData(2,0) }
                is(0x003.U) { frm:=csrData(7,5); fflags:=csrData(4,0) }
              }
            }
          }
        }.otherwise {
          when(hasElements) { rf.io.commit := true.B }
          when(fixed || fractional) {vxsat:=vxsat || fixedFlags}
          if(enableFp && !hostFcsr) { when(fp) { fflags:=fflags | fpFlags } }
          vstart := 0.U
        }
    }
    state := idle
  }
  // Flush abandons candidate versions and in-flight lane work. Committed RAM
  // needs no rollback or reset because arithmetic never wrote the active copy.
  when(io.flush) {
    outstanding:=0.U
    state := idle
    writeEnable := false.B
    rf.io.commit := false.B
  }
  if(staged) {
    // Break result-ready/state -> RAM address and read/modify/write paths.
    // Candidate writes can be discarded on flush. Context writes bypass this
    // stage so their architectural effect still occurs on context.fire.
    val stagedAddress = Reg(UInt(5.W))
    val stagedMask = Reg(UInt(16.W))
    val stagedData = Reg(UInt(128.W))
    val enqueueWrite = writeEnable && writeCandidate && !io.flush
    writePending := enqueueWrite
    when(enqueueWrite) {
      stagedAddress := writeAddress
      stagedMask := writeMask
      stagedData := writeData
    }
    val contextWriteNow = io.context.fire && io.context.bits.write
    rf.io.writeEnable := (writePending && !io.flush) || contextWriteNow
    // Use context IO fields directly: selecting the shared write-request mux
    // here would leave a combinational path from unit.out.ready/state to RAM.
    rf.io.writeAddress := Mux(contextWriteNow,io.context.bits.address(5,1),stagedAddress)
    rf.io.writeCandidate := !contextWriteNow
    rf.io.writeMask := Mux(contextWriteNow,Mux(io.context.bits.address(0),"hff00".U,"h00ff".U),stagedMask)
    rf.io.writeData := Mux(contextWriteNow,Fill(2,io.context.bits.data),stagedData)
    when(writePending) {
      assert(!contextWriteNow,"context write collided with pending candidate")
      assert(!rf.io.commit,"version commit preceded candidate write drain")
    }
  } else {
    rf.io.writeEnable := writeEnable
    rf.io.writeAddress := writeAddress
    rf.io.writeCandidate := writeCandidate
    rf.io.writeMask := writeMask
    rf.io.writeData := writeData
  }
}
