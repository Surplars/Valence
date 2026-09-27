package soc.core.ooo

import chisel3._
import soc.ip.memory.{CacheStallEvents, SharedReadCache}

/** Optional shared cache below AtomicDataMemory, never a private CPU cache. */
class CachedDataMemory(lines: Int = 16, bytes: BigInt = 4096) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val memory   = new DataPort
        val stalls   = Output(new CacheStallEvents)
        val hit      = Output(Bool())
        val miss     = Output(Bool())
    })
    val cache = Module(new SharedReadCache(bytes = bytes, lines = lines))
    io.stalls                              := cache.io.stalls
    io.hit                                 := cache.io.hit
    io.miss                                := cache.io.miss
    cache.io.upstream.request.valid        := io.upstream.request.valid
    cache.io.upstream.request.bits.address := io.upstream.request.bits.address
    cache.io.upstream.request.bits.write   := io.upstream.request.bits.write
    cache.io.upstream.request.bits.size    := io.upstream.request.bits.size
    cache.io.upstream.request.bits.mask    := io.upstream.request.bits.mask
    cache.io.upstream.request.bits.data    := io.upstream.request.bits.data
    io.upstream.request.ready              := cache.io.upstream.request.ready
    io.upstream.response.valid             := cache.io.upstream.response.valid
    io.upstream.response.bits.data         := cache.io.upstream.response.bits.data
    io.upstream.response.bits.error        := cache.io.upstream.response.bits.error
    io.upstream.response.bits.pageFault    := false.B
    cache.io.upstream.response.ready       := io.upstream.response.ready
    io.memory.request.valid                := cache.io.memory.request.valid
    io.memory.request.bits                 := 0.U.asTypeOf(new DataRequest)
    io.memory.request.bits.address         := cache.io.memory.request.bits.address
    io.memory.request.bits.write           := cache.io.memory.request.bits.write
    io.memory.request.bits.size            := cache.io.memory.request.bits.size
    io.memory.request.bits.mask            := cache.io.memory.request.bits.mask
    io.memory.request.bits.data            := cache.io.memory.request.bits.data
    cache.io.memory.request.ready          := io.memory.request.ready
    cache.io.memory.response.valid         := io.memory.response.valid
    cache.io.memory.response.bits.data     := io.memory.response.bits.data
    cache.io.memory.response.bits.error    := io.memory.response.bits.error
    io.memory.response.ready               := cache.io.memory.response.ready
    when(io.upstream.request.valid) { assert(!io.upstream.request.bits.atomic, "cache must follow atomic execution") }
}
