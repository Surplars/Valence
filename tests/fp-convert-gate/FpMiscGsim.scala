package soc.core.ooo
import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
class FpMiscGsim(tagBits: Int) extends Module {
 val p=OooParams(robEntries=16,tagBits=tagBits);val c=FloatingPointConfig.fullFD
 val io=IO(new Bundle {
  val valid=Input(Bool());val ready=Output(Bool());val resultReady=Input(Bool());val resultValid=Output(Bool());val flush=Input(Bool())
  val bits=Input(UInt(64.W));val bitsB=Input(UInt(64.W));val integer=Input(UInt(64.W));val token=Input(UInt(64.W));val owner=Output(UInt((tagBits+4).W));val baseOwner=Output(UInt((tagBits+4).W));val double=Input(Bool());val instruction=Input(UInt(32.W));val rm=Input(UInt(3.W))
  val ownerTag=Output(UInt(64.W));val ownerIndex=Output(UInt(4.W));val baseOwnerTag=Output(UInt(64.W));val baseOwnerIndex=Output(UInt(4.W))
  val allIdle=Output(Bool());val baseAllIdle=Output(Bool())
  val value=Output(UInt(64.W));val flags=Output(UInt(5.W));val illegal=Output(Bool())
  val baseReady=Output(Bool());val baseValid=Output(Bool());val baseValue=Output(UInt(64.W));val baseFlags=Output(UInt(5.W));val baseIllegal=Output(Bool())
 })
 val cand=Seq(false,true).map(d=>Module(new FloatingPointMisc(p,d,c)).io)
 val base=Seq(false,true).map(d=>Module(new FloatingPointMiscBaseline(p,d,c)).io)
 for((us,isCandidate)<-Seq((cand,true),(base,false));(u,i)<-us.zipWithIndex){
  u.flush:=io.flush;u.request.valid:=io.valid && io.double === (i==1).B
  u.request.bits:=0.U.asTypeOf(new FloatingPointExecution(p))
  u.request.bits.command.instruction:=io.instruction
  u.request.bits.operands(0):=io.bits
  u.request.bits.operands(1):=io.bitsB
  u.request.bits.command.integerSource:=io.integer
  u.request.bits.command.token.index:=io.token(3,0)
  u.request.bits.command.token.tag:=io.token
  u.request.bits.rounding:=io.rm;u.result.ready:=io.resultReady
 }
 io.owner:=Mux(io.double,cand(1).result.bits.token.asUInt,cand(0).result.bits.token.asUInt);io.baseOwner:=Mux(io.double,base(1).result.bits.token.asUInt,base(0).result.bits.token.asUInt)
 io.allIdle:=cand.map(u=>u.request.ready && !u.result.valid).reduce(_ && _)
 io.baseAllIdle:=base.map(u=>u.request.ready && !u.result.valid).reduce(_ && _)
 io.ownerTag:=Mux(io.double,cand(1).result.bits.token.tag,cand(0).result.bits.token.tag)
 io.ownerIndex:=Mux(io.double,cand(1).result.bits.token.index,cand(0).result.bits.token.index)
 io.baseOwnerTag:=Mux(io.double,base(1).result.bits.token.tag,base(0).result.bits.token.tag)
 io.baseOwnerIndex:=Mux(io.double,base(1).result.bits.token.index,base(0).result.bits.token.index)
 io.ready:=Mux(io.double,cand(1).request.ready,cand(0).request.ready);io.baseReady:=Mux(io.double,base(1).request.ready,base(0).request.ready)
 io.resultValid:=Mux(io.double,cand(1).result.valid,cand(0).result.valid);io.baseValid:=Mux(io.double,base(1).result.valid,base(0).result.valid)
 io.value:=Mux(io.double,cand(1).result.bits.value,cand(0).result.bits.value);io.flags:=Mux(io.double,cand(1).result.bits.flags,cand(0).result.bits.flags);io.illegal:=Mux(io.double,cand(1).result.bits.exception,cand(0).result.bits.exception)
 io.baseValue:=Mux(io.double,base(1).result.bits.value,base(0).result.bits.value);io.baseFlags:=Mux(io.double,base(1).result.bits.flags,base(0).result.bits.flags);io.baseIllegal:=Mux(io.double,base(1).result.bits.exception,base(0).result.bits.exception)
}
object FpMiscGsimMain extends App {
 val tagBits=args(1).toInt;require(tagBits==16 || tagBits==64)
 ChiselStage.emitCHIRRTLFile(new FpMiscGsim(tagBits),Array("--target-dir",args(0)))
}
