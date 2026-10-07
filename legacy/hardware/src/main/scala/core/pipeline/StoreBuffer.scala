package soc.core.pipeline

import chisel3._
import chisel3.util._

class StoreBufferEntry(val AW: Int, val DW: Int) extends Bundle {
    val valid = Bool()
    val pc    = UInt(AW.W)
    val vaddr = UInt(AW.W)
    val addr  = UInt(AW.W)
    val data  = UInt(DW.W)
    val mask  = UInt((DW / 8).W)
    val size  = UInt(3.W)
}

class StoreBuffer(val entries: Int, val AW: Int, val DW: Int) extends Module {
    val io = IO(new Bundle {
        // Enq (来自 LSU Core 逻辑)
        val enq_valid = Input(Bool())
        val enq_pc    = Input(UInt(AW.W))
        val enq_vaddr = Input(UInt(AW.W))
        val enq_addr  = Input(UInt(AW.W))
        val enq_data  = Input(UInt(DW.W))
        val enq_mask  = Input(UInt((DW / 8).W))
        val enq_size  = Input(UInt(3.W))
        val enq_ready = Output(Bool())
        // Search (来自 Load 指令 Forwarding)
        val search_addr = Input(UInt(AW.W))
        val search_mask = Input(UInt((DW / 8).W))
        val search_hit  = Output(Bool())
        val search_conflict = Output(Bool())
        val search_data = Output(UInt(DW.W))
        // Deq (发往 Memory/Bus)
        val deq_valid = Output(Bool())
        val deq_pc    = Output(UInt(AW.W))
        val deq_vaddr = Output(UInt(AW.W))
        val deq_addr  = Output(UInt(AW.W))
        val deq_data  = Output(UInt(DW.W))
        val deq_mask  = Output(UInt((DW / 8).W))
        val deq_size  = Output(UInt(3.W))
        val deq_ready = Input(Bool())
    })

    val buffer = RegInit(VecInit(Seq.fill(entries) {
        0.U.asTypeOf(new StoreBufferEntry(AW, DW))
    }))

    val head  = RegInit(0.U(log2Ceil(entries).W)) // 读指针（出队）
    val tail  = RegInit(0.U(log2Ceil(entries).W)) // 写指针（入队）
    val count = RegInit(0.U(log2Ceil(entries + 1).W))

    def ptrNext(ptr: UInt): UInt = Mux(ptr === (entries - 1).U, 0.U, ptr + 1.U)

    io.deq_valid := count > 0.U

    val deq_fire = io.deq_valid && io.deq_ready
    // When the FIFO is full but the oldest store drains this cycle, the freed
    // slot can accept a new store without adding a pipeline bubble.
    io.enq_ready := count < entries.U || deq_fire
    val enq_fire = io.enq_valid && io.enq_ready

    when(enq_fire) {
        buffer(tail).valid := true.B
        buffer(tail).pc    := io.enq_pc
        buffer(tail).vaddr := io.enq_vaddr
        buffer(tail).addr  := io.enq_addr
        buffer(tail).data  := io.enq_data
        buffer(tail).mask  := io.enq_mask
        buffer(tail).size  := io.enq_size
        tail               := ptrNext(tail)
    }

    io.deq_pc    := buffer(head).pc
    io.deq_vaddr := buffer(head).vaddr
    io.deq_addr  := buffer(head).addr
    io.deq_data  := buffer(head).data
    io.deq_mask  := buffer(head).mask
    io.deq_size  := buffer(head).size

    when(deq_fire) {
        buffer(head).valid := false.B
        head               := ptrNext(head)
    }

    switch(Cat(enq_fire, deq_fire)) {
        is("b10".U) {
            count := count + 1.U
        }
        is("b01".U) {
            count := count - 1.U
        }
    }

    def ptrPrev(ptr: UInt): UInt = Mux(ptr === 0.U, (entries - 1).U, ptr - 1.U)
    def ptrMinus(ptr: UInt, steps: Int): UInt = {
        var result = ptr
        for (_ <- 0 until steps) {
            result = ptrPrev(result)
        }
        result
    }

    val hitByAge  = Wire(Vec(entries, Bool()))
    val dataByAge = Wire(Vec(entries, UInt(DW.W)))
    val searchBeatAddr = io.search_addr(AW - 1, log2Ceil(DW / 8))

    for (age <- 0 until entries) {
        val idx = ptrMinus(tail, age + 1)
        val entryBeatAddr = buffer(idx).addr(AW - 1, log2Ceil(DW / 8))
        val sameBeat = entryBeatAddr === searchBeatAddr
        hitByAge(age) := buffer(idx).valid && sameBeat && ((buffer(idx).mask & io.search_mask) === io.search_mask)
        dataByAge(age) := buffer(idx).data
    }

    val conflictByAge = Wire(Vec(entries, Bool()))
    for (age <- 0 until entries) {
        val idx = ptrMinus(tail, age + 1)
        val entryBeatAddr = buffer(idx).addr(AW - 1, log2Ceil(DW / 8))
        val sameBeat = entryBeatAddr === searchBeatAddr
        val overlap = (buffer(idx).mask & io.search_mask).orR
        // If a load overlaps an older store but the store buffer cannot supply
        // every requested byte lane, the load must wait for the store to drain.
        // Otherwise byte/halfword loads can bypass pending wider stores and see
        // stale cache data.
        conflictByAge(age) := buffer(idx).valid && sameBeat && overlap && !hitByAge(age)
    }

    val newestHitOH = PriorityEncoderOH(hitByAge.asUInt)
    io.search_hit  := hitByAge.asUInt.orR
    io.search_conflict := conflictByAge.asUInt.orR
    io.search_data := Mux1H(newestHitOH, dataByAge)
}
