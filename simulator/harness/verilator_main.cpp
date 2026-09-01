#include <cstdio>
#include <cstring>
#include <string>
#include <sys/stat.h>
#include <filesystem>
#include <elf.h>
#include <cstdlib>
#include <cstdint>
#include <cerrno>
#include <cinttypes>
#include <fcntl.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <vector>
#include <algorithm>
#include <verilated.h>
#if VM_TRACE_FST
#include <verilated_fst_c.h>
using IonWaveTrace = VerilatedFstC;
#define ION_HAS_WAVE_TRACE 1
static constexpr const char *kWaveFormat = "FST";
static constexpr const char *kDefaultWavePath = "simulator/build/wave.fst";
#elif VM_TRACE_VCD
#include <verilated_vcd_c.h>
using IonWaveTrace = VerilatedVcdC;
#define ION_HAS_WAVE_TRACE 1
static constexpr const char *kWaveFormat = "VCD";
static constexpr const char *kDefaultWavePath = "simulator/build/wave.vcd";
#else
#define ION_HAS_WAVE_TRACE 0
static constexpr const char *kWaveFormat = "none";
static constexpr const char *kDefaultWavePath = "simulator/build/wave.fst";
#endif
#include "VSoc.h"
#include "VSoc___024root.h"
#include "VSoc_L1Cache.h"

#define RED "\033[31m"
#define GREEN "\033[32m"
#define YELLOW "\033[33m"
#define CEND "\033[0m"

#define BROM_BASE 0x80000000
#define ROM_SIZE 0x10000 // 64KB = 16384 words * 4 bytes
#define SRAM_BASE 0x10000000
#define FIRMWARE_SRAM_BASE 0x40000000
#define DEFAULT_SRAM_SIZE 0x10000
#define DEFAULT_FIRMWARE_SRAM_SIZE 0x01000000

#define MAX_SIM_CYCLES 10000
static const char *kPayloadElfPath = "simulator/build/payload/payload.elf";
vluint64_t sim_time = 0;

struct SimOptions;

void load_elf(VSoc *dut, const char *path);
void load_elf_to_regions(VSoc *dut, const char *path, uint64_t sram_base, size_t sram_size);
void load_blob_to_sram(VSoc *dut, const char *path, uint64_t paddr, uint64_t sram_base, size_t sram_size);
bool run_one_test(const std::string &bin_path,
				  const std::string &test_name, bool trace_en,
				  const std::string &expected_uart = "");
bool run_sim(const SimOptions &opts);

static bool env_enabled(const char *name)
{
	const char *value = std::getenv(name);
	return value != nullptr && value[0] != '\0' && std::strcmp(value, "0") != 0;
}

static uint64_t env_u64(const char *name, uint64_t fallback)
{
	const char *value = std::getenv(name);
	if (value == nullptr || value[0] == '\0')
		return fallback;
	char *end = nullptr;
	uint64_t parsed = std::strtoull(value, &end, 0);
	return end != value ? parsed : fallback;
}

static std::string env_string(const char *name, const char *fallback)
{
	const char *value = std::getenv(name);
	return value != nullptr && value[0] != '\0' ? value : fallback;
}

class WaveTraceWindow
{
  public:
	WaveTraceWindow(VSoc *dut, bool requested)
	    : requested_(requested),
	      path_(env_string("ION_TRACE_WAVE_PATH", kDefaultWavePath)),
	      scope_(env_string("ION_TRACE_WAVE_SCOPE", "")),
	      depth_((int)std::max<uint64_t>(1, std::min<uint64_t>(env_u64("ION_TRACE_WAVE_DEPTH", 99), 1024))),
	      start_tick_(env_u64("ION_TRACE_WAVE_START", 0)),
	      stop_tick_(env_u64("ION_TRACE_WAVE_STOP", UINT64_MAX)),
	      trigger_pc_(env_u64("ION_TRACE_WAVE_PC", UINT64_MAX)),
	      length_(env_u64("ION_TRACE_WAVE_LEN", 0)),
	      triggered_(trigger_pc_ == UINT64_MAX),
	      trigger_tick_(start_tick_)
	{
#if ION_HAS_WAVE_TRACE
		if (!requested_)
			return;
		if (start_tick_ > stop_tick_)
		{
			done_ = true;
			printf("[trace]: invalid empty window: start_tick=%" PRIu64 " is after stop_tick=%" PRIu64 "\n",
			       start_tick_,
			       stop_tick_);
			return;
		}
		const std::filesystem::path wave_path(path_);
		const std::filesystem::path parent = wave_path.parent_path();
		if (!parent.empty() && !std::filesystem::exists(parent))
		{
			done_ = true;
			printf("[trace]: output directory does not exist: %s\n", parent.c_str());
			return;
		}
		trace_ = new IonWaveTrace;
		// Verilator requires tracing to be enabled before the first eval().
		Verilated::traceEverOn(true);
		dut->trace(trace_, depth_);
		printf("[trace]: armed format=%s path=%s start_tick=%" PRIu64 " stop_tick=%" PRIu64
		       "%s",
		       kWaveFormat,
		       path_.c_str(),
		       start_tick_,
		       stop_tick_,
		       scope_.empty() ? "" : " scoped");
		if (trigger_pc_ != UINT64_MAX)
			printf(" trigger_pc=0x%016" PRIx64, trigger_pc_);
		if (length_ != 0)
			printf(" len=%" PRIu64, length_);
		if (!scope_.empty())
			printf(" scope=%s scope_depth=%d", scope_.c_str(), depth_);
		printf("\n");
#else
		(void)dut;
		if (requested_)
			printf("[trace]: ION_TRACE_WAVE requested, but this binary was built without TRACE=1; wave disabled.\n");
#endif
	}

	~WaveTraceWindow()
	{
		close(0, false);
#if ION_HAS_WAVE_TRACE
		delete trace_;
#endif
	}

	void sample(VSoc *dut, uint64_t tick)
	{
#if ION_HAS_WAVE_TRACE
		if (!requested_ || done_)
			return;

		if (!triggered_)
		{
			if (tick > stop_tick_)
			{
				done_ = true;
				printf("[trace]: PC trigger expired at stop_tick=%" PRIu64
				       " without matching pc=0x%016" PRIx64 "\n",
				       stop_tick_,
				       trigger_pc_);
				return;
			}
			if (tick < start_tick_)
				return;
			const bool commit_hit = dut->clock && dut->io_debug_retire &&
			                        (uint64_t)dut->io_debug_commitPc == trigger_pc_;
			const bool trap_hit = dut->clock && dut->io_debug_arch_event_valid &&
			                      (uint64_t)dut->io_debug_arch_event_pc == trigger_pc_;
			if (!commit_hit && !trap_hit)
				return;
			triggered_ = true;
			trigger_tick_ = tick;
			printf("[trace]: PC trigger matched at tick=%" PRIu64 " pc=0x%016" PRIx64 "\n",
			       tick,
			       trigger_pc_);
		}

		if (tick < start_tick_)
			return;

		uint64_t last_tick = stop_tick_;
		if (length_ != 0)
		{
			const uint64_t length_delta = length_ - 1;
			const uint64_t length_last = trigger_tick_ > UINT64_MAX - length_delta
			                                 ? UINT64_MAX
			                                 : trigger_tick_ + length_delta;
			last_tick = std::min(last_tick, length_last);
		}
		if (tick > last_tick)
		{
			close(tick, true);
			return;
		}

		if (!open_)
		{
			if (!scope_.empty())
				trace_->dumpvars(depth_, scope_);
			trace_->open(path_.c_str());
			open_ = true;
			printf("[trace]: recording started at tick=%" PRIu64 "\n", tick);
		}
		trace_->dump(tick);
		last_dump_tick_ = tick;
		if (tick == last_tick)
			close(tick, true);
#else
		(void)dut;
		(void)tick;
#endif
	}

	void close(uint64_t tick, bool announce = true)
	{
#if ION_HAS_WAVE_TRACE
		if (open_)
		{
			trace_->close();
			open_ = false;
			if (announce)
				printf("[trace]: recording stopped at tick=%" PRIu64 " path=%s\n",
				       last_dump_tick_,
				       path_.c_str());
		}
		else if (announce && requested_ && trigger_pc_ != UINT64_MAX && !triggered_ && !done_)
		{
			printf("[trace]: simulation ended at tick=%" PRIu64
			       " without matching pc=0x%016" PRIx64 "; no wave file was written\n",
			       tick,
			       trigger_pc_);
		}
		done_ = true;
#else
		(void)tick;
		(void)announce;
#endif
	}

  private:
	bool requested_ = false;
	std::string path_;
	std::string scope_;
	int depth_ = 99;
	uint64_t start_tick_ = 0;
	uint64_t stop_tick_ = UINT64_MAX;
	uint64_t trigger_pc_ = UINT64_MAX;
	uint64_t length_ = 0;
	bool triggered_ = true;
	uint64_t trigger_tick_ = 0;
	bool open_ = false;
	bool done_ = false;
	uint64_t last_dump_tick_ = 0;
#if ION_HAS_WAVE_TRACE
	IonWaveTrace *trace_ = nullptr;
#endif
};

enum class ArchTraceKind : uint8_t
{
	Commit,
	Trap
};

struct ArchTraceEntry
{
	ArchTraceKind kind = ArchTraceKind::Commit;
	uint64_t sequence = 0;
	uint64_t retire_index = 0;
	uint64_t cycle = 0;
	uint64_t tick = 0;
	uint64_t pc = 0;
	uint64_t data = 0;
	uint64_t cause = 0;
	uint64_t tval = 0;
	uint64_t satp = 0;
	uint64_t mepc = 0;
	uint64_t sepc = 0;
	uint64_t mcause = 0;
	uint64_t scause = 0;
	uint32_t instr = 0;
	uint8_t instr_len = 0;
	uint8_t rd = 0;
	uint8_t privilege = 0;
	bool wen = false;
	bool skip = false;
	bool interrupt = false;
};

class ArchitecturalHistory
{
  public:
	ArchitecturalHistory(size_t capacity, bool stream)
	    : ring_(capacity), stream_(stream)
	{
	}

	void sample(VSoc *dut, uint64_t cycle, uint64_t tick)
	{
		if (dut->io_debug_retire)
		{
			ArchTraceEntry entry;
			entry.kind = ArchTraceKind::Commit;
			entry.sequence = ++event_count_;
			entry.retire_index = ++retired_count_;
			entry.cycle = cycle;
			entry.tick = tick;
			entry.pc = dut->io_debug_commitPc;
			entry.instr = dut->io_debug_commitInstr;
			entry.instr_len = dut->io_debug_commitInstrLen == 2 ? 2 : 4;
			entry.wen = dut->io_debug_commitWen;
			entry.rd = dut->io_debug_commitWdest;
			entry.data = dut->io_debug_commitWdata;
			entry.skip = dut->io_debug_commitSkip;
			entry.privilege = dut->io_debug_csr_snapshot_privilegeMode;
			entry.satp = dut->io_debug_csr_snapshot_satp;
			push(entry);
		}

		if (dut->io_debug_arch_event_valid)
		{
			ArchTraceEntry entry;
			entry.kind = ArchTraceKind::Trap;
			entry.sequence = ++event_count_;
			entry.retire_index = retired_count_;
			entry.cycle = cycle;
			entry.tick = tick;
			entry.pc = dut->io_debug_arch_event_pc;
			entry.instr = dut->io_debug_arch_event_instr;
			entry.interrupt = dut->io_debug_arch_event_interrupt;
			entry.cause = dut->io_debug_arch_event_cause;
			entry.tval = dut->io_debug_arch_event_tval;
			entry.privilege = dut->io_debug_csr_snapshot_privilegeMode;
			entry.satp = dut->io_debug_csr_snapshot_satp;
			entry.mepc = dut->io_debug_csr_snapshot_mepc;
			entry.sepc = dut->io_debug_csr_snapshot_sepc;
			entry.mcause = dut->io_debug_csr_snapshot_mcause;
			entry.scause = dut->io_debug_csr_snapshot_scause;
			push(entry);
		}
	}

	void dump(const char *reason) const
	{
		printf("[arch-history]: reason=%s kept=%zu total=%" PRIu64 " retired=%" PRIu64
		       " traps=%" PRIu64 "\n",
		       reason,
		       count_,
		       event_count_,
		       retired_count_,
		       trap_count_);
		if (count_ == 0)
			return;
		const size_t oldest = (next_ + ring_.size() - count_) % ring_.size();
		for (size_t i = 0; i < count_; ++i)
			print(ring_[(oldest + i) % ring_.size()]);
	}

	uint64_t retired_count() const { return retired_count_; }

  private:
	void push(const ArchTraceEntry &entry)
	{
		if (entry.kind == ArchTraceKind::Trap)
			++trap_count_;
		if (!ring_.empty())
		{
			ring_[next_] = entry;
			next_ = (next_ + 1) % ring_.size();
			count_ = std::min(count_ + 1, ring_.size());
		}
		if (stream_)
			print(entry);
	}

	static void print(const ArchTraceEntry &entry)
	{
		if (entry.kind == ArchTraceKind::Commit)
		{
			printf("[arch-commit]: seq=%" PRIu64 " retire=%" PRIu64 " cycle=%" PRIu64
			       " tick=%" PRIu64 " pc=0x%016" PRIx64 " instr=0x%08x len=%u"
			       " priv_after=%u satp=0x%016" PRIx64 " skip=%u wen=%u rd=%u wdata=0x%016" PRIx64 "\n",
			       entry.sequence,
			       entry.retire_index,
			       entry.cycle,
			       entry.tick,
			       entry.pc,
			       entry.instr,
			       (unsigned)entry.instr_len,
			       (unsigned)entry.privilege,
			       entry.satp,
			       entry.skip ? 1U : 0U,
			       entry.wen ? 1U : 0U,
			       (unsigned)entry.rd,
			       entry.data);
			return;
		}

		printf("[arch-trap]: seq=%" PRIu64 " retire=%" PRIu64 " cycle=%" PRIu64
		       " tick=%" PRIu64 " type=%s cause=0x%016" PRIx64 " pc=0x%016" PRIx64
		       " instr=0x%08x tval=0x%016" PRIx64 " priv_after=%u satp=0x%016" PRIx64
		       " mepc=0x%016" PRIx64 " sepc=0x%016" PRIx64
		       " mcause=0x%016" PRIx64 " scause=0x%016" PRIx64 "\n",
		       entry.sequence,
		       entry.retire_index,
		       entry.cycle,
		       entry.tick,
		       entry.interrupt ? "interrupt" : "exception",
		       entry.cause,
		       entry.pc,
		       entry.instr,
		       entry.tval,
		       (unsigned)entry.privilege,
		       entry.satp,
		       entry.mepc,
		       entry.sepc,
		       entry.mcause,
		       entry.scause);
	}

