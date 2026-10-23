package soc.ip.dma

import chisel3._
import chisel3.util._

/** Optional posted TX ownership. Payload remains in the existing single TX RAM.
  * An owner survives POST through completion POP. STOP finishes an active frame
  * and cancels only descriptors that have not launched, in posting order.
  */
class EthernetTxDescriptorQueue(slots: Int, ramBase: BigInt, ramBytes: BigInt, maxFrameBytes: Int,
    runtimeAdmission: Boolean = false, separateStopAcceptance: Boolean = false)
    extends Module {
    require(slots >= 1 && slots <= 16 && isPow2(slots))
    require(ramBase >= 0 && ramBytes > 0 && ramBase + ramBytes <= (BigInt(1) << 64))
    require(maxFrameBytes > 0)
    private val slotBits = log2Ceil(slots).max(1)
    private val countBits = log2Ceil(slots + 1)
    private val addressBits = (ramBase + ramBytes - 1).bitLength.max(4)
    private val lengthBits = log2Ceil(BigInt(maxFrameBytes) + 1)
    private val wordCountBits = log2Ceil((BigInt(maxFrameBytes) + 7) / 8 + 1)
    val io = IO(new Bundle {
        val offset = Input(UInt(8.W))
        val data = Input(UInt(64.W))
        val accessWrite = Input(Bool())
        val write = Input(Bool())
        // Transport acceptance plus address/size/mask/write checks ONLY. STOP
        // legality needs enabled, not a different command's descriptor proof.
        val acceptedWrite = if (separateStopAcceptance) Some(Input(Bool())) else None
        val known = Output(Bool())
        val allowed = Output(Bool())
        val readData = Output(UInt(64.W))
        val engineIdle = Input(Bool())
        // Keep launch admission separate from engine emptiness / MMIO legality.
        val launchAllowed = if (runtimeAdmission) Some(Input(Bool())) else None
        val engineDone = Input(Bool())
        val engineFailed = Input(Bool())
        val engineBytes = Input(UInt(16.W))
        val consumeDone = Output(Bool())
        val launch = Valid(new Bundle { val address = UInt(64.W); val length = UInt(64.W) })
        val enabled = Output(Bool())
        val irq = Output(Bool())
        val work = Output(Bool())
    })
    val enabled = RegInit(false.B)
    val stopped = RegInit(false.B)
    val stageAddress = RegInit(0.U(64.W))
    val stageLength = RegInit(0.U(64.W))
    // Derive the narrow word count on the same accepted field write, not on
    // POST's combinational admission path. Invalid full64 lengths remain illegal.
    val stageLengthValid = RegInit(false.B)
    val stageWords = RegInit(0.U(wordCountBits.W))
    val owned = RegInit(VecInit(Seq.fill(slots)(false.B)))
    val addressWords = Reg(Vec(slots, UInt((addressBits - 3).W)))
    val lengths = Reg(Vec(slots, UInt(lengthBits.W)))
    val results = Reg(Vec(slots, UInt(17.W)))
    val postIndex = RegInit(0.U(slotBits.W))
    val launchIndex = RegInit(0.U(slotBits.W))
    val headIndex = RegInit(0.U(slotBits.W))
    val activeIndex = Reg(UInt(slotBits.W))
    val active = RegInit(false.B)
    val owners = RegInit(0.U(countBits.W))
    val pending = RegInit(0.U(countBits.W))
    val completed = RegInit(0.U(countBits.W))
    def at[T <: Data](vec: Vec[T], index: UInt): T = if (slots == 1) vec(0) else vec(index)
    def address(index: UInt): UInt = Cat(at(addressWords, index), 0.U(3.W))
    def next(index: UInt): UInt = if (slots == 1) 0.U else index + 1.U
    val addressHighClear = if (addressBits == 64) true.B else !stageAddress(63, addressBits).orR
    val endWord = stageAddress(addressBits - 1, 3) +& stageWords
    // The rounded endpoint is word-aligned, so flooring the aperture endpoint
    // is exact even for an unaligned aperture. +& retains a possible 2^64 end.
    val descriptorValid = addressHighClear && stageAddress(2, 0) === 0.U &&
        stageAddress >= ramBase.U(65.W) && stageLengthValid &&
        endWord <= ((ramBase + ramBytes) >> 3).U
    val postStart = stageAddress(addressBits - 1, 0)
    val postLength = stageLength(lengthBits - 1, 0)
    val overlaps = (0 until slots).map { i =>
        val start = Cat(addressWords(i), 0.U(3.W))
        // Full-width legality independently gates POST. Owned fields have
        // already passed that proof, so only bounded bits affect overlap.
        owned(i) && postStart < (start +& lengths(i)) && start < (postStart +& postLength)
    }.reduce(_ || _)
    val empty = owners === 0.U && !active && io.engineIdle
    val commandValid = MuxLookup(io.data, false.B)(Seq(
        1.U -> (!enabled && empty), 2.U -> (enabled && empty),
        4.U -> (enabled && !stopped && owners < slots.U && descriptorValid && !overlaps),
        8.U -> (enabled && completed =/= 0.U), 16.U -> enabled))
    io.known := Seq(224, 232, 240, 248).map(n => io.offset === n.U).reduce(_ || _)
    io.allowed := io.known && (!io.accessWrite || io.offset === 224.U || io.offset === 232.U ||
        (io.offset === 240.U && commandValid))
    io.readData := MuxLookup(io.offset, 0.U(64.W))(Seq(
        224.U -> Mux(completed =/= 0.U, address(headIndex), 0.U),
        232.U -> Mux(completed =/= 0.U, at(results, headIndex), 0.U),
        240.U -> (enabled.asUInt | (stopped.asUInt << 1)),
        248.U -> (pending | (completed << 8) | (active.asUInt << 16) |
            (stopped.asUInt << 17) | (enabled.asUInt << 18))))
    val stopCommand = io.offset === 240.U && io.data === 16.U
    val acceptedStop = if (separateStopAcceptance)
        io.acceptedWrite.get && stopCommand && enabled
        else io.write && stopCommand
    if (separateStopAcceptance) {
        assert(acceptedStop === (io.write && stopCommand),
            "independent STOP acceptance disagrees with accepted legal MMIO write")
    }
    val post = io.write && io.offset === 240.U && io.data === 4.U
    val pop = io.write && io.offset === 240.U && io.data === 8.U
    val consume = WireDefault(false.B)
    val complete = WireDefault(false.B)
    when(post =/= pop) { owners := Mux(post, owners + 1.U, owners - 1.U) }
    when(post =/= consume) { pending := Mux(post, pending + 1.U, pending - 1.U) }
    when(complete =/= pop) { completed := Mux(complete, completed + 1.U, completed - 1.U) }
    when(io.write) {
        assert(io.allowed)
        switch(io.offset) {
            is(224.U) { stageAddress := io.data }
            is(232.U) {
                stageLength := io.data
                stageLengthValid := io.data =/= 0.U && io.data <= maxFrameBytes.U
                // pad also supports constructor lengths smaller than one word.
                stageWords := (io.data(lengthBits - 1, 0).pad(4) >> 3) +& io.data(2, 0).orR.asUInt
            }
            is(240.U) {
                when(io.data === 1.U || io.data === 2.U) {
                    enabled := io.data === 1.U; stopped := false.B
                    postIndex := 0.U; launchIndex := 0.U; headIndex := 0.U
                }
                when(io.data === 16.U) { stopped := true.B }
            }
        }
    }
    when(post) {
        at(owned, postIndex) := true.B
        at(addressWords, postIndex) := stageAddress(addressBits - 1, 3)
        at(lengths, postIndex) := stageLength(lengthBits - 1, 0)
        postIndex := next(postIndex)
    }
    when(pop) { at(owned, headIndex) := false.B; headIndex := next(headIndex) }
    io.launch.valid := false.B
    io.launch.bits.address := address(launchIndex)
    io.launch.bits.length := at(lengths, launchIndex)
    io.consumeDone := enabled && active && io.engineDone
    when(io.consumeDone) {
        at(results, activeIndex) := io.engineBytes | (io.engineFailed.asUInt << 16)
        active := false.B; complete := true.B
    }
    // Runtime pause retains pending descriptors. An explicit software STOP is
    // still destructive and may cancel them even while fresh launches are paused.
    val launchIdle = if (runtimeAdmission) io.engineIdle &&
        (io.launchAllowed.get || stopped || acceptedStop)
        else io.engineIdle
    when(enabled && !active && launchIdle && pending =/= 0.U) {
        consume := true.B; launchIndex := next(launchIndex)
        // A STOP accepted in this cycle already prevents a fresh launch.
        when(stopped || acceptedStop) {
            at(results, launchIndex) := (1 << 16).U; complete := true.B
        }.otherwise {
            active := true.B; activeIndex := launchIndex; io.launch.valid := true.B
        }
    }
    io.enabled := enabled
    io.irq := enabled && completed =/= 0.U
    io.work := enabled && (active || pending =/= 0.U)
    assert(owners === PopCount(owned))
    assert(owners === pending +& completed + active.asUInt)
    assert(owners <= slots.U)
}
