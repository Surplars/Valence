package soc.core.pipeline

import chisel3._
import chisel3.util._

// class BTBEntrySet(val ways: Int, val tagBits: Int, val xlen: Int) extends Bundle {
//     val tags    = Vec(ways, UInt(tagBits.W))
//     val targets = Vec(ways, UInt(xlen.W))
//     val valids  = Vec(ways, Bool())
//     val plru    = UInt(3.W) // 3-bit PLRU for 4-way
// }

// class BPU_SetAssoc(XLEN: Int = 64, btbEntries: Int, phtEntries: Int, ghrBits: Int, rasDepth: Int) extends Module {
//     require(isPow2(btbEntries), "btbEntries must be power of two")
//     require(isPow2(phtEntries), "phtEntries must be power of two")
//     require(ghrBits > 0 && ghrBits <= 32, "ghrBits reasonable range")

//     val io = IO(new Bundle {
//         val pc_in = Input(UInt(XLEN.W))

//         val pred_valid  = Output(Bool())
//         val pred_taken  = Output(Bool())
//         val pred_target = Output(UInt(XLEN.W))

//         // update from EX (branch resolution)
//         val update_valid   = Input(Bool())
//         val update_pc      = Input(UInt(XLEN.W))
//         val update_taken   = Input(Bool())
//         val update_target  = Input(UInt(XLEN.W))
//         val update_is_call = Input(Bool())
//         val update_is_ret  = Input(Bool())

//         // checkpointing: alloc id + restore id (same protocol as before)
//         val chkpt_alloc   = Output(UInt(5.W))
//         val chkpt_restore = Input(UInt(5.W))
//     })

//     // parameters
//     val ways        = 4
//     val sets        = btbEntries / ways
//     val btbIdxBits  = log2Ceil(sets)        // index into sets
//     val phtIdxBits  = log2Ceil(phtEntries)
//     val tagBits     = XLEN - btbIdxBits - 2 // drop low 2 bits alignment
//     val CHKPT_WIDTH = 5
//     val CHKPT_NONE  = ((1 << CHKPT_WIDTH) - 1).U(CHKPT_WIDTH.W)

//     // BTB: an array of sets, each set holds 'ways' entries + PLRU bits
//     val btbSets = RegInit(VecInit(Seq.fill(sets) {
//         val s = Wire(new BTBEntrySet(ways, tagBits, XLEN))
//         s.tags    := VecInit(Seq.fill(ways)(0.U(tagBits.W)))
//         s.targets := VecInit(Seq.fill(ways)(0.U(XLEN.W)))
//         s.valids  := VecInit(Seq.fill(ways)(false.B))
//         s.plru    := 0.U
//         s
//     }))

//     // PHT: gshare style (2-bit counters)
//     val pht = RegInit(VecInit(Seq.fill(phtEntries)(1.U(2.W))))
//     val ghr = RegInit(0.U(ghrBits.W))

//     // checkpoint array for speculative GHR
//     val chkptCount    = 1 << CHKPT_WIDTH
//     val chkptArray    = RegInit(VecInit(Seq.fill(chkptCount)(0.U(ghrBits.W))))
//     val chkptAllocPtr = RegInit(0.U(CHKPT_WIDTH.W))

//     // RAS
//     val ras    = RegInit(VecInit(Seq.fill(rasDepth)(0.U(XLEN.W))))
//     val rasPtr = RegInit(0.U(log2Ceil(rasDepth + 1).W))

//     // helper: extract set index and tag from pc
//     def setIndex(pc: UInt): UInt = (pc >> 2)(btbIdxBits - 1, 0)
//     def tagOf(pc: UInt): UInt    = (pc >> (2 + btbIdxBits))(tagBits - 1, 0)

//     // pht index (gshare)
//     def pcPhtIndex(pc: UInt): UInt                = (pc >> 2)(phtIdxBits - 1, 0)
//     def gshareIndex(pc: UInt, curGhr: UInt): UInt = {
//         if (phtIdxBits <= ghrBits) pcPhtIndex(pc) ^ curGhr(phtIdxBits - 1, 0)
//         else pcPhtIndex(pc) ^ Cat(Fill(phtIdxBits - ghrBits, 0.U), curGhr)
//     }