	std::vector<ArchTraceEntry> ring_;
	bool stream_ = false;
	size_t next_ = 0;
	size_t count_ = 0;
	uint64_t event_count_ = 0;
	uint64_t retired_count_ = 0;
	uint64_t trap_count_ = 0;
};

static bool would_block_errno(int err)
{
	if (err == EAGAIN)
		return true;
#if EWOULDBLOCK != EAGAIN
	if (err == EWOULDBLOCK)
		return true;
#endif
	return false;
}

struct SimOptions
{
	std::string elf_path = kPayloadElfPath;
	std::string second_elf_path;
	std::string third_elf_path;
	std::string dtb_path;
	std::string test_name = "payload";
	std::string expected_uart;
	std::string flash_image;
	bool trace_wave = false;
	bool direct_elf_load = true;
	bool uart_stdin = false;
	bool trace_irq = false;
	bool trace_dmi = false;
	bool perf_report = false;
	bool jtag_only = false;
	bool require_sram_entry = false;
	bool require_payload_entry = false;
	bool stop_on_payload_entry = false;
	bool accept_uart_match = false;
	bool stop_on_uart_match = false;
	int jtag_rbb_port = 0;
	bool inject_boot_args = false;
	uint64_t boot_a0 = 0;
	uint64_t boot_a1 = 0;
	uint64_t boot_a2 = 0;
	uint64_t dtb_addr = SRAM_BASE + 0x00f00000;
	uint64_t sram_base = SRAM_BASE;
	size_t sram_size = DEFAULT_SRAM_SIZE;
	uint64_t max_cycles = MAX_SIM_CYCLES;
};

static void clear_ext_irq_sources(VSoc *dut)
{
	dut->io_ext_irq_sources_0 = 0;
	dut->io_ext_irq_sources_1 = 0;
	dut->io_ext_irq_sources_2 = 0;
	dut->io_ext_irq_sources_3 = 0;
	dut->io_ext_irq_sources_4 = 0;
	dut->io_ext_irq_sources_5 = 0;
	dut->io_ext_irq_sources_6 = 0;
	dut->io_ext_irq_sources_7 = 0;
	dut->io_ext_irq_sources_8 = 0;
	dut->io_ext_irq_sources_9 = 0;
	dut->io_ext_irq_sources_10 = 0;
	dut->io_ext_irq_sources_11 = 0;
	dut->io_ext_irq_sources_12 = 0;
	dut->io_ext_irq_sources_13 = 0;
	dut->io_ext_irq_sources_14 = 0;
	dut->io_ext_irq_sources_15 = 0;
	dut->io_ext_irq_sources_16 = 0;
	dut->io_ext_irq_sources_17 = 0;
	dut->io_ext_irq_sources_18 = 0;
	dut->io_ext_irq_sources_19 = 0;
	dut->io_ext_irq_sources_20 = 0;
	dut->io_ext_irq_sources_21 = 0;
	dut->io_ext_irq_sources_22 = 0;
	dut->io_ext_irq_sources_23 = 0;
	dut->io_ext_irq_sources_24 = 0;
	dut->io_ext_irq_sources_25 = 0;
	dut->io_ext_irq_sources_26 = 0;
	dut->io_ext_irq_sources_27 = 0;
	dut->io_ext_irq_sources_28 = 0;
	dut->io_ext_irq_sources_29 = 0;
	dut->io_ext_irq_sources_30 = 0;
	dut->io_ext_irq_sources_31 = 0;
}

static void set_ext_irq_source(VSoc *dut, unsigned source, bool value)
{
	switch (source)
	{
	case 0: dut->io_ext_irq_sources_0 = value; break;
	case 1: dut->io_ext_irq_sources_1 = value; break;
	case 2: dut->io_ext_irq_sources_2 = value; break;
	case 3: dut->io_ext_irq_sources_3 = value; break;
	case 4: dut->io_ext_irq_sources_4 = value; break;
	case 5: dut->io_ext_irq_sources_5 = value; break;
	case 6: dut->io_ext_irq_sources_6 = value; break;
	case 7: dut->io_ext_irq_sources_7 = value; break;
	case 8: dut->io_ext_irq_sources_8 = value; break;
	case 9: dut->io_ext_irq_sources_9 = value; break;
	case 10: dut->io_ext_irq_sources_10 = value; break;
	case 11: dut->io_ext_irq_sources_11 = value; break;
	case 12: dut->io_ext_irq_sources_12 = value; break;
	case 13: dut->io_ext_irq_sources_13 = value; break;
	case 14: dut->io_ext_irq_sources_14 = value; break;
	case 15: dut->io_ext_irq_sources_15 = value; break;
	case 16: dut->io_ext_irq_sources_16 = value; break;
	case 17: dut->io_ext_irq_sources_17 = value; break;
	case 18: dut->io_ext_irq_sources_18 = value; break;
	case 19: dut->io_ext_irq_sources_19 = value; break;
	case 20: dut->io_ext_irq_sources_20 = value; break;
	case 21: dut->io_ext_irq_sources_21 = value; break;
	case 22: dut->io_ext_irq_sources_22 = value; break;
	case 23: dut->io_ext_irq_sources_23 = value; break;
	case 24: dut->io_ext_irq_sources_24 = value; break;
	case 25: dut->io_ext_irq_sources_25 = value; break;
	case 26: dut->io_ext_irq_sources_26 = value; break;
	case 27: dut->io_ext_irq_sources_27 = value; break;
	case 28: dut->io_ext_irq_sources_28 = value; break;
	case 29: dut->io_ext_irq_sources_29 = value; break;
	case 30: dut->io_ext_irq_sources_30 = value; break;
	case 31: dut->io_ext_irq_sources_31 = value; break;
	default: break;
	}
}

class UartStdio
{
  public:
	explicit UartStdio(bool enable_stdin)
	    : enable_stdin_(enable_stdin),
	      inject_cycle_(env_u64("ION_UART_RX_CYCLE", UINT64_MAX)),
	      inject_byte_(env_u64("ION_UART_RX_BYTE", 0)),
	      inject_enabled_(inject_cycle_ != UINT64_MAX)
	{
		if (enable_stdin_)
		{
			old_flags_ = fcntl(STDIN_FILENO, F_GETFL, 0);
			if (old_flags_ >= 0)
				fcntl(STDIN_FILENO, F_SETFL, old_flags_ | O_NONBLOCK);
		}
	}

	~UartStdio()
	{
		if (enable_stdin_ && old_flags_ >= 0)
			fcntl(STDIN_FILENO, F_SETFL, old_flags_);
	}

	void drive_rx(VSoc *dut, uint64_t cycle)
	{
		dut->io_uart_rx_valid = 0;
		dut->io_uart_rx_byte = 0;
		if (inject_enabled_ && !injected_ && cycle >= inject_cycle_)
		{
			dut->io_uart_rx_valid = 1;
			dut->io_uart_rx_byte = (uint8_t)(inject_byte_ & 0xff);
			injected_ = true;
			return;
		}
		if (!enable_stdin_)
			return;

		uint8_t ch = 0;
		ssize_t n = read(STDIN_FILENO, &ch, 1);
		if (n == 1)
		{
			dut->io_uart_rx_valid = 1;
			dut->io_uart_rx_byte = ch;
		}
		else if (n < 0 && !would_block_errno(errno))
		{
			perror("uart stdin read");
		}
	}

	void capture_tx(VSoc *dut)
	{
		if (dut->io_uart_tx)
		{
			uint8_t ch = (uint8_t)(dut->io_uart_byte & 0xFF);
			output_.push_back((char)ch);
			putchar(ch);
			fflush(stdout);
		}
	}

	const std::string &output() const { return output_; }

  private:
	bool enable_stdin_ = false;
	int old_flags_ = -1;
	std::string output_;
	uint64_t inject_cycle_ = UINT64_MAX;
	uint64_t inject_byte_ = 0;
	bool inject_enabled_ = false;
	bool injected_ = false;
};

class InterruptModel
{
  public:
	explicit InterruptModel(bool trace_irq)
	    : trace_irq_(trace_irq), env_mask_(env_u64("ION_IRQ_SOURCE_MASK", 0))
	{
	}

	void drive(VSoc *dut, const std::string &test_name, uint64_t cycle)
	{
		clear_ext_irq_sources(dut);
		uint64_t mask = env_mask_;
		if ((test_name == "plic" || test_name == "plic_s") && cycle >= 80)
			mask |= (1ULL << 1);
		for (unsigned source = 0; source < 32; ++source)
			set_ext_irq_source(dut, source, (mask >> source) & 1ULL);
	}

	void sample(VSoc *dut, uint64_t cycle)
	{
		if (!trace_irq_)
			return;

		uint8_t mtip = (dut->rootp->SimTop__DOT__clint__DOT__mtimecmp != 0) &&
		               (dut->rootp->SimTop__DOT__clint__DOT__mtime >= dut->rootp->SimTop__DOT__clint__DOT__mtimecmp);
		uint8_t src1 = dut->rootp->io_ext_irq_sources_1;
		uint8_t pending = dut->rootp->SimTop__DOT__core__DOT__interruptPending;
		uint8_t fire = dut->rootp->SimTop__DOT__core__DOT__interrupt_fire;
		uint64_t mcause = dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mcause;
		if (mtip != last_mtip_ || src1 != last_src1_ || pending != last_pending_ || fire != last_fire_)
		{
			printf("[irq %6" PRIu64 "] src1=%u mtip=%u pending=%u fire=%u mcause=0x%016" PRIx64 "\n",
			       cycle, src1, mtip, pending, fire, mcause);
		}
		last_mtip_ = mtip;
		last_src1_ = src1;
		last_pending_ = pending;
		last_fire_ = fire;
	}

  private:
	bool trace_irq_ = false;
	uint64_t env_mask_ = 0;
	uint8_t last_mtip_ = 0xff;
	uint8_t last_src1_ = 0xff;
	uint8_t last_pending_ = 0xff;
	uint8_t last_fire_ = 0xff;
};

class RemoteBitbang
{
  public:
	explicit RemoteBitbang(int port, bool cycle_per_command = false)
	    : port_(port),
	      cycle_per_command_(cycle_per_command),
	      trace_(env_enabled("ION_TRACE_JTAG")),
	      trace_dmi_(env_enabled("ION_TRACE_DMI")) {}

