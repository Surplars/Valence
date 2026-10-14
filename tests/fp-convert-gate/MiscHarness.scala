package soc.core.ooo
import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
class MiscHarness extends Module {
 val p=OooParams(robEntries=16,tagBits=16);val c=FloatingPointConfig.fullFD
 val io=IO(new Bundle {
  val valid=Input(Bool());val ready=Output(Bool());val resultReady=Input(Bool());val resultValid=Output(Bool());val flush=Input(Bool())
  val bits=Input(UInt(64.W));val bitsB=Input(UInt(64.W));val integer=Input(UInt(64.W));val token=Input(UInt(16.W));val owner=Output(UInt(20.W));val baseOwner=Output(UInt(20.W));val double=Input(Bool());val instruction=Input(UInt(32.W));val rm=Input(UInt(3.W))
  val value=Output(UInt(64.W));val flags=Output(UInt(5.W));val illegal=Output(Bool())
  val baseReady=Output(Bool());val baseValid=Output(Bool());val baseValue=Output(UInt(64.W));val baseFlags=Output(UInt(5.W));val baseIllegal=Output(Bool())
 })
 val cand=Seq(false,true).map(d=>Module(new FloatingPointMisc(p,d,c)).io)
 val base=Seq(false,true).map(d=>Module(new FloatingPointMiscBaseline(p,d,c)).io)
 for(us<-Seq(cand,base);(u,i)<-us.zipWithIndex){
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
 io.ready:=Mux(io.double,cand(1).request.ready,cand(0).request.ready);io.baseReady:=Mux(io.double,base(1).request.ready,base(0).request.ready)
 io.resultValid:=Mux(io.double,cand(1).result.valid,cand(0).result.valid);io.baseValid:=Mux(io.double,base(1).result.valid,base(0).result.valid)
 io.value:=Mux(io.double,cand(1).result.bits.value,cand(0).result.bits.value);io.flags:=Mux(io.double,cand(1).result.bits.flags,cand(0).result.bits.flags);io.illegal:=Mux(io.double,cand(1).result.bits.exception,cand(0).result.bits.exception)
 io.baseValue:=Mux(io.double,base(1).result.bits.value,base(0).result.bits.value);io.baseFlags:=Mux(io.double,base(1).result.bits.flags,base(0).result.bits.flags);io.baseIllegal:=Mux(io.double,base(1).result.bits.exception,base(0).result.bits.exception)
}
object MiscEmit extends App {
 ChiselStage.emitSystemVerilogFile(new MiscHarness,Array("--target-dir",args(0)),Array("-disable-all-randomization","-strip-debug-info","-default-layer-specialization=disable","-lowering-options=disallowLocalVariables"))
}
