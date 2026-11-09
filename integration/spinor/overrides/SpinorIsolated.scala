package vpu

import chisel3._
import chisel3.util._

/** Capacity-one link with no combinational forward or backward bypass.
  *
  * Payload and valid come from local registers; input ready depends only on
  * the local full bit. An occupied slot must drain before it can refill, so
  * push and pop cannot occur together. Accepted transactions have no flush
  * path and must be drained before a coordinated reset.
  */
class RegisteredLink[T <: Data](gen:T) extends Module {
  val io=IO(new Bundle {val in=Flipped(Decoupled(gen));val out=Decoupled(gen)})
  val full=RegInit(false.B);val data=Reg(gen)
  io.in.ready:= !full;io.out.valid:=full;io.out.bits:=data
  when(io.in.fire) {data:=io.in.bits;full:=true.B}
  when(io.out.fire) {full:=false.B}
}

/** Registered architectural observations, also sampled after core publication.
  * In host-FCSR mode, frm/fflags observe the host sidebands; fflags does not
  * include the instruction's contribution until the CPU merges it at done.
  */
class IsolatedState extends Bundle {
  val vl=UInt(8.W);val vtype=UInt(64.W);val vstart=UInt(7.W)
  val vxrm=UInt(2.W);val vxsat=Bool();val frm=UInt(3.W);val fflags=UInt(5.W)
}
/** Immutable preview packet retained through authorization and final response.
  * flags is the per-instruction host-FCSR contribution, qualified by flagsValid.
  */
class IsolatedResult extends Bundle {
  val reply=new VpuHostReply
  val flagsValid=Bool();val flags=UInt(5.W)
}
/** Published result plus its post-publication state snapshot, held under stalls. */
class IsolatedDone extends Bundle {
  val result=new IsolatedResult
  val state=new IsolatedState
}
/** CPU-owned FCSR observations; execution frm is captured separately at offer. */
class IsolatedFcsr extends Bundle {val frm=UInt(3.W);val fflags=UInt(5.W)}

/** Same-clock registered SoC boundary with preview/grant/done publication.
  *
  * The CPU offers qualified retirement-head work. preview describes an
  * available result; grant authorizes a later local completion handshake;
  * done acknowledges publication. After grant the CPU retains ownership and
  * defers interrupts, recovery and younger work until done.fire.
  *
  * Arithmetic can be canceled before grant. Memory may already have committed
  * a prefix and must drain all accepted traffic before releasing its owner.
  * This protocol has distinct authorization and acknowledgement edges; it
  * cannot be wired to the direct VpuHostBoundary same-edge retirement protocol.
  * All interfaces share a clock. Reset requires coordinated transaction drain.
  */