	bool init()
	{
		if (port_ <= 0)
			return true;
		listen_fd_ = socket(AF_INET, SOCK_STREAM, 0);
		if (listen_fd_ < 0)
		{
			perror("jtag socket");
			return false;
		}
		int one = 1;
		setsockopt(listen_fd_, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
		sockaddr_in addr{};
		addr.sin_family = AF_INET;
		addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
		addr.sin_port = htons((uint16_t)port_);
		if (bind(listen_fd_, (sockaddr *)&addr, sizeof(addr)) != 0)
		{
			perror("jtag bind");
			return false;
		}
		if (listen(listen_fd_, 1) != 0)
		{
			perror("jtag listen");
			return false;
		}
		set_nonblock(listen_fd_);
		printf("[jtag]: remote-bitbang listening on 127.0.0.1:%d\n", port_);
		return true;
	}

	~RemoteBitbang()
	{
		if (client_fd_ >= 0)
			close(client_fd_);
		if (listen_fd_ >= 0)
			close(listen_fd_);
	}

	void drive(VSoc *dut)
	{
		if (port_ <= 0)
			return;
		accept_client();
		if (client_fd_ < 0)
			return;

		char ch = 0;
		ssize_t n = recv(client_fd_, &ch, 1, 0);
		if (n == 1)
		{
			handle(dut, ch);
			return;
		}
		if (n == 0)
		{
			close(client_fd_);
			client_fd_ = -1;
			return;
		}
		if (would_block_errno(errno))
			return;
		perror("jtag recv");
		close(client_fd_);
		client_fd_ = -1;
	}

  private:
	static void set_nonblock(int fd)
	{
		int flags = fcntl(fd, F_GETFL, 0);
		if (flags >= 0)
			fcntl(fd, F_SETFL, flags | O_NONBLOCK);
	}

	void accept_client()
	{
		if (client_fd_ >= 0 || listen_fd_ < 0)
			return;
		client_fd_ = accept(listen_fd_, nullptr, nullptr);
		if (client_fd_ >= 0)
		{
			set_nonblock(client_fd_);
			printf("[jtag]: remote-bitbang client connected\n");
		}
		else if (!would_block_errno(errno))
		{
			perror("jtag accept");
		}
	}

	void handle(VSoc *dut, char ch)
	{
		if (ch >= '0' && ch <= '7')
		{
			unsigned value = (unsigned)(ch - '0');
			dut->io_jtag_tck = (value >> 2) & 1;
			dut->io_jtag_tms = (value >> 1) & 1;
			dut->io_jtag_tdi = value & 1;
			step_command_clock(dut);
			if (trace_)
				printf("[jtag-rbb] write %c tck=%u tms=%u tdi=%u tdo=%u\n", ch,
				       (unsigned)dut->io_jtag_tck, (unsigned)dut->io_jtag_tms,
				       (unsigned)dut->io_jtag_tdi, (unsigned)dut->io_jtag_tdo);
		}
		else if (ch == 'R')
		{
			dut->eval();
			char tdo = dut->io_jtag_tdo ? '1' : '0';
			(void)send(client_fd_, &tdo, 1, MSG_NOSIGNAL);
			if (trace_)
				printf("[jtag-rbb] read tdo=%c\n", tdo);
		}
		else if (ch >= 'r' && ch <= 'u')
		{
			bool trst = ((ch - 'r') & 0x2) != 0;
			if (trst)
			{
				dut->io_jtag_tms = 1;
				dut->io_jtag_tck = 0;
				dut->io_jtag_tdi = 0;
			}
			step_command_clock(dut);
			if (trace_)
				printf("[jtag-rbb] reset cmd %c trst=%u\n", ch, (unsigned)trst);
		}
		else if (ch == 'Q')
		{
			close(client_fd_);
			client_fd_ = -1;
		}
	}

	int port_ = 0;
	int listen_fd_ = -1;
	int client_fd_ = -1;
	bool cycle_per_command_ = false;
	bool trace_ = false;
	bool trace_dmi_ = false;
	uint8_t last_dmi_valid_ = 0;

	void step_command_clock(VSoc *dut)
	{
		if (!cycle_per_command_)
			return;
		// The current Chisel TAP samples TCK edges in the SoC clock domain.
		// In JTAG-only mode, advance a full SoC tick for every remote_bitbang
		// drive command so OpenOCD cannot outrun the synchronizer.
		if (dut->clock)
		{
			dut->clock = 0;
			dut->eval();
		}
		dut->clock = 1;
		dut->eval();
		trace_dmi(dut);
		dut->clock = 0;
		dut->eval();
	}

	void trace_dmi(VSoc *dut)
	{
		if (!trace_dmi_)
			return;
		uint8_t dmi_valid = dut->rootp->SimTop__DOT__debugModule_io_dmi_valid_REG;
		if (dmi_valid && !last_dmi_valid_)
		{
			uint64_t dr = dut->rootp->SimTop__DOT__jtag__DOT__drUpdate;
			unsigned op = dr & 0x3;
			unsigned addr = (dr >> 34) & 0x7f;
			uint32_t wdata = (uint32_t)((dr >> 2) & 0xffffffffu);
			uint32_t rdata = dut->rootp->SimTop__DOT___debugModule_io_dmi_rdata;
			uint32_t dmcontrol = dut->rootp->SimTop__DOT__debugModule__DOT__dmcontrol;
			uint32_t dmstatus = dut->rootp->SimTop__DOT__debugModule__DOT__dmstatus;
			printf("[dmi-cmd] op=%u addr=0x%02x wdata=0x%08x rdata=0x%08x dmcontrol=0x%08x dmstatus=0x%08x\n",
			       op, addr, wdata, rdata, dmcontrol, dmstatus);
			fflush(stdout);
		}
		last_dmi_valid_ = dmi_valid;
	}
};

class FlashImage
{
  public:
	bool load(const std::string &path)
	{
		if (path.empty())
			return true;
		FILE *f = fopen(path.c_str(), "rb");
		if (!f)
		{
			perror("flash fopen");
			return false;
		}
		if (fseek(f, 0, SEEK_END) != 0)
		{
			fclose(f);
			return false;
		}
		long size = ftell(f);
		if (size < 0)
		{
			fclose(f);
			return false;
		}
		rewind(f);
		data_.resize((size_t)size);
		size_t got = fread(data_.data(), 1, data_.size(), f);
		fclose(f);
		if (got != data_.size())
		{
			fprintf(stderr, "short flash image read: %zu/%zu\n", got, data_.size());
			return false;
		}
		printf("[flash]: loaded %zu bytes from %s (QSPI pins not connected yet)\n", data_.size(), path.c_str());
		return true;
	}