//     // PLRU helper functions for 4-way tree (bits = UInt(3.W): b2=root, b1=left, b0=right)
//     def plruVictim(plruBits: UInt): UInt = {
//         val root  = plruBits(2)
//         val left  = plruBits(1)
//         val right = plruBits(0)
//         // if root == 0 -> choose left subtree; left==0 => way0 else way1
//         // if root == 1 -> choose right subtree; right==0 => way2 else way3
//         Mux(root === 0.U, Mux(left === 0.U, 0.U(2.W), 1.U(2.W)), Mux(right === 0.U, 2.U(2.W), 3.U(2.W)))
//     }
//     def plruUpdateOnAccess(plruBits: UInt, way: UInt): UInt = {
//         // way 0 -> root:=1, left:=1
//         // way 1 -> root:=1, left:=0
//         // way 2 -> root:=0, right:=1
//         // way 3 -> root:=0, right:=0
//         MuxLookup(way, plruBits)(
//             Seq(
//                 0.U -> Cat(1.U(1.W), 1.U(1.W), 1.U(1.W)), // encoding bits: b2(root), b1(left), b0(right)
//                 1.U -> Cat(1.U(1.W), 0.U(1.W), plruBits(0)),
//                 2.U -> Cat(0.U(1.W), plruBits(1), 1.U(1.W)),
//                 3.U -> Cat(0.U(1.W), plruBits(1), 0.U(1.W))
//             )
//         )
//         // Note: the above sets bits along the path; other bits preserved as appropriate.
//     }

//     // --- prediction (combinational) ---
//     val idx = setIndex(io.pc_in)
//     val tag = tagOf(io.pc_in)
//     val set = btbSets(idx)

//     // compute hit vector for the set
//     val hitVec = Wire(Vec(ways, Bool()))
//     for (w <- 0 until ways) {
//         hitVec(w) := set.valids(w) && (set.tags(w) === tag)
//     }
//     val anyHit = hitVec.asUInt.orR
//     // if multiple hits (shouldn't normally happen) take first priority (PriorityEncoder)
//     val hitWay    = PriorityEncoder(hitVec.asUInt) // UInt(width = 2)
//     val hitTarget = set.targets(hitWay)

//     // PHT index uses current GHR (we may speculatively update later)
//     val phtIndex     = gshareIndex(io.pc_in, ghr)
//     val phtCtr       = pht(phtIndex)
//     val phtPredTaken = phtCtr(1) === 1.U

//     val predTaken  = anyHit && phtPredTaken
//     val predTarget = Mux(anyHit, hitTarget, 0.U(XLEN.W))

//     io.pred_valid  := anyHit
//     io.pred_taken  := predTaken
//     io.pred_target := predTarget

//     // checkpoint alloc logic as before: allocate a slot if we do a speculative update (predTaken)
//     val allocId       = WireDefault(CHKPT_NONE)
//     val predSpecTaken = predTaken
//     when(predSpecTaken) { allocId := chkptAllocPtr }
//     io.chkpt_alloc := allocId

//     // speculative write of checkpoint array (sequential)
//     when(predSpecTaken) {
//         chkptArray(chkptAllocPtr) := ghr
//         chkptAllocPtr             := chkptAllocPtr + 1.U
//     }

//     // handle restore
//     when(io.chkpt_restore =/= CHKPT_NONE) {
//         val ridx = io.chkpt_restore
//         ghr := chkptArray(ridx)
//     }

//     // --- update on branch resolution (EX) ---
//     when(io.update_valid) {
//         // compute pht index at resolution time (use historical GHR at time of resolution)
//         val u_pht_index = gshareIndex(
//             io.update_pc,
//             ghr
//         ) // note: this uses current ghr; practical impl might need saved history; simplified here
//         val cur   = pht(u_pht_index)
//         val taken = io.update_taken
//         val nxt   = WireDefault(cur)
//         when(taken && cur =/= 3.U) { nxt := cur + 1.U }
//             .elsewhen(!taken && cur =/= 0.U) { nxt := cur - 1.U }
//         pht(u_pht_index) := nxt

//         // BTB update: if taken, write or update a way in the set; prefer updating existing way if tag matches,
//         // otherwise choose victim using PLRU
//         val u_idx = setIndex(io.update_pc)
//         val u_tag = tagOf(io.update_pc)
//         val set_u = btbSets(u_idx)