class SpinorIsolated(monitorBase:BigInt=0,config:SpinorParams=SpinorParams()) extends Module {
  val core=Module(new SpinorVpu(monitorBase,config,retimeMemory=true))
  val io=IO(new Bundle {
    val offer=Flipped(Decoupled(new Command))
    val preview=Valid(new IsolatedResult)
    val grant=Flipped(Decoupled(UInt(80.W)))
    val done=Decoupled(new IsolatedDone)
    val stop=Input(Bool());val canceled=Valid(UInt(80.W))
    val busy=Output(Bool());val protocolError=Output(Bool())
    val contextMode=Input(Bool())
    val context=Flipped(Decoupled(new ContextAccess));val contextResult=Decoupled(UInt(64.W))
    val fcsrHost=if(config.hostFcsr)Some(Input(new IsolatedFcsr)) else None
    val status=Valid(new IsolatedState)
    val tl=new VpuTileLinkMaster(VpuTLParams())
    val monitor=Flipped(new VpuTileLinkMaster(VpuTLParams()))
  })
  // Command path: capture -> dispatch -> result preview -> captured grant
  // comparison -> core commit -> state sample -> held acknowledgement.
  // Context uses a separate request/response path under the same single owner.
  // poison is terminal until reset and never authorizes a core completion.
  val Seq(idle,dispatch,waiting,prepared,authorizing,commit,published,ack,cancel,
    contextSend,contextWait,contextReply,poison)=Enum(13)
  val state=RegInit(idle)
  val owner=Reg(new Command);val grantToken=Reg(UInt(80.W))
  val memory=owner.instruction(6,0)==="h07".U || owner.instruction(6,0)==="h27".U
  val store=owner.instruction(6,0)==="h27".U
  // The same immutable packet serves preview and done. Keep it until done.fire
  // instead of copying another wide completion register at publication.
  val result=Reg(new IsolatedResult);val finishedState=Reg(new IsolatedState)
  val contextRequest=Reg(new ContextAccess);val contextData=Reg(UInt(64.W))
  // Registered mode and stop inputs keep external control out of ready paths.
  // A sampled stop is retained through dispatch/execution until ownership ends.
  val contextMode=RegNext(io.contextMode,false.B);val stop=RegNext(io.stop,false.B)
  val stopPending=RegInit(false.B)
  val stopping=stop || stopPending
  io.offer.ready:=state===idle && !contextMode && !stop
  io.context.ready:=state===idle && contextMode && !stop
  io.preview.valid:=state===prepared;io.preview.bits:=result
  io.grant.ready:=state===prepared
  io.done.valid:=state===ack;io.done.bits.result:=result;io.done.bits.state:=finishedState
  // Cancellation is a one-cycle notification, not a backpressured response.
  io.canceled.valid:=state===cancel;io.canceled.bits:=owner.token
  io.contextResult.valid:=state===contextReply;io.contextResult.bits:=contextData
  io.busy:=state=/=idle;io.protocolError:=state===poison

  // Live status is observational and delayed. done.state instead freezes the
  // state sampled after publication; neither observation authorizes retirement.
  val observed=Wire(new IsolatedState)
  observed.vl:=core.io.core.vl;observed.vtype:=core.io.core.vtype
  observed.vstart:=core.io.core.vstart;observed.vxrm:=core.io.core.vxrm
  observed.vxsat:=core.io.core.vxsat
  observed.frm:=core.io.core.frm.getOrElse(0.U)
  observed.fflags:=core.io.core.fflags.getOrElse(0.U)
  val status=RegInit(0.U.asTypeOf(new IsolatedState));status:=observed
  io.status.bits:=status;io.status.valid:=RegNext(!reset.asBool,false.B)

  // Host observation and execution rounding have different lifetimes: the
  // former tracks registered CPU inputs; the latter is immutable for one offer.
  if(config.hostFcsr) {
    val committedFrm=RegNext(io.fcsrHost.get.frm,0.U)
    val committedFlags=RegNext(io.fcsrHost.get.fflags,0.U)
    // State observation belongs to the host, including during context access
    // before any offer has initialized the independent execution snapshot.
    observed.frm:=committedFrm
    val executionFrm=Reg(UInt(3.W))
    when(io.offer.fire) {executionFrm:=io.fcsrHost.get.frm}
    core.io.core.fcsrHost.get.frm:=Mux(state===idle,committedFrm,executionFrm)
    core.io.core.fcsrHost.get.fflags:=committedFlags
  }
  core.io.core.command.valid:=state===dispatch && (memory || !stopping)
  core.io.core.command.bits:=owner
  core.io.core.context.valid:=state===contextSend
  core.io.core.context.bits:=contextRequest
  // Stop before grant may cancel arithmetic, but never discard a memory
  // owner or a buffered bus beat. Once grant is accepted it cannot be revoked.
  core.io.core.flush:=state===cancel || ((state===waiting || state===prepared) && memory && stopping)