  private:
	std::vector<uint8_t> data_;
};

int main(int argc, char **argv, char **env)
{
	(void)env;
	Verilated::commandArgs(argc, argv);
	printf("\n\n");
	bool all_pass = true;
	if (env_enabled("ION_JTAG_ONLY"))
	{
		SimOptions opts;
		opts.test_name = "jtag";
		opts.trace_wave = env_enabled("ION_TRACE_WAVE");
		opts.direct_elf_load = !env_enabled("ION_BOOTROM_ONLY");
		opts.uart_stdin = env_enabled("ION_UART_STDIN");
		opts.trace_irq = env_enabled("ION_TRACE_IRQ");
		opts.trace_dmi = env_enabled("ION_TRACE_DMI");
		opts.perf_report = env_enabled("ION_PERF");
		opts.jtag_only = true;
		opts.jtag_rbb_port = (int)env_u64("ION_JTAG_RBB_PORT", 0);
		opts.max_cycles = env_u64("ION_MAX_CYCLES", 0);
		const char *flash = std::getenv("ION_FLASH_IMAGE");
		if (flash != nullptr)
			opts.flash_image = flash;
		return run_sim(opts) ? 0 : 1;
	}
	else if (argc < 2)
	{
		// 默认测试 payload (假设无后缀)
		all_pass &= run_one_test(kPayloadElfPath, "payload", env_enabled("ION_TRACE_WAVE"), "S!!P");
	}
	else if (std::string(argv[1]) == "--payload")
	{
		std::string name = (argc > 2) ? argv[2] : "payload";
		std::string expected_uart = (argc > 3) ? argv[3] : "";
		std::string elf_path = (argc > 4) ? argv[4] : kPayloadElfPath;
		all_pass &= run_one_test(elf_path, name, env_enabled("ION_TRACE_WAVE"), expected_uart);
	}
	else if (std::string(argv[1]) == "--payload-firmware")
	{
		std::string name = (argc > 2) ? argv[2] : "payload";
		std::string expected_uart = (argc > 3) ? argv[3] : "";
		std::string elf_path = (argc > 4) ? argv[4] : kPayloadElfPath;
		SimOptions opts;
		opts.elf_path = elf_path;
		opts.test_name = name;
		opts.expected_uart = expected_uart;
		opts.trace_wave = env_enabled("ION_TRACE_WAVE");
		opts.direct_elf_load = !env_enabled("ION_BOOTROM_ONLY");
		opts.uart_stdin = env_enabled("ION_UART_STDIN");
		opts.trace_irq = env_enabled("ION_TRACE_IRQ");
		opts.trace_dmi = env_enabled("ION_TRACE_DMI");
		opts.perf_report = env_enabled("ION_PERF");
		opts.accept_uart_match = env_enabled("ION_ACCEPT_UART_MATCH");
		opts.stop_on_uart_match = env_enabled("ION_STOP_ON_UART_MATCH");
		opts.jtag_rbb_port = (int)env_u64("ION_JTAG_RBB_PORT", 0);
		opts.max_cycles = env_u64("ION_MAX_CYCLES", MAX_SIM_CYCLES);
		opts.sram_base = env_u64("ION_SRAM_BASE", FIRMWARE_SRAM_BASE);
		opts.sram_size = (size_t)env_u64("ION_SRAM_SIZE", DEFAULT_FIRMWARE_SRAM_SIZE);
		all_pass &= run_sim(opts);
	}
	else if (std::string(argv[1]) == "--rustsbi" || std::string(argv[1]) == "--sbi-firmware")
	{
		if (argc < 6)
		{
			fprintf(stderr, "usage: %s %s <trampoline.elf> <firmware.elf> <payload.elf> <dtb>\n", argv[0], argv[1]);
			return 1;
		}
		SimOptions opts;
		opts.test_name = std::string(argv[1]) == "--rustsbi" ? "rustsbi" : "sbi-firmware";
		opts.elf_path = argv[2];
		opts.second_elf_path = argv[3];
		opts.third_elf_path = argv[4];
		opts.dtb_path = argv[5];
		const char *expected_uart = std::getenv("ION_EXPECT_UART");
		opts.expected_uart = expected_uart != nullptr ? expected_uart : "IonSoC SBI smoke";
		opts.trace_wave = env_enabled("ION_TRACE_WAVE");
		opts.direct_elf_load = true;
		opts.uart_stdin = env_enabled("ION_UART_STDIN");
		opts.trace_irq = env_enabled("ION_TRACE_IRQ");
		opts.trace_dmi = env_enabled("ION_TRACE_DMI");
		opts.perf_report = env_enabled("ION_PERF");
		opts.accept_uart_match = env_enabled("ION_ACCEPT_UART_MATCH");
		opts.stop_on_uart_match = env_enabled("ION_STOP_ON_UART_MATCH");
		opts.jtag_rbb_port = (int)env_u64("ION_JTAG_RBB_PORT", 0);
		opts.max_cycles = env_u64("ION_MAX_CYCLES", 8000000);
		opts.sram_base = env_u64("ION_SRAM_BASE", FIRMWARE_SRAM_BASE);
		opts.sram_size = (size_t)env_u64("ION_SRAM_SIZE", DEFAULT_FIRMWARE_SRAM_SIZE);
		opts.dtb_addr = env_u64("ION_DTB_ADDR", opts.sram_base + 0x00f00000);
		opts.require_sram_entry = true;
		opts.require_payload_entry = std::getenv("ION_REQUIRE_PAYLOAD_ENTRY") == nullptr ||
		                             env_enabled("ION_REQUIRE_PAYLOAD_ENTRY");
		opts.inject_boot_args = true;
		opts.boot_a0 = env_u64("ION_BOOT_A0", 0);
		opts.boot_a1 = env_u64("ION_BOOT_A1", opts.dtb_addr);
		opts.boot_a2 = env_u64("ION_BOOT_A2", opts.sram_base + 0x00100000);
		all_pass &= run_sim(opts);
	}
	else
	{
		std::vector<std::string> tests;
		bool testAll = false;

		for (int i = 1; i < argc; ++i)
		{
			if (std::string(argv[i]) == "testAll")
			{
				testAll = true;
				break;
			}
			tests.emplace_back(argv[i]);
		}

		const std::string base_dir = "riscv-tests/target/share/riscv-tests/isa/";
		// const std::string base_dir = "simulator/generated/";

		if (testAll)
		{
			for (auto &p : std::filesystem::directory_iterator(base_dir))
			{
				// 查找无后缀的文件 (ELF)
				if (p.path().extension() == "")
				{
					std::string bin = p.path().string();
					std::string name = p.path().stem().string();
					all_pass &= run_one_test(bin, name, false);
				}
			}
		}
		else
		{
			for (auto &t : tests)
			{
				// 构建路径时不再添加 .bin 后缀
				std::string bin_ui = base_dir + "rv64ui-p-" + t;
				std::string bin_um = base_dir + "rv64um-p-" + t;
				std::string bin;

				if (std::filesystem::exists(bin_ui))
				{
					bin = bin_ui;
				}
				else if (std::filesystem::exists(bin_um))
				{
					bin = bin_um;
				}
				else
				{
					printf("Test binary for %s not found.\n", t.c_str());
					all_pass = false;
					continue;
				}

				all_pass &= run_one_test(bin, t, env_enabled("ION_TRACE_WAVE"));
			}
		}
	}

	printf("All simulations finished.\n");
	return all_pass ? 0 : 1;
}

static uint8_t *sram_bytes(VSoc *dut)
{
	return (uint8_t *)&(dut->rootp->SimTop__DOT__sram__DOT__mem_rdata_mem_ext__DOT__Memory[0]);
}

static size_t rtl_sram_capacity_bytes(VSoc *dut)
{
	return sizeof(dut->rootp->SimTop__DOT__sram__DOT__mem_rdata_mem_ext__DOT__Memory);
}

static void write_sram_bytes(VSoc *dut, uint64_t sram_base, size_t sram_size, uint64_t paddr, const uint8_t *src, size_t len)
{
	if (paddr < sram_base)
	{
		fprintf(stderr, "SRAM write below base: paddr=0x%016" PRIx64 "\n", paddr);
		exit(1);
	}
	uint64_t off = paddr - sram_base;
	if (off + len > sram_size)
	{
		fprintf(stderr, "SRAM write out of range: paddr=0x%016" PRIx64 " len=%zu sram=%zu\n",
		        paddr, len, sram_size);
		exit(1);
	}
	memcpy(sram_bytes(dut) + off, src, len);
}

void load_elf(VSoc *dut, const char *path)
{
	load_elf_to_regions(dut, path, SRAM_BASE, DEFAULT_SRAM_SIZE);
}

void load_elf_to_regions(VSoc *dut, const char *path, uint64_t sram_base, size_t sram_size)
{
	FILE *f = fopen(path, "rb");
	if (!f)
	{
		perror("fopen");
		exit(1);
	}

	// Read ELF64 header (read max sized header; will validate class)
	Elf64_Ehdr ehdr64;
	if (fread(&ehdr64, 1, sizeof(Elf64_Ehdr), f) != sizeof(Elf64_Ehdr))
	{
		fprintf(stderr, "Read ELF header failed: %s\n", path);
		fclose(f);
		exit(1);
	}

	// Check ELF magic
	if (ehdr64.e_ident[EI_MAG0] != ELFMAG0 || ehdr64.e_ident[EI_MAG1] != ELFMAG1 ||
		ehdr64.e_ident[EI_MAG2] != ELFMAG2 || ehdr64.e_ident[EI_MAG3] != ELFMAG3)
	{
		fprintf(stderr, "Not an ELF file: %s\n", path);
		fclose(f);
		exit(1);
	}

	// Only accept little-endian for now
	if (ehdr64.e_ident[EI_DATA] != ELFDATA2LSB)
	{
		fprintf(stderr, "Unsupported ELF endianness (not little-endian): %s\n", path);
		fclose(f);
		exit(1);
	}

	if (ehdr64.e_ident[EI_CLASS] != ELFCLASS64)
	{
		fprintf(stderr, "Unsupported ELF class (not 64-bit): %s\n", path);
		fclose(f);
		exit(1);
	}

	if (ehdr64.e_phoff == 0 || ehdr64.e_phnum == 0)
	{
		fprintf(stderr, "No program headers in ELF: %s\n", path);
		fclose(f);
		exit(1);
	}

	// Read program headers (Elf64_Phdr)
	if (fseeko(f, (off_t)ehdr64.e_phoff, SEEK_SET) != 0)
	{
		perror("fseeko phoff");
		fclose(f);
		exit(1);
	}
	Elf64_Phdr *phdrs = new Elf64_Phdr[ehdr64.e_phnum];
	if (fread(phdrs, sizeof(Elf64_Phdr), ehdr64.e_phnum, f) != (size_t)ehdr64.e_phnum)
	{
		fprintf(stderr, "Read program headers failed\n");
		delete[] phdrs;
		fclose(f);
		exit(1);
	}

	// memory pointers: treat DUT mem[] as word array but provide byte view
	// 原代码使用 32-bit word pointers；这里保留相同写法（假设目标内存为 32-bit word 存储）
	uint32_t *brom_lo_words = (uint32_t *)&(dut->rootp->SimTop__DOT__brom__DOT__loRom__DOT__mem[0]);
	uint32_t *brom_hi_words = (uint32_t *)&(dut->rootp->SimTop__DOT__brom__DOT__hiRom__DOT__mem[0]);
	uint32_t *tlrom_lo_words = (uint32_t *)&(dut->rootp->SimTop__DOT__tlrom__DOT__loRom__DOT__mem[0]);
	uint32_t *tlrom_hi_words = (uint32_t *)&(dut->rootp->SimTop__DOT__tlrom__DOT__hiRom__DOT__mem[0]);
	uint32_t *sram_words = (uint32_t *)sram_bytes(dut);
	std::vector<uint8_t> brom_image(ROM_SIZE, 0);
	uint8_t *brom_bytes = brom_image.data();
	uint8_t *sram_bytes = (uint8_t *)sram_words;

	const size_t rom_bytes_size = (size_t)ROM_SIZE;
	const size_t sram_bytes_size = sram_size;

	// Helper lambda: safe write (reads from file and writes into target_bytes at byte offset)
	auto write_bytes_to_region = [&](uint8_t *target_bytes, size_t region_bytes,
									 uint64_t offset_byte, uint64_t file_off, uint64_t filesz)
	{
		if (filesz == 0)
			return;
		// clamp
		if ((uint64_t)offset_byte + (uint64_t)filesz > region_bytes)
		{
			size_t can = (offset_byte < region_bytes) ? (region_bytes - offset_byte) : 0;
			fprintf(stderr, "Warning: truncating write: offset 0x%016" PRIx64 " filesz %" PRIu64 " -> %zu available\n",
					offset_byte, filesz, can);
			filesz = (uint64_t)can;
			if (filesz == 0)
				return;
		}

		// If both offset and size are 4-byte aligned, do word writes for performance/endianness clarity
		if ((offset_byte % 4 == 0) && (filesz % 4 == 0))
		{
			size_t word_idx = offset_byte / 4;
			size_t words = filesz / 4;
			// seek file
			if (fseeko(f, (off_t)file_off, SEEK_SET) != 0)
			{
				perror("fseeko file_off");
				return;
			}
			for (size_t w = 0; w < words; ++w)
			{
				uint8_t buf[4];
				size_t r = fread(buf, 1, 4, f);
				if (r != 4)
				{
					fprintf(stderr, "Warning: short read in word copy (%zu/%zu)\n", r, (size_t)4);
					break;
				}
				// little-endian assemble
				uint32_t word = (uint32_t)buf[0] | ((uint32_t)buf[1] << 8) | ((uint32_t)buf[2] << 16) | ((uint32_t)buf[3] << 24);
				// write to target words (assume target_bytes is word-addressable as uint32_t array)
				((uint32_t *)target_bytes)[word_idx + w] = word;
			}
		}
		else
		{
			// unaligned or non-word-sized: do byte-wise copy
			if (fseeko(f, (off_t)file_off, SEEK_SET) != 0)
			{
				perror("fseeko file_off");
				return;
			}
			size_t to_copy = (size_t)filesz;
			size_t dest = (size_t)offset_byte;
			const size_t CHUNK = 1024;
			uint8_t tmp[CHUNK];
			while (to_copy > 0)
			{
				size_t c = (to_copy > CHUNK) ? CHUNK : to_copy;
				size_t r = fread(tmp, 1, c, f);
				if (r == 0)
					break;
				memcpy(target_bytes + dest, tmp, r);
				dest += r;
				to_copy -= r;
			}
		}
	};

	auto mirror_rom_to_rtl = [&](uint64_t offset_byte, uint64_t filesz)
	{
		uint64_t end = offset_byte + filesz;
		if (end > rom_bytes_size)
		{
			end = rom_bytes_size;
		}
		for (uint64_t byte = offset_byte; byte < end; byte += 4)
		{
			uint32_t word = ((uint32_t *)brom_bytes)[byte / 4];
			uint64_t word_idx = byte / 4;
			brom_lo_words[word_idx] = word;
			brom_hi_words[word_idx] = word;
			if ((word_idx & 1) == 0)
			{
				tlrom_lo_words[word_idx] = word;
			}
			else
			{
				tlrom_hi_words[word_idx] = word;
			}
		}
	};

	// Iterate program headers
	for (int i = 0; i < (int)ehdr64.e_phnum; ++i)
	{
		Elf64_Phdr &ph = phdrs[i];
		// debug print
		printf("PHDR %d: type=%" PRIu32 " vaddr=0x%016" PRIx64 " off=0x%016" PRIx64 " filesz=%" PRIu64 " memsz=%" PRIu64 "\n",
			   i, (uint32_t)ph.p_type, (uint64_t)ph.p_vaddr, (uint64_t)ph.p_offset, (uint64_t)ph.p_filesz, (uint64_t)ph.p_memsz);

		if (ph.p_type != PT_LOAD)
			continue;

		uint64_t vaddr = (uint64_t)ph.p_vaddr;
		uint64_t filesz = (uint64_t)ph.p_filesz;
		uint64_t memsz = (uint64_t)ph.p_memsz;

		uint8_t *target_bytes = nullptr;
		size_t region_bytes = 0;
		uint64_t offset_in_region = 0;
		const char *region_name = nullptr;

		if (vaddr >= (uint64_t)BROM_BASE && vaddr < (uint64_t)BROM_BASE + (uint64_t)ROM_SIZE)
		{
			target_bytes = brom_bytes;
			region_bytes = rom_bytes_size;
			offset_in_region = vaddr - (uint64_t)BROM_BASE;
			region_name = "ROM";
		}
		else if (vaddr >= sram_base && vaddr < sram_base + (uint64_t)sram_bytes_size)
		{
			target_bytes = sram_bytes;
			region_bytes = sram_bytes_size;
			offset_in_region = vaddr - sram_base;
			region_name = "SRAM";
		}
		else
		{
			printf("Warning: PT_LOAD at vaddr 0x%016" PRIx64 " (filesz=%" PRIu64 ") outside ROM/SRAM -> skip\n", vaddr, filesz);
			continue;
		}

		// write file bytes to region
		if (filesz > 0)
		{
			write_bytes_to_region(target_bytes, region_bytes, offset_in_region, ph.p_offset, filesz);
			if (target_bytes == brom_bytes)
			{
				mirror_rom_to_rtl(offset_in_region, filesz);
			}
			printf("  -> wrote %" PRIu64 " bytes to %s @ offset 0x%016" PRIx64 "\n", filesz, region_name, offset_in_region);
		}

		// zero initialize BSS tail (memsz > filesz)
		if (memsz > filesz)
		{
			uint64_t zero_start = offset_in_region + filesz;
			uint64_t zero_len = memsz - filesz;
			if (zero_start < region_bytes)
			{
				if (zero_start + zero_len > region_bytes)
				{
					zero_len = region_bytes - zero_start;
				}
				if (zero_len > 0)
				{
					memset(target_bytes + (size_t)zero_start, 0, (size_t)zero_len);
					printf("  -> zeroed %" PRIu64 " bytes in %s @ offset 0x%016" PRIx64 "\n", zero_len, region_name, zero_start);
				}
			}
		}
	}

	delete[] phdrs;
	fclose(f);
}

void load_blob_to_sram(VSoc *dut, const char *path, uint64_t paddr, uint64_t sram_base, size_t sram_size)
{
	FILE *f = fopen(path, "rb");
	if (!f)
	{
		perror("blob fopen");
		exit(1);
	}
	if (fseek(f, 0, SEEK_END) != 0)
	{
		perror("blob fseek");
		fclose(f);
		exit(1);
	}
	long size = ftell(f);
	if (size < 0)
	{
		perror("blob ftell");
		fclose(f);
		exit(1);
	}
	rewind(f);
	std::vector<uint8_t> data((size_t)size);
	if (!data.empty() && fread(data.data(), 1, data.size(), f) != data.size())
	{
		fprintf(stderr, "short blob read: %s\n", path);
		fclose(f);
		exit(1);
	}
	fclose(f);
	write_sram_bytes(dut, sram_base, sram_size, paddr, data.data(), data.size());
	printf("[boot]: loaded blob %s -> SRAM 0x%016" PRIx64 " (%zu bytes)\n", path, paddr, data.size());
}

void ram_init(VSoc *dut, size_t sram_size = DEFAULT_SRAM_SIZE)
{
	size_t rtl_capacity = rtl_sram_capacity_bytes(dut);
	if (sram_size > rtl_capacity)
	{
		fprintf(stderr, "Requested SRAM size 0x%zx exceeds RTL SRAM capacity 0x%zx. Rebuild the matching Verilator profile.\n",
		        sram_size, rtl_capacity);
		exit(1);
	}
	const size_t WORDS = sram_size / 8; // Memory is 64-bit wide
	for (size_t i = 0; i < WORDS; ++i)
	{
		dut->rootp->SimTop__DOT__sram__DOT__mem_rdata_mem_ext__DOT__Memory[i] = 0x0;
	}
}

bool run_one_test(const std::string &bin_path,
				  const std::string &test_name, bool trace_en,
				  const std::string &expected_uart)
{
	SimOptions opts;
	opts.elf_path = bin_path;
	opts.test_name = test_name;
	opts.expected_uart = expected_uart;
	opts.trace_wave = trace_en;
	opts.direct_elf_load = !env_enabled("ION_BOOTROM_ONLY");
	opts.uart_stdin = env_enabled("ION_UART_STDIN");
	opts.trace_irq = env_enabled("ION_TRACE_IRQ");
	opts.trace_dmi = env_enabled("ION_TRACE_DMI");
	opts.perf_report = env_enabled("ION_PERF");
	opts.accept_uart_match = env_enabled("ION_ACCEPT_UART_MATCH");
	opts.stop_on_uart_match = env_enabled("ION_STOP_ON_UART_MATCH");
	opts.jtag_rbb_port = (int)env_u64("ION_JTAG_RBB_PORT", 0);
	opts.max_cycles = env_u64("ION_MAX_CYCLES", MAX_SIM_CYCLES);
	if (test_name == "uart_irq")
		opts.max_cycles = env_u64("ION_MAX_CYCLES", 200000);
	const char *flash = std::getenv("ION_FLASH_IMAGE");
	if (flash != nullptr)
		opts.flash_image = flash;
	return run_sim(opts);
}

bool run_sim(const SimOptions &opts)
{
	Verilated::gotFinish(false);
	Verilated::gotError(false);
	VSoc *dut = new VSoc;
	WaveTraceWindow wave(dut, opts.trace_wave);

	sim_time = 0;

	dut->clock = 0;
	dut->reset = 1;
	clear_ext_irq_sources(dut);
	dut->io_uart_rx_valid = 0;
	dut->io_uart_rx_byte = 0;
	dut->io_jtag_tms = 1;
	dut->io_jtag_tck = 0;
	dut->io_jtag_tdi = 0;
	// Run Verilator initial blocks before preloading memories; ROM initial
	// blocks clear their arrays and would otherwise wipe harness-loaded ELFs.
	dut->eval();

	ram_init(dut, opts.sram_size);

	FlashImage flash;
	if (!flash.load(opts.flash_image))
	{
		delete dut;
		return false;
	}
	if (opts.direct_elf_load)
	{
		load_elf_to_regions(dut, opts.elf_path.c_str(), opts.sram_base, opts.sram_size);
		if (!opts.second_elf_path.empty())
			load_elf_to_regions(dut, opts.second_elf_path.c_str(), opts.sram_base, opts.sram_size);
		if (!opts.third_elf_path.empty())
			load_elf_to_regions(dut, opts.third_elf_path.c_str(), opts.sram_base, opts.sram_size);
		if (!opts.dtb_path.empty())
			load_blob_to_sram(dut, opts.dtb_path.c_str(), opts.dtb_addr, opts.sram_base, opts.sram_size);
	}
	else
	{
		printf("[boot]: direct ELF preload disabled; boot ROM will run from built-in contents\n");
		printf("[boot]: use ION_FLASH_IMAGE for the future QSPI-backed boot path\n");
	}

	clear_ext_irq_sources(dut);
	dut->io_uart_rx_valid = 0;
	dut->io_uart_rx_byte = 0;
	dut->io_jtag_tms = 1;
	dut->io_jtag_tck = 0;
	dut->io_jtag_tdi = 0;

	dut->clock = 0;
	dut->reset = 1;

	UartStdio uart(opts.uart_stdin);
	InterruptModel irq(opts.trace_irq);
	RemoteBitbang jtag(opts.jtag_rbb_port, opts.jtag_only);
	if (!jtag.init())
	{
		delete dut;
		return false;
	}

	for (int i = 0; i < 6; ++i)
	{
		irq.drive(dut, opts.test_name, sim_time);
		uart.drive_rx(dut, sim_time);
		jtag.drive(dut);
		dut->clock ^= 1;
		dut->eval();
		wave.sample(dut, sim_time);
		sim_time++;
	}

	dut->reset = 0;
	if (opts.inject_boot_args)
	{
		dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[10] = opts.boot_a0;
		dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[11] = opts.boot_a1;
		dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[12] = opts.boot_a2;
		printf("[boot]: sram_base=0x%016" PRIx64 " sram_size=0x%zx dtb=0x%016" PRIx64 " payload=0x%016" PRIx64 "\n",
		       opts.sram_base, opts.sram_size, opts.dtb_addr, opts.boot_a2);
		printf("[boot]: injected a0=0x%016" PRIx64 " a1=0x%016" PRIx64 " a2=0x%016" PRIx64 "\n",
		       opts.boot_a0, opts.boot_a1, opts.boot_a2);
	}

	printf("\n--- UART output ---\n");
	bool saw_exit = false;
	bool stopped_on_payload_entry = false;
	bool stopped_on_uart_match = false;
	bool trace_cpu = env_enabled("ION_TRACE_CPU");
	bool trace_cpu_every = env_enabled("ION_TRACE_CPU_EVERY");
	bool trace_pc_escape = env_enabled("ION_TRACE_PC_ESCAPE");
	bool trace_map_u32 = env_enabled("ION_TRACE_MAP_U32");
	bool trace_ret = env_enabled("ION_TRACE_RET");
	bool trace_csr = env_enabled("ION_TRACE_CSR");
	bool trace_atomic = env_enabled("ION_TRACE_ATOMIC");
	bool trace_lsu_ptw = env_enabled("ION_TRACE_LSU_PTW");
	bool trace_dmem = env_enabled("ION_TRACE_DMEM");
	bool disable_exit_check = env_enabled("ION_DISABLE_EXIT_CHECK");
	bool stop_on_payload_entry = opts.stop_on_payload_entry || env_enabled("ION_STOP_ON_PAYLOAD_ENTRY");
	uint64_t trace_pc_start = env_u64("ION_TRACE_PC_START", 0);
	uint64_t trace_pc_end = env_u64("ION_TRACE_PC_END", UINT64_MAX);
	uint64_t trace_atomic_addr = env_u64("ION_TRACE_ATOMIC_ADDR", 0);
	uint64_t trace_lsu_ptw_vaddr = env_u64("ION_TRACE_LSU_PTW_VADDR", 0);
	uint64_t trace_dmem_addr = env_u64("ION_TRACE_DMEM_ADDR", 0);
	uint64_t trace_dmem_pc_start = env_u64("ION_TRACE_DMEM_PC_START", 0);
	uint64_t trace_dmem_pc_end = env_u64("ION_TRACE_DMEM_PC_END", UINT64_MAX);
	bool trace_boot = env_enabled("ION_TRACE_BOOT");
	bool saw_rom_pc = false;
	bool saw_sram_pc = false;
	bool saw_payload_pc = false;
	bool saw_pc_escape = false;
	uint64_t last_pc = UINT64_MAX;
	uint64_t prev_pc = UINT64_MAX;
	bool prev_pc_valid = false;
	uint64_t last_mtimecmp = UINT64_MAX;
	uint8_t last_mtip = 0xff;
	uint8_t last_dmi_valid = 0;
	uint8_t last_lsu_ptw_state = 0xff;
	uint8_t last_lsu_ptw_level = 0xff;
	uint64_t perf_cycles = 0;
	uint64_t perf_retired = 0;
	uint64_t perf_stall_cycles = 0;
	uint64_t perf_ifetch_stall_cycles = 0;
	uint64_t perf_ifetch_only_stall_cycles = 0;
	uint64_t perf_ifetch_lsu_overlap_cycles = 0;
	uint64_t perf_frontend_starved_cycles = 0;
	uint64_t perf_frontend_queue_full_cycles = 0;
	uint64_t perf_frontend_queue_empty_cycles = 0;
	uint64_t perf_lsu_stall_cycles = 0;
	uint64_t perf_lsu_load_stall_cycles = 0;
	uint64_t perf_lsu_store_stall_cycles = 0;
	uint64_t perf_lsu_mmio_stall_cycles = 0;
	uint64_t perf_lsu_atomic_stall_cycles = 0;
	uint64_t perf_lsu_fence_stall_cycles = 0;
	uint64_t perf_decode_load_use_cycles = 0;
	uint64_t perf_lsu_load_only_cycles = 0;
	uint64_t perf_lsu_store_only_cycles = 0;
	uint64_t perf_lsu_fence_only_cycles = 0;
	uint64_t perf_branch_count = 0;
	uint64_t perf_branch_taken = 0;
	uint64_t perf_branch_redirect = 0;
	uint64_t perf_branch_pred_taken = 0;
	uint64_t perf_branch_pred_correct = 0;
	const size_t history_capacity = (size_t)std::min<uint64_t>(env_u64("ION_DEBUG_HISTORY", 256), 1U << 16);
	const bool stream_arch_trace = env_enabled("ION_TRACE_COMMIT");
	const bool dump_history_always = env_enabled("ION_DEBUG_HISTORY_ALWAYS");
	const uint64_t no_retire_timeout = env_u64("ION_NO_RETIRE_TIMEOUT", 0);
	const uint64_t stop_pc = env_u64("ION_STOP_PC", UINT64_MAX);
	ArchitecturalHistory arch_history(history_capacity, stream_arch_trace);
	uint64_t core_cycle = 0;
	uint64_t last_retire_cycle = 0;
	bool no_retire_timeout_hit = false;
	bool stop_pc_hit = false;
	const char *stop_reason = "max-ticks";
	uint64_t last_eval_tick = sim_time == 0 ? 0 : sim_time - 1;

	while (!Verilated::gotFinish() && !Verilated::gotError() &&
	       (opts.max_cycles == 0 || sim_time < opts.max_cycles))
	{
		irq.drive(dut, opts.test_name, sim_time);
		uart.drive_rx(dut, sim_time);
		jtag.drive(dut);

		dut->clock ^= 1;
		dut->eval();
		last_eval_tick = sim_time;
		wave.sample(dut, sim_time);

		uint64_t cur_mtimecmp = last_mtimecmp;
		uint8_t cur_mtip = last_mtip;
		bool trace_state_change = false;
		if (trace_cpu)
		{
			cur_mtimecmp = dut->rootp->SimTop__DOT__clint__DOT__mtimecmp;
			cur_mtip = (dut->rootp->SimTop__DOT__clint__DOT__mtimecmp != 0) &&
					   (dut->rootp->SimTop__DOT__clint__DOT__mtime >= dut->rootp->SimTop__DOT__clint__DOT__mtimecmp);
			trace_state_change = cur_mtip != last_mtip || cur_mtimecmp != last_mtimecmp;
		}
		uint64_t pc_now = dut->io_debug_pc;
		const bool commit_valid = dut->clock && dut->io_debug_retire;
		const uint64_t commit_pc = dut->io_debug_commitPc;
		if (dut->clock)
		{
			++core_cycle;
			arch_history.sample(dut, core_cycle, sim_time);
			if (dut->io_debug_retire)
				last_retire_cycle = core_cycle;
			if (!opts.jtag_only && no_retire_timeout != 0 &&
			    core_cycle - last_retire_cycle >= no_retire_timeout)
				no_retire_timeout_hit = true;
			if (!opts.jtag_only && commit_valid && commit_pc == stop_pc)
			{
				stop_pc_hit = true;
				stop_reason = "stop-pc";
				break;
			}
		}
		if (opts.perf_report && dut->clock)
		{
			perf_cycles++;
			perf_retired += dut->io_debug_retire ? 1 : 0;
			perf_stall_cycles += dut->io_debug_stall ? 1 : 0;
			perf_ifetch_stall_cycles += dut->io_debug_ifetchStall ? 1 : 0;
			perf_lsu_stall_cycles += dut->io_debug_lsuStall ? 1 : 0;
			perf_ifetch_only_stall_cycles += (dut->io_debug_ifetchStall && !dut->io_debug_lsuStall) ? 1 : 0;
			perf_ifetch_lsu_overlap_cycles += (dut->io_debug_ifetchStall && dut->io_debug_lsuStall) ? 1 : 0;
			perf_frontend_starved_cycles += dut->io_debug_frontendStarved ? 1 : 0;
			perf_frontend_queue_full_cycles += dut->io_debug_frontendQueueFull ? 1 : 0;
			perf_frontend_queue_empty_cycles += dut->io_debug_frontendQueueEmpty ? 1 : 0;
			perf_lsu_load_stall_cycles += dut->io_debug_lsuLoadStall ? 1 : 0;
			perf_lsu_store_stall_cycles += dut->io_debug_lsuStoreStall ? 1 : 0;
			perf_lsu_mmio_stall_cycles += dut->io_debug_lsuMmioStall ? 1 : 0;
			perf_lsu_atomic_stall_cycles += dut->io_debug_lsuAtomicStall ? 1 : 0;
			perf_lsu_fence_stall_cycles += dut->io_debug_lsuFenceStall ? 1 : 0;
			perf_decode_load_use_cycles += dut->rootp->SimTop__DOT__core__DOT__loadScoreboard__DOT__io_decodeUsesPending ? 1 : 0;
			perf_lsu_load_only_cycles += (dut->io_debug_lsuLoadStall && !dut->io_debug_lsuStoreStall && !dut->io_debug_lsuFenceStall) ? 1 : 0;
			perf_lsu_store_only_cycles += (dut->io_debug_lsuStoreStall && !dut->io_debug_lsuLoadStall && !dut->io_debug_lsuFenceStall) ? 1 : 0;
			perf_lsu_fence_only_cycles += (dut->io_debug_lsuFenceStall && !dut->io_debug_lsuLoadStall && !dut->io_debug_lsuStoreStall) ? 1 : 0;
			perf_branch_count += dut->io_debug_branchValid ? 1 : 0;
			perf_branch_taken += dut->io_debug_branchTaken ? 1 : 0;
			perf_branch_redirect += dut->io_debug_branchRedirect ? 1 : 0;
			perf_branch_pred_taken += dut->io_debug_branchPredTaken ? 1 : 0;
			perf_branch_pred_correct += dut->io_debug_branchPredCorrect ? 1 : 0;
		}

		if (dut->clock)
		{
			if (trace_map_u32 && pc_now >= 0x4001ccc0ULL && pc_now <= 0x4001cdb0ULL)
			{
				auto &regs = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory;
				printf("[map-u32 %6" PRIu64 "] pc=0x%016" PRIx64 " instr=0x%08x"
				       " a0=0x%016" PRIx64 " a1=0x%016" PRIx64 " a2=0x%016" PRIx64
				       " a3=0x%016" PRIx64 " a4=0x%016" PRIx64 " a5=0x%016" PRIx64
				       " a6=0x%016" PRIx64 " t0=0x%016" PRIx64 " ra=0x%016" PRIx64 "\n",
				       sim_time,
				       pc_now,
				       (uint32_t)dut->io_debug_instr,
				       (uint64_t)regs[10],
				       (uint64_t)regs[11],
				       (uint64_t)regs[12],
				       (uint64_t)regs[13],
				       (uint64_t)regs[14],
				       (uint64_t)regs[15],
				       (uint64_t)regs[16],
				       (uint64_t)regs[5],
				       (uint64_t)regs[1]);
			}
			if (trace_ret)
			{
				uint64_t lsu_pc = dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__out_pc;
				bool trace_ret_window = pc_now >= 0x40019590ULL && pc_now <= 0x40019690ULL;
				bool trace_ret_lsu_window = lsu_pc >= 0x40019590ULL && lsu_pc <= 0x40019690ULL;
				if (trace_ret_window || (trace_ret_lsu_window && dut->rootp->SimTop__DOT__core__DOT___lsu_io_valid_out))
				{
					printf("[ret-trace %6" PRIu64 "] pc=0x%016" PRIx64 " instr=0x%08x lsu_pc=0x%016" PRIx64
					       " has_ret=%u ret_redirect=%u retConsumed=%u lsu_valid=%u out_is_ret=%u ret_type=%u"
					       " epc=0x%016" PRIx64 " mepc=0x%016" PRIx64 " sepc=0x%016" PRIx64 "\n",
					       sim_time,
					       pc_now,
					       (uint32_t)dut->io_debug_instr,
					       lsu_pc,
					       (unsigned)dut->rootp->SimTop__DOT__core__DOT__has_ret,
					       (unsigned)dut->rootp->SimTop__DOT__core__DOT__ret_redirect,
					       (unsigned)dut->rootp->SimTop__DOT__core__DOT__retConsumed,
					       (unsigned)dut->rootp->SimTop__DOT__core__DOT___lsu_io_valid_out,
					       (unsigned)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__out_trap_is_ret,
					       (unsigned)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__out_trap_ret_type,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT___csr_io_epc_out,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mepc,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__sepc);
				}
			}
			if (trace_csr && dut->rootp->SimTop__DOT__core__DOT__csr__DOT__io_wvalid &&
			    dut->rootp->SimTop__DOT__core__DOT__csr__DOT__io_wwrite)
			{
				uint32_t csr_addr = dut->rootp->SimTop__DOT__core__DOT__csr__DOT__io_waddr;
				if (csr_addr == 0x105 || csr_addr == 0x140 || csr_addr == 0x141 ||
				    csr_addr == 0x300 || csr_addr == 0x305 || csr_addr == 0x340 || csr_addr == 0x341)
				{
					printf("[csr-trace %6" PRIu64 "] pc=0x%016" PRIx64 " instr=0x%08x"
					       " addr=0x%03x wdata=0x%016" PRIx64
					       " mepc=0x%016" PRIx64 " sepc=0x%016" PRIx64 " mscratch=0x%016" PRIx64 "\n",
					       sim_time,
					       pc_now,
					       (uint32_t)dut->io_debug_instr,
					       csr_addr,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__io_wwdata,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mepc,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__sepc,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mscratch);
				}
			}

			bool prev_in_sram = prev_pc_valid && prev_pc >= opts.sram_base && prev_pc < opts.sram_base + opts.sram_size;
			bool pc_in_sram = pc_now >= opts.sram_base && pc_now < opts.sram_base + opts.sram_size;
			if (trace_pc_escape && !saw_pc_escape && prev_in_sram && !pc_in_sram)
			{
				saw_pc_escape = true;
				uint64_t ra = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[1];
				uint64_t sp = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[2];
				uint64_t t0 = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[5];
				uint64_t a0_trace = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[10];
				uint64_t a1_trace = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[11];
				uint64_t a2_trace = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[12];
				uint64_t a7_trace = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[17];
				printf("[pc-escape %6" PRIu64 "] prev_pc=0x%016" PRIx64 " pc=0x%016" PRIx64
				       " instr=0x%08x pc_reg=0x%016" PRIx64
				       " alu_br_v=%u alu_br_t=%u alu_br_red=%u alu_br_pc=0x%016" PRIx64 " alu_br_tgt=0x%016" PRIx64
				       " alu_r_br_v=%u alu_r_br_t=%u alu_r_br_red=%u alu_r_br_pc=0x%016" PRIx64 " alu_r_br_tgt=0x%016" PRIx64
				       " alu_v=%u alu_pc=0x%016" PRIx64 " alu_rd=%u alu_w=%u alu_res=0x%016" PRIx64
				       " id_issue=%u id_issued=%u id_pc=0x%016" PRIx64 " id_rd=%u id_w=%u id_op1=0x%016" PRIx64 " id_op2=0x%016" PRIx64
				       " wb_w=%u wb_rd=%u wb_data=0x%016" PRIx64
				       " ra=0x%016" PRIx64 " sp=0x%016" PRIx64 " t0=0x%016" PRIx64
				       " a0=0x%016" PRIx64 " a1=0x%016" PRIx64 " a2=0x%016" PRIx64 " a7=0x%016" PRIx64
				       " mtvec=0x%016" PRIx64 " mepc=0x%016" PRIx64 " mcause=0x%016" PRIx64 " mtval=0x%016" PRIx64 "\n",
				       sim_time,
				       prev_pc,
				       pc_now,
				       (uint32_t)dut->io_debug_instr,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__pc__DOT__ProgramCounter,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___alu_io_br_info_valid,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___alu_io_br_info_taken,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___alu_io_br_info_redirect,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT___alu_io_br_info_pc,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT___alu_io_br_info_target,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_br_info_r_valid,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_br_info_r_taken,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_br_info_r_redirect,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_br_info_r_pc,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_br_info_r_target,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_valid_out_r,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_pc_out_r,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_alu_out_rd_r,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_alu_out_reg_write_r,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_alu_out_result_r,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__issueIdToAlu,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__idIssuedValid,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__idIssuedPc,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__idecode__DOT__io_decoded_out_rd,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__idecode__DOT__io_decoded_out_ctrl_reg_write,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__idecode__DOT__io_decoded_out_op1,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__idecode__DOT__io_decoded_out_op2,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___wb_io_reg_wb_reg_write,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___wb_io_reg_wb_rd,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT___wb_io_reg_wb_data,
				       ra,
				       sp,
				       t0,
				       a0_trace,
				       a1_trace,
				       a2_trace,
				       a7_trace,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mtvec,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mepc,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mcause,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mtval);
			}
			prev_pc = pc_now;
			prev_pc_valid = true;

			if (!saw_rom_pc && commit_valid && commit_pc >= BROM_BASE && commit_pc < BROM_BASE + ROM_SIZE)
			{
				saw_rom_pc = true;
				if (trace_boot)
					printf("[boot-trace %6" PRIu64 "] retired in ROM pc=0x%016" PRIx64 "\n", sim_time, commit_pc);
			}
			if (!saw_sram_pc && commit_valid && commit_pc >= opts.sram_base && commit_pc < opts.sram_base + opts.sram_size)
			{
				saw_sram_pc = true;
				if (trace_boot)
					printf("[boot-trace %6" PRIu64 "] retired in SRAM pc=0x%016" PRIx64 "\n", sim_time, commit_pc);
			}
			if (!saw_payload_pc && commit_valid && commit_pc >= opts.boot_a2 && commit_pc < opts.boot_a2 + 0x10000)
			{
				saw_payload_pc = true;
				if (trace_boot)
					printf("[boot-trace %6" PRIu64 "] retired in payload pc=0x%016" PRIx64 "\n", sim_time, commit_pc);
				if (stop_on_payload_entry)
				{
					stopped_on_payload_entry = true;
					saw_exit = true;
					stop_reason = "payload-entry";
					sim_time++;
					break;
				}
			}
			if (trace_boot && dut->rootp->SimTop__DOT__core__DOT__combined_trap)
			{
					printf("[boot-trace %6" PRIu64 "] trap pc=0x%016" PRIx64 " mtvec=0x%016" PRIx64
					       " mepc=0x%016" PRIx64 " mcause=0x%016" PRIx64
					       " stvec=0x%016" PRIx64 " sepc=0x%016" PRIx64
					       " scause=0x%016" PRIx64 " stval=0x%016" PRIx64
					       " sscratch=0x%016" PRIx64 " tp=0x%016" PRIx64 " sp=0x%016" PRIx64
					       " ra=0x%016" PRIx64 " s0=0x%016" PRIx64 " s1=0x%016" PRIx64
					       " a0=0x%016" PRIx64 " a1=0x%016" PRIx64 " a2=0x%016" PRIx64
					       " a3=0x%016" PRIx64 " a4=0x%016" PRIx64 " a5=0x%016" PRIx64
					       " s2=0x%016" PRIx64 " s3=0x%016" PRIx64 " s4=0x%016" PRIx64
					       " s5=0x%016" PRIx64 " s6=0x%016" PRIx64 " s7=0x%016" PRIx64
					       " s8=0x%016" PRIx64 " s9=0x%016" PRIx64 " s10=0x%016" PRIx64 "\n",
					       sim_time,
					       pc_now,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mtvec,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mepc,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mcause,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__stvec,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__sepc,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__scause,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__stval,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__sscratch,
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[4],
				       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[2],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[1],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[8],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[9],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[10],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[11],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[12],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[13],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[14],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[15],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[18],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[19],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[20],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[21],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[22],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[23],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[24],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[25],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[26]);
				}
#ifdef ION_LINUX_PROFILE
				if (trace_lsu_ptw)
				{
				const uint64_t req_vaddr = (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_req_bits_vaddr;
				const uint64_t reg_vaddr = (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__reqReg_vaddr;
				const uint64_t fault_value = (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_resp_bits_fault_value;
				const uint8_t state = dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__state;
				const uint8_t level = dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__level;
				const bool target_match = trace_lsu_ptw_vaddr == 0 ||
				                          trace_lsu_ptw_vaddr == req_vaddr ||
				                          trace_lsu_ptw_vaddr == reg_vaddr ||
				                          trace_lsu_ptw_vaddr == fault_value;
				const bool event =
				    dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_req_valid ||
				    dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_resp_valid ||
				    dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_mem_req_valid ||
				    dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_mem_resp_valid ||
				    state != last_lsu_ptw_state ||
				    level != last_lsu_ptw_level;
				if (target_match && event)
				{
					printf("[lsu-ptw-trace %6" PRIu64 "] pc=0x%016" PRIx64 " instr=0x%08x"
					       " state=%u level=%u req_v=%u req_va=0x%016" PRIx64
					       " reg_va=0x%016" PRIx64 " satp=0x%016" PRIx64
					       " table=0x%016" PRIx64 " mem_req_v=%u mem_req_r=%u mem_addr=0x%016" PRIx64
					       " mem_resp_v=%u mem_resp_r=%u mem_err=%u pte=0x%016" PRIx64
					       " tr_leaf=%u tr_fault=%u tr_pa=0x%016" PRIx64
					       " resp_v=%u resp_pa=0x%016" PRIx64 " fault=%u cause=0x%016" PRIx64
					       " value=0x%016" PRIx64 " priv=%u sum=%u mxr=%u\n",
					       sim_time,
					       (uint64_t)dut->io_debug_pc,
					       (uint32_t)dut->io_debug_instr,
					       (uint32_t)state,
					       (uint32_t)level,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_req_valid,
					       req_vaddr,
					       reg_vaddr,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_req_bits_satp,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__tableBase,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_mem_req_valid,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_mem_req_ready,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_mem_req_bits_addr,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_mem_resp_valid,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_mem_resp_ready,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_mem_resp_bits_err,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_mem_resp_bits_rdata,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__translator__DOT__io_leaf,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__translator__DOT__io_fault_valid,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__translator__DOT__io_paddr,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_resp_valid,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_resp_bits_paddr,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_resp_bits_fault_valid,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_resp_bits_fault_cause,
					       fault_value,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__reqReg_priv,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__reqReg_sum,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__reqReg_mxr);
				}
				last_lsu_ptw_state = state;
				last_lsu_ptw_level = level;
			}
				if (trace_dmem)
				{
				const uint64_t req_addr = (uint64_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheReq_bits_addr;
				const bool pc_match = pc_now >= trace_dmem_pc_start && pc_now <= trace_dmem_pc_end;
				const bool req_match = trace_dmem_addr == 0 || trace_dmem_addr == req_addr;
				const bool resp_match = trace_dmem_addr == 0 || req_match ||
				                        trace_dmem_addr == (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_req_bits_addr ||
				                        trace_dmem_addr == (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_mem_req_bits_addr;
				const bool req_event =
				    pc_match && dut->rootp->SimTop__DOT__core__DOT___dcacheArbiter_io_cacheReq_valid && req_match;
				const bool resp_event =
				    pc_match && dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheResp_valid && resp_match;
				if (req_event || resp_event)
				{
					printf("[dmem-trace %6" PRIu64 "] pc=0x%016" PRIx64 " instr=0x%08x"
					       " req_v=%u req_r=%u req_fire=%u cmd=%u addr=0x%016" PRIx64
					       " wdata=0x%016" PRIx64 " mask=0x%02x owner_ptw=%u pending=%u"
					       " resp_v=%u resp_r=%u resp_fire=%u resp_err=%u rdata=0x%016" PRIx64
					       " lsu_req_addr=0x%016" PRIx64 " lsu_ptw_req_addr=0x%016" PRIx64 "\n",
					       sim_time,
					       (uint64_t)dut->io_debug_pc,
					       (uint32_t)dut->io_debug_instr,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___dcacheArbiter_io_cacheReq_valid,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheReq_ready,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__cacheReqFire,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheReq_bits_cmd,
					       req_addr,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheReq_bits_wdata,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheReq_bits_mask,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__respOwnerPtw,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__respPending,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheResp_valid,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheResp_ready,
					       (uint32_t)(dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheResp_valid &&
					                  dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheResp_ready),
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheResp_bits_err,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheResp_bits_rdata,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_req_bits_addr,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__ptw__DOT__io_mem_req_bits_addr);
					}
				}
#endif
				if (trace_atomic)
			{
				const uint64_t atomic_vaddr = (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicAccess_vaddr;
				const uint64_t atomic_paddr = (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicAccess_paddr;
				const uint64_t req_addr = (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_req_bits_addr;
				const bool target_match = trace_atomic_addr == 0 ||
				                          trace_atomic_addr == atomic_vaddr ||
				                          trace_atomic_addr == atomic_paddr ||
				                          trace_atomic_addr == req_addr;
				const bool atomic_active =
				    dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__raw_atomic_req ||
				    dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__new_atomic_req ||
				    dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__do_atomic_read_req ||
				    dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__do_atomic_write_req ||
				    dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicRespValid;
				if (atomic_active && target_match)
				{
					printf("[atomic-trace %6" PRIu64 "] pc=0x%016" PRIx64 " instr=0x%08x"
					       " raw=%u new=%u pend=%u rd_sent=%u wr_sent=%u do_wr=%u resp_v=%u"
					       " op=%u atom=%u size=%u mask=0x%02x"
					       " vaddr=0x%016" PRIx64 " paddr=0x%016" PRIx64
					       " awdata=0x%016" PRIx64 " wrdata=0x%016" PRIx64
					       " old=0x%016" PRIx64 " resp=0x%016" PRIx64
					       " req_v=%u req_r=%u req_cmd=%u req_addr=0x%016" PRIx64
					       " req_wdata=0x%016" PRIx64 " req_mask=0x%02x resp_in=%u resp_err=%u resp_data=0x%016" PRIx64
					       " rs1/a0=0x%016" PRIx64 " rs2/a3=0x%016" PRIx64 " s0=0x%016" PRIx64
					       " s1=0x%016" PRIx64 " s2=0x%016" PRIx64 "\n",
					       sim_time,
					       pc_now,
					       (uint32_t)dut->io_debug_instr,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__raw_atomic_req,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__new_atomic_req,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicPending,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicReadSent,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicWriteSent,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicDoWrite,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicRespValid,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicAccess_op,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicAccess_atomic,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicAccess_size,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicAccess_mask,
					       atomic_vaddr,
					       atomic_paddr,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicAccess_wdata,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicWriteData,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicOldData,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__atomicRespData,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_req_valid,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_req_ready,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_req_bits_cmd,
					       req_addr,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_req_bits_wdata,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_req_bits_mask,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_resp_valid,
					       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_resp_bits_err,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_resp_bits_rdata,
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[10],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[13],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[8],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[9],
					       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[18]);
				}
			}
		}

		bool trace_pc_match = pc_now >= trace_pc_start && pc_now <= trace_pc_end;
		if (trace_cpu && trace_pc_match && dut->clock && (trace_cpu_every || sim_time < 150 || dut->io_debug_pc != last_pc || trace_state_change))
		{
			last_pc = pc_now;
			last_mtimecmp = cur_mtimecmp;
			last_mtip = cur_mtip;
			uint64_t ra = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[1];
			uint64_t t0 = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[5];
			uint64_t s0 = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[8];
			uint64_t s1 = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[9];
			uint64_t s2 = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[18];
			uint64_t t3 = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[28];
			uint64_t t4 = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[29];
			uint64_t t5 = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[30];
			uint64_t a0_trace = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[10];
			uint64_t a1_trace = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[11];
			uint64_t a2_trace = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[12];
			uint64_t a3_trace = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[13];
			uint64_t a4_trace = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[14];
			uint64_t a5_trace = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[15];
			uint64_t a6_trace = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[16];
			uint64_t a7_trace = dut->rootp->SimTop__DOT__core__DOT__register__DOT__regFile_ext__DOT__Memory[17];
			printf("[trace %6" PRIu64 "] pc=0x%016" PRIx64 " instr=0x%08x ra=0x%016" PRIx64 " t0=0x%016" PRIx64 " s0=0x%016" PRIx64 " s1=0x%016" PRIx64 " s2=0x%016" PRIx64 " t3=0x%016" PRIx64 " t4=0x%016" PRIx64 " t5=0x%016" PRIx64 " a0=0x%016" PRIx64 " a1=0x%016" PRIx64 " a2=0x%016" PRIx64 " a3=0x%016" PRIx64 " a4=0x%016" PRIx64 " a5=0x%016" PRIx64 " a6=0x%016" PRIx64 " a7=0x%016" PRIx64
				   " id_v=%u id_rd=%u id_w=%u id_op1=0x%016" PRIx64 " id_op2=0x%016" PRIx64
				   " lsu_stall=%u load_valid=%u load_rd=%u load=0x%016" PRIx64 " alu_v=%u alu_rd=%u alu_w=%u alu_mem_v=%u alu_mem_op=%u alu_res=0x%016" PRIx64 " alu_pc=0x%016" PRIx64 " alu_op1=0x%016" PRIx64 " alu_op2=0x%016" PRIx64
				   " lsu_v=%u lsu_rd=%u lsu_w=%u lsu_res=0x%016" PRIx64 " wb_rd=%u wb_w=%u wb_data=0x%016" PRIx64
				   " br_v=%u br_t=%u br_red=%u exbp_v=%u exbp_rd=%u exbp_data=0x%016" PRIx64
				   " fwd_v=%u fwd_rd=%u fwd_data=0x%016" PRIx64 " prev_v=%u prev_rd=%u prev_data=0x%016" PRIx64
				   " fq_flush=%u decode_stall=%u"
				   " sb_p=%u sb_rd=%u sb_new=%u sb_done=%u sb_inst=%u sb_inst_rd=%u"
				   " pc_stall=%u if_stall=%u if_in_pc=0x%016" PRIx64
					   " if_state=%u if_acc=%u if_req_pc=0x%016" PRIx64 " if_req_pa=0x%016" PRIx64
#ifdef ION_LINUX_PROFILE
					   " if_xp=%u if_xd=%u if_xlate=%u if_issue=%u if_start_xlate=%u if_req_v=%u"
					   " if_trap_v=%u if_trap_c=0x%016" PRIx64 " if_trap_tval=0x%016" PRIx64
					   " ptw_state=%u ptw_level=%u ptw_req_v=%u ptw_req_va=0x%016" PRIx64
				   " ptw_mem_req_v=%u ptw_mem_req_r=%u ptw_mem_addr=0x%016" PRIx64
				   " ptw_mem_resp_v=%u ptw_mem_resp_r=%u ptw_resp_v=%u ptw_fault=%u"
					   " ptw_table=0x%016" PRIx64 " ptw_reg_va=0x%016" PRIx64
					   " dc_ptw_owner=%u dc_pending=%u dc_req_fire=%u dc_resp_fire=%u"
					   " if_xlate_rdy=%u if_xlate_pa=0x%016" PRIx64
#endif
					   " if_pc=0x%016" PRIx64 " if_instr=0x%08x if_len=%u pc_step=%u pc_hold=%u bpu_taken=%u"
				   " redirect=%u int_p=%u int_f=%u trap=%u flush=%u priv=%u satp=0x%016" PRIx64
				   " mtvec=0x%016" PRIx64 " mepc=0x%016" PRIx64 " mcause=0x%016" PRIx64
				   " sepc=0x%016" PRIx64 " scause=0x%016" PRIx64 " mtval=0x%016" PRIx64
				   " mstatus=0x%016" PRIx64 " mie=0x%016" PRIx64 " plic_src1=%u mtip=%u mtime=0x%016" PRIx64 " mtimecmp=0x%016" PRIx64 "\n",
				   sim_time,
				   (uint64_t)dut->io_debug_pc,
				   (uint32_t)dut->io_debug_instr,
				   ra,
				   t0,
				   s0,
				   s1,
				   s2,
				   t3,
				   t4,
				   t5,
				   a0_trace,
				   a1_trace,
				   a2_trace,
				   a3_trace,
				   a4_trace,
				   a5_trace,
				   a6_trace,
				   a7_trace,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__idecode__DOT__io_valid_out,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__idecode__DOT__io_decoded_out_rd,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__idecode__DOT__io_decoded_out_ctrl_reg_write,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__idecode__DOT__io_decoded_out_op1,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__idecode__DOT__io_decoded_out_op2,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_stall_req_0,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT___lsu_io_load_data_valid,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT___lsu_io_load_data_rd,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT___lsu_io_load_data,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_valid_out_r,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_alu_out_rd_r,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_alu_out_reg_write_r,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_alu_out_mem_valid_r,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_alu_out_mem_op_r,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_alu_out_result_r,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_pc_out_r,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__op1,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__op2,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT___lsu_io_valid_out,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__out_reg_rd,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__out_reg_write,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__out_result,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT___wb_io_reg_wb_rd,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT___wb_io_reg_wb_reg_write,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT___wb_io_reg_wb_data,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__branch_valid,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__branch_taken,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__branchRedirect,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__exBypassValid,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__exBypassRd,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__exBypassData,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__aluResultFwdValid,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__aluResultFwdRd,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__aluResultFwdData,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__aluResultPrevValid,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__aluResultPrevRd,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__aluResultPrevData,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__frontendQueueFlush,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__decodeStall,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__loadScoreboard__DOT__io_pending,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__loadScoreboard__DOT__io_pendingRd,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__loadScoreboard__DOT__io_newLoadLike,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__loadScoreboard__DOT__io_complete,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__loadScoreboard__DOT__io_issued,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__loadScoreboard__DOT__io_issuedRd,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__pc__DOT__io_stall,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT___ifetch_io_fetch_stall,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__io_pc,
					   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__state,
					   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__acceptResp,
					   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__reqPc,
					   (uint64_t)dut->rootp->SimTop__DOT__core__DOT___ifetch_io_cache_req_bits_addr,
#ifdef ION_LINUX_PROFILE
					   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__xlatePending,
					   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__xlateDone,
					   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__translateFetch,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__canIssue,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__startTranslation,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__normalFetchReqValid,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__fetchTrap_valid,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__fetchTrap_cause,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__fetchTrap_value,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__state,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__level,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__io_req_valid,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__io_req_bits_vaddr,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__io_mem_req_valid,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__io_mem_req_ready,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__io_mem_req_bits_addr,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__io_mem_resp_valid,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__io_mem_resp_ready,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__io_resp_valid,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__io_resp_bits_fault_valid,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__tableBase,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__ptw__DOT__reqReg_vaddr,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__respOwnerPtw,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__respPending,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__cacheReqFire,
				   (uint32_t)(dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheResp_valid &&
				              dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheResp_ready),
					   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__translatedReady,
					   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__xlatePaddr,
#endif
					   (uint64_t)dut->rootp->SimTop__DOT__core__DOT___ifetch_io_pc_out,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT___ifetch_io_instr_out,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT___ifetch_io_instr_len,
					   (uint32_t)dut->rootp->SimTop__DOT__core__DOT___ifetch_io_pc_step_len,
					   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__pc__DOT__redirectHold,
					   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__pc__DOT___bpu_io_pred_taken,
					   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__pc__DOT__redirect,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__interruptPending,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__interrupt_fire,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__combined_trap,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__combined_trap,
				   (uint32_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__CurrentPrivLevel,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__satp,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mtvec,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mepc,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mcause,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__sepc,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__scause,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mtval,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mstatus,
				   (uint64_t)dut->rootp->SimTop__DOT__core__DOT__csr__DOT__mie,
				   (uint32_t)dut->rootp->io_ext_irq_sources_1,
				   (uint32_t)cur_mtip,
				   (uint64_t)dut->rootp->SimTop__DOT__clint__DOT__mtime,
				   cur_mtimecmp);
		}
		irq.sample(dut, sim_time);
		if (opts.trace_dmi)
		{
			uint8_t dmi_valid = dut->rootp->SimTop__DOT__debugModule_io_dmi_valid_REG;
			if (dmi_valid && !last_dmi_valid)
			{
				uint64_t dr = dut->rootp->SimTop__DOT__jtag__DOT__drUpdate;
				unsigned op = dr & 0x3;
				unsigned addr = (dr >> 34) & 0x7f;
				uint32_t wdata = (uint32_t)((dr >> 2) & 0xffffffffu);
				uint32_t rdata = dut->rootp->SimTop__DOT___debugModule_io_dmi_rdata;
				uint32_t dmcontrol = dut->rootp->SimTop__DOT__debugModule__DOT__dmcontrol;
				uint32_t dmstatus = dut->rootp->SimTop__DOT__debugModule__DOT__dmstatus;
				printf("[dmi %6" PRIu64 "] op=%u addr=0x%02x wdata=0x%08x rdata=0x%08x dmcontrol=0x%08x dmstatus=0x%08x\n",
				       sim_time, op, addr, wdata, rdata, dmcontrol, dmstatus);
			}
			last_dmi_valid = dmi_valid;
		}

		if (dut->clock)
			uart.capture_tx(dut);
		if (opts.stop_on_uart_match && !opts.expected_uart.empty() &&
		    uart.output().find(opts.expected_uart) != std::string::npos)
		{
			stopped_on_uart_match = true;
			saw_exit = true;
			stop_reason = "uart-match";
			sim_time++;
			break;
		}

		if (!opts.jtag_only && !disable_exit_check && dut->clock &&
		    dut->io_debug_gpr_snapshot_17 == 93)
		{
			saw_exit = true;
			stop_reason = "exit-sentinel";
			sim_time++;
			break;
		}

		if (no_retire_timeout_hit)
		{
			stop_reason = "no-retire-timeout";
			printf("[watchdog]: no retired instruction for %" PRIu64
			       " cycles (cycle=%" PRIu64 ", tick=%" PRIu64 ")\n",
			       no_retire_timeout,
			       core_cycle,
			       sim_time);
			sim_time++;
			break;
		}

		sim_time++;
	}
	if (Verilated::gotError())
		stop_reason = "verilator-error";
	else if (Verilated::gotFinish() && std::strcmp(stop_reason, "max-ticks") == 0)
		stop_reason = "verilator-finish";

	printf("\n--- UART output end ---\n");

	uint64_t gp = dut->io_debug_gpr_snapshot_3;
	uint64_t a0 = dut->io_debug_gpr_snapshot_10;
	uint64_t a7 = dut->io_debug_gpr_snapshot_17;
	if (trace_boot)
	{
		printf("[boot-trace end] cycles=%" PRIu64 " pc=0x%016" PRIx64 " instr=0x%08x mtvec=0x%016" PRIx64
		       " mepc=0x%016" PRIx64 " mcause=0x%016" PRIx64 " a0=0x%016" PRIx64 " a1=0x%016" PRIx64
		       " a2=0x%016" PRIx64 " a7=0x%016" PRIx64
		       " fence_start=%u fence_pending=%u fence_issued=%u fence_active=%u fence_ack=%u\n",
		       sim_time,
		       (uint64_t)dut->io_debug_pc,
		       (uint32_t)dut->io_debug_instr,
		       (uint64_t)dut->io_debug_csr_snapshot_mtvec,
		       (uint64_t)dut->io_debug_csr_snapshot_mepc,
		       (uint64_t)dut->io_debug_csr_snapshot_mcause,
		       (uint64_t)dut->io_debug_gpr_snapshot_10,
		       (uint64_t)dut->io_debug_gpr_snapshot_11,
		       (uint64_t)dut->io_debug_gpr_snapshot_12,
		       (uint64_t)dut->io_debug_gpr_snapshot_17,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__fenceIStart,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__fenceIPending,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__fenceIFlushIssued,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__fenceIActive,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__fenceIAck);
#ifdef ION_LINUX_PROFILE
			if (dut->rootp->__PVT__SimTop__DOT__core__DOT__icache != nullptr)
			{
				printf("[boot-trace cache] ifetch_state=%u ifetch_req=%u ifetch_ptw_req=%u ifetch_ptw_resp=%u icache_state=%u icache_req_ready=%u icache_resp_valid=%u icache_inv_ready=%u bus_a_valid=%u bus_d_ready=%u\n",
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__state,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__io_cache_req_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__io_ptw_req_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__io_ptw_resp_valid,
			       (uint32_t)dut->rootp->__PVT__SimTop__DOT__core__DOT__icache->state,
			       (uint32_t)dut->rootp->__PVT__SimTop__DOT__core__DOT__icache->io_cpu_req_ready,
			       (uint32_t)dut->rootp->__PVT__SimTop__DOT__core__DOT__icache->io_cpu_resp_valid,
			       (uint32_t)dut->rootp->__PVT__SimTop__DOT__core__DOT__icache->io_invalidate_ready,
			       (uint32_t)dut->rootp->__PVT__SimTop__DOT__core__DOT__icache->io_bus_a_valid,
			       (uint32_t)dut->rootp->__PVT__SimTop__DOT__core__DOT__icache->io_bus_d_ready);
		}
		if (dut->rootp->__PVT__SimTop__DOT__core__DOT__L1Cache != nullptr)
		{
			printf("[boot-trace dcache] arb_pending=%u arb_owner_ptw=%u d_req_v=%u d_req_r=%u d_resp_v=%u d_resp_r=%u lsu_req_v=%u lsu_req_r=%u lsu_resp_v=%u lsu_resp_r=%u ptw_req_v=%u ptw_req_r=%u ptw_resp_v=%u ptw_resp_r=%u state=%u bus_a_valid=%u bus_d_ready=%u\n",
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__respPending,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__respOwnerPtw,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___dcacheArbiter_io_cacheReq_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheReq_ready,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___L1Cache_io_cpu_resp_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__dcacheArbiter__DOT__io_cacheResp_ready,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_req_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_req_ready,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_resp_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_resp_ready,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__io_ptw_req_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__io_ptw_req_ready,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__io_ptw_resp_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__ifetch__DOT__io_ptw_resp_ready,
			       (uint32_t)dut->rootp->__PVT__SimTop__DOT__core__DOT__L1Cache->state,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___L1Cache_io_bus_a_valid,
				       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___L1Cache_io_bus_d_ready);
			}
#endif
			printf("[boot-trace lsu] op=%u is_load=%u is_store=%u raw_xlate=%u xlate_not_ready=%u xlate_busy=%u xlate_pending=%u xlate_done=%u raw_cache_load=%u new_cache_load=%u cache_pending=%u raw_load_hit_sb=%u\n",
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__memAccess_op,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__is_load,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__is_store,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__rawNeedsTranslation,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__translationNotReady,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__translationBusy,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__xlatePending,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__xlateDone,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__raw_cache_load,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__new_cache_load,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__cacheLoadPending,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__raw_load_hit_sb);
		printf("[boot-trace frontend] global_stall=%u pipe_stall=%u decode_stall=%u decode_uses_pending=%u lsu_stall=%u lsu_load=%u lsu_store=%u lsu_mmio=%u lsu_atomic=%u lsu_fence=%u load_pending=%u load_rd=%u queue_full=%u queue_empty=%u queue_count=%u head=%u tail=%u id_valid=%u id_rd=%u id_w=%u alu_valid=%u alu_pc=0x%016" PRIx64 " wb_w=%u wb_rd=%u\n",
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__global_stall,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___global_stall_T,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__decodeStall,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__loadScoreboard__DOT__io_decodeUsesPending,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_stall_req,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_stall_load,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_stall_store,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_stall_mmio,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_stall_atomic,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_stall_fence,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__loadScoreboard__DOT__io_pending,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__loadScoreboard__DOT__io_pendingRd,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__frontendQueue__DOT__io_full,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__frontendQueue__DOT__io_empty,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__frontendQueue__DOT__count,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__frontendQueue__DOT__head,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__frontendQueue__DOT__tail,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__idecode__DOT__io_valid_out,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__idecode__DOT__io_decoded_out_rd,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__idecode__DOT__io_decoded_out_ctrl_reg_write,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_valid_out_r,
		       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__alu__DOT__io_pc_out_r,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___wb_io_reg_wb_reg_write,
		       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___wb_io_reg_wb_rd);
		if (dut->rootp->__PVT__SimTop__DOT__core__DOT__L1Cache != nullptr)
		{
			auto *dcache = dut->rootp->__PVT__SimTop__DOT__core__DOT__L1Cache;
			printf("[boot-trace lsu] stall=%u raw_load=%u new_load=%u load_pending=%u load_sent=%u load_split=%u load_second=%u load_size=%u load_paddr=0x%016" PRIx64 " load_vaddr=0x%016" PRIx64 " store_pending=%u sb_count=%u sb_valid=%u d_req=%u d_ready=%u d_addr=0x%08x d_resp=%u dcache_state=%u dcache_resp=%u dcache_req_ready=%u dcache_req_addr=0x%08x\n",
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_stall_req_0,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__raw_cache_load,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__new_cache_load,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__cacheLoadPending,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__cacheLoadSent,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__cacheLoadSplit,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__cacheLoadSecond,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__cacheLoadAccess_size,
			       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__cacheLoadAccess_paddr,
			       (uint64_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__cacheLoadAccess_vaddr,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__storeDrainPending,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__storeBuffer__DOT__count,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__storeBuffer__DOT__io_deq_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT___lsu_io_dcache_req_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_req_ready,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_req_bits_addr,
			       (uint32_t)dut->rootp->SimTop__DOT__core__DOT__lsu__DOT__io_dcache_resp_valid,
			       (uint32_t)dcache->state,
			       (uint32_t)dcache->io_cpu_resp_valid,
			       (uint32_t)dcache->io_cpu_req_ready,
			       (uint32_t)dcache->io_cpu_req_bits_addr);
			printf("[boot-trace dcache-tl] req_reg=0x%08x a_valid=%u a_ready=%u a_op=%u a_addr=0x%08x d_valid=%u d_ready=%u d_denied=%u d_data=0x%016" PRIx64 " c_valid=%u c_ready=%u c_src=%u\n",
			       (uint32_t)dcache->reqReg_addr,
			       (uint32_t)dcache->io_bus_a_valid,
			       (uint32_t)dcache->io_bus_a_ready,
			       (uint32_t)dcache->io_bus_a_bits_opcode,
			       (uint32_t)dcache->io_bus_a_bits_address,
			       (uint32_t)dcache->io_bus_d_valid,
			       (uint32_t)dcache->io_bus_d_ready,
			       (uint32_t)dcache->io_bus_d_bits_denied,
			       (uint64_t)dcache->io_bus_d_bits_data,
			       (uint32_t)dcache->io_bus_c_valid,
			       (uint32_t)dcache->io_bus_c_ready,
			       (uint32_t)dcache->io_bus_c_bits_source);
			printf("[boot-trace sram] a_valid=%u a_ready=%u a_op=%u a_src=%u a_addr=0x%08x d_valid=%u d_ready=%u d_op=%u d_src=%u d_denied=%u resp_valid=%u resp_src=%u resp_data=0x%016" PRIx64 " req_valid=%u q_valid=%u q_op=%u q_src=%u q_addr=0x%08x\n",
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__io_tl_a_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__io_tl_a_ready,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__io_tl_a_bits_opcode,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__io_tl_a_bits_source,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__io_tl_a_bits_address,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__io_tl_d_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__io_tl_d_ready,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__io_tl_d_bits_opcode,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__io_tl_d_bits_source,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__io_tl_d_bits_denied,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__resp_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__resp_source,
			       (uint64_t)dut->rootp->SimTop__DOT__sram__DOT__resp_data,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__req_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT___req_queue_q_io_deq_valid,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT___req_queue_q_io_deq_bits_opcode,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT___req_queue_q_io_deq_bits_source,
			       (uint32_t)dut->rootp->SimTop__DOT__sram__DOT__req_queue_q__DOT__io_deq_bits_address);
		}
	}

	bool uart_pass = opts.expected_uart.empty() || (uart.output().find(opts.expected_uart) != std::string::npos);
	bool boot_flow_pass = (!opts.require_sram_entry || saw_sram_pc) &&
	                      (!opts.require_payload_entry || saw_payload_pc);
	bool pass = !Verilated::gotError() && !no_retire_timeout_hit && !stop_pc_hit &&
	            (opts.jtag_only ? true :
	                              (stopped_on_payload_entry && boot_flow_pass) ||
	                                  (opts.accept_uart_match && uart_pass && boot_flow_pass) ||
	                                  (saw_exit && a7 == 93 && a0 == 0 && uart_pass && boot_flow_pass));
	if (opts.perf_report)
	{
		double ipc = perf_cycles == 0 ? 0.0 : (double)perf_retired / (double)perf_cycles;
		double stall_pct = perf_cycles == 0 ? 0.0 : (100.0 * (double)perf_stall_cycles / (double)perf_cycles);
		double ifetch_pct = perf_cycles == 0 ? 0.0 : (100.0 * (double)perf_ifetch_stall_cycles / (double)perf_cycles);
		double lsu_pct = perf_cycles == 0 ? 0.0 : (100.0 * (double)perf_lsu_stall_cycles / (double)perf_cycles);
		double branch_rate = perf_retired == 0 ? 0.0 : (100.0 * (double)perf_branch_count / (double)perf_retired);
		double branch_taken_pct = perf_branch_count == 0 ? 0.0 : (100.0 * (double)perf_branch_taken / (double)perf_branch_count);
		double branch_redirect_pct = perf_branch_count == 0 ? 0.0 : (100.0 * (double)perf_branch_redirect / (double)perf_branch_count);
		double branch_pred_taken_pct = perf_branch_count == 0 ? 0.0 : (100.0 * (double)perf_branch_pred_taken / (double)perf_branch_count);
		double branch_pred_correct_pct = perf_branch_count == 0 ? 0.0 : (100.0 * (double)perf_branch_pred_correct / (double)perf_branch_count);
		printf("[perf]: cycles=%" PRIu64 " retired=%" PRIu64 " ipc=%.4f stall_cycles=%" PRIu64 " stall_pct=%.2f ifetch_stall=%" PRIu64 " ifetch_pct=%.2f lsu_stall=%" PRIu64 " lsu_pct=%.2f\n",
		       perf_cycles,
		       perf_retired,
		       ipc,
		       perf_stall_cycles,
		       stall_pct,
		       perf_ifetch_stall_cycles,
		       ifetch_pct,
		       perf_lsu_stall_cycles,
		       lsu_pct);
		printf("[perf-branch]: branches=%" PRIu64 " branch_rate=%.2f taken=%" PRIu64 " taken_pct=%.2f redirects=%" PRIu64 " redirect_pct=%.2f pred_taken=%" PRIu64 " pred_taken_pct=%.2f pred_correct=%" PRIu64 " pred_correct_pct=%.2f\n",
		       perf_branch_count,
		       branch_rate,
		       perf_branch_taken,
		       branch_taken_pct,
		       perf_branch_redirect,
		       branch_redirect_pct,
		       perf_branch_pred_taken,
		       branch_pred_taken_pct,
		       perf_branch_pred_correct,
		       branch_pred_correct_pct);
		printf("[perf-lsu]: load=%" PRIu64 " store=%" PRIu64 " mmio=%" PRIu64 " atomic=%" PRIu64 " fence=%" PRIu64 "\n",
		       perf_lsu_load_stall_cycles,
		       perf_lsu_store_stall_cycles,
		       perf_lsu_mmio_stall_cycles,
		       perf_lsu_atomic_stall_cycles,
		       perf_lsu_fence_stall_cycles);
		printf("[perf-stall-detail]: decode_load_use=%" PRIu64 " lsu_load_only=%" PRIu64 " lsu_store_only=%" PRIu64 " lsu_fence_only=%" PRIu64 "\n",
		       perf_decode_load_use_cycles,
		       perf_lsu_load_only_cycles,
		       perf_lsu_store_only_cycles,
		       perf_lsu_fence_only_cycles);
		printf("[perf-overlap]: ifetch_only=%" PRIu64 " ifetch_lsu_overlap=%" PRIu64 "\n",
		       perf_ifetch_only_stall_cycles,
		       perf_ifetch_lsu_overlap_cycles);
		printf("[perf-frontend]: starved=%" PRIu64 " queue_full=%" PRIu64 " queue_empty=%" PRIu64 "\n",
		       perf_frontend_starved_cycles,
		       perf_frontend_queue_full_cycles,
		       perf_frontend_queue_empty_cycles);
	}

	if (opts.jtag_only)
		printf("[%s]: JTAG server active on port %d%s\n", opts.test_name.c_str(), opts.jtag_rbb_port, CEND);
	else if (pass)
		printf("[%s]: gp=%" PRIu64 ", a7=%" PRIu64 ", a0=%" PRIu64 ", test %spassed%s\n",
		       opts.test_name.c_str(), gp, a7, a0, GREEN, CEND);
	else if (stopped_on_uart_match)
		printf("[%s]: gp=%" PRIu64 ", a7=%" PRIu64 ", a0=%" PRIu64
		       ", uart milestone reached, test %sfailed%s\n",
		       opts.test_name.c_str(), gp, a7, a0, RED, CEND);
	else if (a7 == 93)
		printf("[%s]: gp=%" PRIu64 ", a7=%" PRIu64 ", a0=%" PRIu64
		       ", uart=\"%s\", test %sfailed%s\n",
		       opts.test_name.c_str(), gp, a7, a0, uart.output().c_str(), RED, CEND);
	else
		printf("[%s]: gp=%" PRIu64 ", a7=%" PRIu64 ", a0=%" PRIu64 ", test %sunknown%s\n",
		       opts.test_name.c_str(), gp, a7, a0, YELLOW, CEND);

	if (!opts.jtag_only && !pass)
	{
		printf("[sim-fail]: reason=%s saw_exit=%u uart_pass=%u boot_flow_pass=%u entered_sram=%u"
		       " entered_payload=%u expected_uart=\"%s\"\n",
		       stop_reason,
		       saw_exit ? 1 : 0,
		       uart_pass ? 1 : 0,
		       boot_flow_pass ? 1 : 0,
		       saw_sram_pc ? 1 : 0,
		       saw_payload_pc ? 1 : 0,
		       opts.expected_uart.c_str());
		printf("[sim-fail]: tick=%" PRIu64 " cycle=%" PRIu64 " retired=%" PRIu64
		       " fetch_pc=0x%016" PRIx64 " fetch_instr=0x%08x mtvec=0x%016" PRIx64
		       " mepc=0x%016" PRIx64 " mcause=0x%016" PRIx64 " mtval=0x%016" PRIx64 "\n",
		       last_eval_tick,
		       core_cycle,
		       arch_history.retired_count(),
		       (uint64_t)dut->io_debug_pc,
		       (uint32_t)dut->io_debug_instr,
		       (uint64_t)dut->io_debug_csr_snapshot_mtvec,
		       (uint64_t)dut->io_debug_csr_snapshot_mepc,
		       (uint64_t)dut->io_debug_csr_snapshot_mcause,
		       (uint64_t)dut->io_debug_csr_snapshot_mtval);
	}
	if ((!opts.jtag_only && !pass) || dump_history_always)
		arch_history.dump(pass ? "requested" : stop_reason);

	wave.close(last_eval_tick);
	dut->final();
	delete dut;
	return pass;
}