//         // find hit in the set
//         val u_hitVec = Wire(Vec(ways, Bool()))
//         for (w <- 0 until ways) u_hitVec(w) := set_u.valids(w) && (set_u.tags(w) === u_tag)
//         val u_anyHit = u_hitVec.asUInt.orR
//         val u_hitWay = PriorityEncoder(u_hitVec.asUInt)

//         when(io.update_taken) {
//             when(u_anyHit) {
//                 // update that way's target (and mark valid)
//                 set_u.targets(u_hitWay) := io.update_target
//                 set_u.valids(u_hitWay)  := true.B
//                 // update PLRU for that set to reflect access to u_hitWay
//                 set_u.plru := plruUpdateOnAccess(set_u.plru, u_hitWay)
//             }.otherwise {
//                 // allocate: choose PLRU victim
//                 val victim = plruVictim(set_u.plru)
//                 set_u.tags(victim)    := u_tag
//                 set_u.targets(victim) := io.update_target
//                 set_u.valids(victim)  := true.B
//                 // update PLRU to mark victim as most recently used
//                 set_u.plru := plruUpdateOnAccess(set_u.plru, victim)
//             }
//         }.otherwise {
//             // on not taken: optional: might invalidate entry or leave unchanged; here we leave unchanged
//         }

//         // RAS update
//         when(io.update_is_call) {
//             ras(rasPtr) := io.update_pc + 4.U
//             rasPtr      := Mux(rasPtr === (rasDepth - 1).U, (rasDepth - 1).U, rasPtr + 1.U)
//         }.elsewhen(io.update_is_ret) {
//             rasPtr := Mux(rasPtr === 0.U, 0.U, rasPtr - 1.U)
//         }

//         // update GHR with actual outcome
//         ghr := Cat(ghr(ghrBits - 2, 0), io.update_taken.asUInt)
//     }
// }

import chisel3._
import chisel3.util._

// 参数化配置：BTB 条目数
class BranchPredictor(val entries: Int = 512) extends Module {
  val io = IO(new Bundle {
    // --- 1. 预测阶段 (Fetch Stage) ---
    val req_pc = Input(UInt(64.W))  // 当前取指 PC
    
    // 预测结果
    val pred_valid  = Output(Bool())    // BTB 是否命中 (是否遇到过这条分支指令)
    val pred_taken  = Output(Bool())    // 预测方向 (True=跳, False=不跳)
    val pred_target = Output(UInt(64.W))// 预测的目标地址

    // --- 2. 更新阶段 (Execute/Writeback Stage) ---
    // 只有在该指令确实是 Branch/JAL/JALR 类型时才有效
    val update_valid  = Input(Bool())
    val update_pc     = Input(UInt(64.W))
    val update_target = Input(UInt(64.W)) // 实际计算出的跳转目标
    val update_taken  = Input(Bool())     // 实际是否跳转
    val update_is_br  = Input(Bool())     // 标记：这是否是一条条件分支指令(B-Type)
                                          // (JAL/JALR 总是跳转，不参考饱和计数器，但需要更新BTB)
  })

  val indexBits = log2Ceil(entries)
  // The C extension allows branch instructions and targets on 16-bit
  // boundaries. Index/tag by halfword address so adjacent compressed
  // instructions such as 0x...38 and 0x...3a do not alias in the BTB.
  val tagBits = 64 - indexBits - 1
  
  def getIndex(pc: UInt): UInt = pc(indexBits, 1)
  def getTag(pc: UInt): UInt = pc(63, indexBits + 1)

  // --------------------------------------------------------
  // 存储结构 (使用 Mem 替代 Reg(Vec) 以加速仿真并减少逻辑资源)
  // --------------------------------------------------------

  // 1. Valid Bit Array 
  // Valid 位通常还是建议保持为 Reg，因为我们需要复位重置它们
  // 对于 Mem 来说，如果不初始化，仿真一开始全是 X。但 Valid 必须以 False 开始。
  // 512 bit 的寄存器开销很小，所以 Valid Array 保持 RegInit。
  val valid_array = RegInit(VecInit(Seq.fill(entries)(false.B)))