  // Completion consumption is gated by both identity and the saved full
  // packet. A stale token, missing memory metadata or changed preview fails
  // closed before the handshake that would publish arithmetic candidates.
  val identity=VectorTiming.equal(core.io.core.completion.bits.token,owner.token) &&
    VectorTiming.equal(core.io.core.completion.bits.instruction,owner.instruction)
  val metadata=core.io.memoryStatus.valid===memory
  val matches=identity && metadata
  val awaiting=state===waiting || state===prepared || state===authorizing || state===commit
  val unchanged=WireDefault(false.B)
  val malformed=(core.io.core.completion.valid && (!awaiting || !matches)) ||
    (core.io.memoryStatus.valid && !core.io.core.completion.valid)
  core.io.core.completion.ready:=state===commit && matches && !malformed && unchanged

  // Form a stable host packet using physical fault causes. Illegal instructions
  // have priority; faults and interrupted memory suppress scalar writeback.
  val snapshot=Wire(new IsolatedResult)
  snapshot:=0.U.asTypeOf(new IsolatedResult)
  snapshot.reply.completion:=core.io.core.completion.bits
  snapshot.reply.memory:=memory
  snapshot.reply.stopped:=memory && core.io.memoryStatus.bits.interrupted
  val illegal=core.io.core.completion.bits.illegal
  val fault=memory && core.io.memoryStatus.bits.fault
  val misaligned=Mux(store,core.io.memoryStatus.bits.cause===6.U,core.io.memoryStatus.bits.cause===4.U)
  snapshot.reply.exception:=illegal || fault
  snapshot.reply.cause:=Mux(illegal,2.U,Mux(fault,Mux(misaligned,Mux(store,6.U,4.U),Mux(store,7.U,5.U)),0.U))
  snapshot.reply.tval:=Mux(illegal,owner.instruction.pad(64),Mux(fault,core.io.memoryStatus.bits.address,0.U))
  snapshot.reply.rawMemoryCause:=Mux(memory,core.io.memoryStatus.bits.cause,0.U)
  snapshot.reply.element:=Mux(memory,core.io.memoryStatus.bits.element,0.U)
  when(illegal || fault || snapshot.reply.stopped) {snapshot.reply.completion.writesScalar:=false.B}
  if(config.hostFcsr) {
    snapshot.flagsValid:=core.io.core.fcsrHost.get.flags.valid
    snapshot.flags:=core.io.core.fcsrHost.get.flags.bits
  }
  // Compare the live determinants in parallel, before cause/tval normalization.
  // The immutable owner and captured packet make these equations equivalent to
  // full snapshot equality. Keep the full packet comparison as a separate proof.
  val liveCompletion=Wire(chiselTypeOf(core.io.core.completion.bits))
  val savedCompletion=Wire(chiselTypeOf(core.io.core.completion.bits))
  liveCompletion:=core.io.core.completion.bits; liveCompletion.writesScalar:=false.B
  savedCompletion:=result.reply.completion; savedCompletion.writesScalar:=false.B
  val stopped=memory && core.io.memoryStatus.bits.interrupted
  val scalarWrite=core.io.core.completion.bits.writesScalar && !(illegal || fault || stopped)
  val sameMemory = result.reply.memory===memory && result.reply.stopped===stopped &&
    result.reply.exception===(illegal || fault) &&
    (!memory || (VectorTiming.equal(core.io.memoryStatus.bits.cause,result.reply.rawMemoryCause) &&
      VectorTiming.equal(core.io.memoryStatus.bits.element,result.reply.element))) &&
    (illegal || !fault || VectorTiming.equal(core.io.memoryStatus.bits.address,result.reply.tval))
  val sameFlags=if(config.hostFcsr) core.io.core.fcsrHost.get.flags.valid===result.flagsValid &&
    VectorTiming.equal(core.io.core.fcsrHost.get.flags.bits,result.flags) else true.B
  unchanged:=VectorTiming.equal(liveCompletion.asUInt,savedCompletion.asUInt) &&
    scalarWrite===result.reply.completion.writesScalar && sameMemory && sameFlags
  when((state===prepared || state===authorizing || state===commit) && core.io.core.completion.valid) {
    assert(unchanged===VectorTiming.equal(snapshot.asUInt,result.asUInt),
      "factored live preview comparison must preserve full normalized packet equality")
  }