  // 2. BTB Tag Array - 存储 PC 的高位
  // 使用 Mem (SyncReadMem 是同步读，Mem 是异步读，这里必须用异步读 Mem 才能单周期出结果)
  val tag_array = Mem(entries, UInt(tagBits.W))

  // 3. BTB Target Array - 存储目标跳转地址
  val target_array = Mem(entries, UInt(64.W))

  // 4. BHT (Branch History Table) - 饱和计数器
  // 虽然可以使用 Mem，但因为需要 Read-Modify-Write (读出旧值->加减->写回)，
  // 使用 Mem 在同一个周期内做 RMW 可能会有写透传（Write-Through）或旧值问题。
  // 为了安全和简单，且 BHT 位宽很小(2bit)，这里为了仿真速度也可以用 Mem，
  // 但要注意先读再写逻辑。Chisel Mem 默认支持同周期读写（返回旧值或新值取决于实现）。
  // 实际上，BHT 更新是在 EX 阶段（写），而预测是在 IF 阶段（读），两个操作几乎从不在同一个周期对同一个地址操作。
  // 所以 Read-Modify-Write 是针对 update 逻辑的：update 自身需要读出旧值。
  // Chisel Mem 的读端口是组合逻辑，所以可以： old_cnt = mem(upd_idx) -> new_cnt = calc(old_cnt) -> mem(upd_idx) := new_cnt
  val bht_array = Mem(entries, UInt(2.W))

  // BHT 只在 BTB valid/tag 命中时参与预测。更新侧对新分配项显式初始化计数器，
  // 避免依赖未初始化 Mem 的旧值。
  
  // --------------------------------------------------------
  // 1. 预测逻辑 (Fetch Stage - 组合逻辑)
  // --------------------------------------------------------

  val req_idx = getIndex(io.req_pc)
  val req_tag = getTag(io.req_pc)

  // 读出数据 (Mem 的读是组合逻辑，表现像数组索引)
  val hit_valid  = valid_array(req_idx)
  val hit_tag    = tag_array(req_idx)
  val hit_target = target_array(req_idx)
  
  // BHT 读取：即使 Mem 里是垃圾值，只要 hit_valid 是 false，我们就不会用它
  // 只有当 valid 为 true 时，意味着我们以前写过它，那里面肯定已经是有效值了。
  val hit_cnt    = bht_array(req_idx)

  // 判断命中：Valid 为 1 且 Tag 匹配
  val btb_hit = hit_valid && (hit_tag === req_tag)

  // 预测方向
  val is_taken_prediction = hit_cnt(1) // 最高位为 1 则预测跳转

  io.pred_valid  := btb_hit
  io.pred_taken  := btb_hit && is_taken_prediction
  io.pred_target := hit_target

  // --------------------------------------------------------
  // 2. 更新逻辑 (Ex/WB Stage - 时序逻辑)
  // --------------------------------------------------------

  val upd_idx = getIndex(io.update_pc)
  val upd_tag = getTag(io.update_pc)
  
  val upd_valid = valid_array(upd_idx)
  val upd_hit = upd_valid && (tag_array(upd_idx) === upd_tag)
  val old_cnt = bht_array(upd_idx)
  
  when(io.update_valid) {
    // Not-taken conditional branches that miss the BTB are not allocated.
    // This keeps one-off forward branches from polluting the direct-mapped BTB.
    val shouldWriteBtb = !io.update_is_br || io.update_taken || upd_hit
    when(shouldWriteBtb) {
      valid_array(upd_idx)  := true.B
      tag_array(upd_idx)    := upd_tag
      target_array(upd_idx) := io.update_target
    }

    val base_cnt = Mux(upd_hit, old_cnt, Mux(io.update_taken, 2.U, 1.U))
    val new_cnt = WireDefault(base_cnt)

    when(io.update_is_br) {
      // 条件分支：使用饱和加减逻辑
      when(io.update_taken) {
        when(base_cnt =/= 3.U) { new_cnt := base_cnt + 1.U }
      }.otherwise {
        when(base_cnt =/= 0.U) { new_cnt := base_cnt - 1.U }
      }
    }.otherwise {
      // 无条件跳转 (JAL, JALR)：直接设为 Strong Taken (11)
      new_cnt := 3.U
    }
    
    when(shouldWriteBtb) {
      bht_array(upd_idx) := new_cnt
    }
  }
}