  // Only idle accepts a new owner. Admission captures raw payload first;
  // instruction classification and core handshakes use that registered copy.
  when(state===idle) {stopPending:=false.B}
  when((state===dispatch || state===waiting || state===prepared) && stop) {stopPending:=true.B}
  when(io.offer.fire) {
    owner:=io.offer.bits
    state:=dispatch
  }
  when(io.context.fire) {contextRequest:=io.context.bits;state:=contextSend}
  when(state===dispatch) {
    when(!memory && stopping) {state:=cancel}
      .elsewhen(core.io.core.command.fire) {state:=waiting}
  }
  when(state===waiting) {
    when(!memory && stopping) {state:=cancel}
      .elsewhen(core.io.core.completion.valid && matches) {result:=snapshot;state:=prepared}
  }
  when(state===prepared) {
    // grant wins a coincident stop: it is an irrevocable publication lease.
    when(io.grant.fire) {
      grantToken:=io.grant.bits;state:=authorizing
    }.elsewhen(!memory && stopping) {state:=cancel}
  }
  // Compare only captured tokens. The external CPU token never enters a wide
  // comparator ahead of the boundary register.
  when(state===authorizing) {state:=Mux(VectorTiming.equal(grantToken,owner.token),commit,poison)}
  when(state===commit) {
    // Refuse to consume a core which changed a previously captured result.
    when(!core.io.core.completion.valid || !unchanged) {state:=poison}
    when(core.io.core.completion.fire) {state:=published}
  }
  // Sampling one edge after core completion observes the newly committed state.
  // Hold the result and this snapshot until the CPU acknowledges done.
  when(state===published) {finishedState:=observed;state:=ack}
  when(io.done.fire || state===cancel) {state:=idle}
  // The inner context result is a Valid pulse. Capture it before exposing a
  // Decoupled outer response, so CPU stalls cannot lose or duplicate the value.
  when(core.io.core.context.fire) {state:=contextWait}
  when(state===contextWait && core.io.core.contextResult.valid) {contextData:=core.io.core.contextResult.bits;state:=contextReply}
  when(io.contextResult.fire) {state:=idle}
  // Protocol corruption overrides normal transitions, including cancellation.
  when(malformed) {state:=poison}

  // All four TL directions cross a non-flowing register. No flush here:
  // the LSU must see the final response and own all externally issued stores.
  val ramA=Module(new RegisteredLink(new VpuTLA(VpuTLParams())))
  val ramD=Module(new RegisteredLink(new VpuTLD(VpuTLParams())))
  ramA.io.in<>core.io.tl.a;io.tl.a<>ramA.io.out
  ramD.io.in<>io.tl.d;core.io.tl.d<>ramD.io.out
  val monitorA=Module(new RegisteredLink(new VpuTLA(VpuTLParams())))
  val monitorControl=Module(new RegisteredLink(new VpuTLA(VpuTLParams())))
  val monitorD=Module(new RegisteredLink(new VpuTLD(VpuTLParams())))
  monitorA.io.in<>io.monitor.a
  monitorControl.io.in.valid:=monitorA.io.out.valid
  monitorA.io.out.ready:=monitorControl.io.in.ready
  monitorControl.io.in.bits:=monitorA.io.out.bits
  // A control write can only mean 0/1/2. Preserve high-bit rejection in a
  // separate pipeline stage instead of a 64-bit <=2 carry chain inside the
  // monitor. For 32-bit writes the unused upper data half remains ignored.
  val ma=monitorA.io.out.bits
  val write=ma.opcode===0.U || ma.opcode===1.U
  val high=Mux(ma.size===2.U,ma.data(31,2).orR,ma.data(63,2).orR)
  monitorControl.io.in.bits.data:=ma.data(1,0).pad(64)
  monitorControl.io.in.bits.param:=ma.param | (write && high).asUInt
  core.io.monitor.a<>monitorControl.io.out
  monitorD.io.in<>core.io.monitor.d;io.monitor.d<>monitorD.io.out
}
