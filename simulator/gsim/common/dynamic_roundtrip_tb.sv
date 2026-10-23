`timescale 1ns/1ps
`default_nettype none
// Native SV functional model, explicitly NOT UNISIM or physical frequency qualification.
module dynamic_roundtrip_tb;
  initial $timeformat(-9,3," ns",0);
  wire  rateBackend_0_present;
  wire  rateBackend_0_gateClosed;
  wire  rateBackend_0_gateOpen;
  wire  rateBackend_0_locked;
  wire  rateBackend_0_resumed;
  wire  rateBackend_0_fatal;
  wire  rateBackend_0_quiesce;
  wire  rateBackend_0_isolate;
  wire  rateBackend_0_clockEnable;
  wire  rateBackend_0_program_ready;
  wire  rateBackend_0_program_valid;
  wire [31:0] rateBackend_0_program_bits_hz;
  wire [23:0] rateBackend_0_program_bits_parameters;
  wire [31:0] rateBackend_0_program_bits_token;
  wire  rateBackend_0_program_bits_fallback;
  wire  rateBackend_0_result_ready;
  wire  rateBackend_0_result_valid;
  wire [31:0] rateBackend_0_result_bits_hz;
  wire [31:0] rateBackend_0_result_bits_token;
  wire  rateBackend_0_result_bits_error;
  wire  rateBackend_1_present;
  wire  rateBackend_1_gateClosed;
  wire  rateBackend_1_gateOpen;
  wire  rateBackend_1_locked;
  wire  rateBackend_1_resumed;
  wire  rateBackend_1_fatal;
  wire  rateBackend_1_quiesce;
  wire  rateBackend_1_isolate;
  wire  rateBackend_1_clockEnable;
  wire  rateBackend_1_program_ready;
  wire  rateBackend_1_program_valid;
  wire [31:0] rateBackend_1_program_bits_hz;
  wire [23:0] rateBackend_1_program_bits_parameters;
  wire [31:0] rateBackend_1_program_bits_token;
  wire  rateBackend_1_program_bits_fallback;
  wire  rateBackend_1_result_ready;
  wire  rateBackend_1_result_valid;
  wire [31:0] rateBackend_1_result_bits_hz;
  wire [31:0] rateBackend_1_result_bits_token;
  wire  rateBackend_1_result_bits_error;
  wire  cpuClock;
  wire  fabricClock;
  reg  alwaysOnClock = 0;
  reg  ddrClock = 0;
  reg  timebaseClock = 0;
  reg  debugClock = 0;
  reg  rawUartClock = 0;
  reg  rawTxClock = 0;
  reg  rawRxClock = 0;
  reg  commonColdReset = 0;
  reg  io_ddrAxi_aw_ready = 1;
  wire  io_ddrAxi_aw_valid;
  wire [3:0] io_ddrAxi_aw_bits_id;
  wire [31:0] io_ddrAxi_aw_bits_addr;
  wire [7:0] io_ddrAxi_aw_bits_len;
  wire [2:0] io_ddrAxi_aw_bits_size;
  wire [1:0] io_ddrAxi_aw_bits_burst;
  wire  io_ddrAxi_aw_bits_lock;
  wire [3:0] io_ddrAxi_aw_bits_cache;
  wire [2:0] io_ddrAxi_aw_bits_prot;
  wire [3:0] io_ddrAxi_aw_bits_qos;
  reg  io_ddrAxi_w_ready = 1;
  wire  io_ddrAxi_w_valid;
  wire [63:0] io_ddrAxi_w_bits_data;
  wire [7:0] io_ddrAxi_w_bits_strb;
  wire  io_ddrAxi_w_bits_last;
  wire  io_ddrAxi_b_ready;
  reg  io_ddrAxi_b_valid = 0;
  reg [3:0] io_ddrAxi_b_bits_id = 0;
  reg [1:0] io_ddrAxi_b_bits_resp = 0;
  reg  io_ddrAxi_ar_ready = 1;
  wire  io_ddrAxi_ar_valid;
  wire [3:0] io_ddrAxi_ar_bits_id;
  wire [31:0] io_ddrAxi_ar_bits_addr;
  wire [7:0] io_ddrAxi_ar_bits_len;
  wire [2:0] io_ddrAxi_ar_bits_size;
  wire [1:0] io_ddrAxi_ar_bits_burst;
  wire  io_ddrAxi_ar_bits_lock;
  wire [3:0] io_ddrAxi_ar_bits_cache;
  wire [2:0] io_ddrAxi_ar_bits_prot;
  wire [3:0] io_ddrAxi_ar_bits_qos;
  wire  io_ddrAxi_r_ready;
  reg  io_ddrAxi_r_valid = 0;
  reg [3:0] io_ddrAxi_r_bits_id = 0;
  reg [63:0] io_ddrAxi_r_bits_data = 0;
  reg [1:0] io_ddrAxi_r_bits_resp = 0;
  reg  io_ddrAxi_r_bits_last = 0;
  reg  io_ddrReady = 1;
  reg  io_bootEnable = 0;
  reg [30:0] io_sources = 0;
  reg  io_uartRx = 1;
  wire  io_uartTx;
  reg [7:0] io_gmiiRxData = 0;
  reg  io_gmiiRxValid = 0;
  reg  io_gmiiRxError = 0;
  wire [7:0] io_gmiiTxData;
  wire  io_gmiiTxEnable;
  wire  io_gmiiTxError;
  reg  io_linkUp = 1;
  wire  io_mdc;
  wire  io_mdioIn;
  reg [4:0] io_triSpeedRgmii_rxRise = 0;
  reg [4:0] io_triSpeedRgmii_rxFall = 0;
  wire [4:0] io_triSpeedRgmii_txRise;
  wire [4:0] io_triSpeedRgmii_txFall;
  wire  io_triSpeedRgmii_txClockRise;
  wire  io_triSpeedRgmii_txClockFall;
  wire [1:0] io_triSpeedRgmii_requestedSpeed;
  wire [1:0] io_triSpeedRgmii_appliedSpeed;
  wire  io_triSpeedRgmii_pending;
  wire  io_triSpeedRgmii_linkUp;
  wire  io_triSpeedRgmii_txIdle;
  wire  io_triSpeedRgmii_rxDrained;
  wire  io_mdioOut;
  wire  io_mdioOe;
  wire  io_jtagDmi_request_ready;
  reg  io_jtagDmi_request_valid = 0;
  reg [1:0] io_jtagDmi_request_bits_op = 0;
  reg [6:0] io_jtagDmi_request_bits_address = 0;
  reg [31:0] io_jtagDmi_request_bits_data = 0;
  reg  io_jtagDmi_response_ready = 1;
  wire  io_jtagDmi_response_valid;
  wire [1:0] io_jtagDmi_response_bits_status;
  wire [31:0] io_jtagDmi_response_bits_data;
  reg  io_jtagLinkUp = 1;
  wire  io_maintenance_ready;
  reg  io_maintenance_valid = 0;
  reg [7:0] io_maintenance_bits_epoch = 0;
  reg  io_maintenance_bits_invalidateInstructions = 0;
  reg  io_maintenance_bits_invalidateTranslations = 0;
  wire  io_maintenanceStatus_valid;
  wire [7:0] io_maintenanceStatus_bits_epoch;
  wire  io_maintenanceStatus_bits_privateOwnersDrained;
  wire  io_maintenanceStatus_bits_dirtyWritebackCompleted;
  wire  io_maintenanceStatus_bits_fetchQuiescent;
  wire  io_maintenanceStatus_bits_invalidationsCompleted;
  wire  io_maintenanceStatus_bits_holdUntilResume;
  wire  io_retire_0_valid;
  wire [63:0] io_retire_0_bits_pc;
  wire [31:0] io_retire_0_bits_instruction;
  wire [63:0] io_retire_0_bits_nextPc;
  wire [4:0] io_retire_0_bits_rd;
  wire  io_retire_0_bits_writesRd;
  wire [63:0] io_retire_0_bits_data;
  wire  io_retire_1_valid;
  wire [63:0] io_retire_1_bits_pc;
  wire [31:0] io_retire_1_bits_instruction;
  wire [63:0] io_retire_1_bits_nextPc;
  wire [4:0] io_retire_1_bits_rd;
  wire  io_retire_1_bits_writesRd;
  wire [63:0] io_retire_1_bits_data;
  wire  io_trap_valid;
  wire [63:0] io_trap_bits_pc;
  wire [63:0] io_trap_bits_cause;
  wire [63:0] io_cpuCycles;
  wire [63:0] io_instructions;
  wire [63:0] io_fabricCycles;
  wire [63:0] io_timeSnapshot;
  wire  io_cpuLinkReady;
  wire  io_fabricLinkReady;
  wire  io_cpuTransportEmpty;
  wire  io_fabricTransportEmpty;
  wire  io_maintenancePending;
  wire  io_homeDrained;
  reg sourceClock250=0;
  always #2 sourceClock250=~sourceClock250;
  initial begin #0; forever #10 alwaysOnClock=~alwaysOnClock; end
  initial begin #0.25; forever #2 ddrClock=~ddrClock; end
  initial begin #0.5; forever #2 timebaseClock=~timebaseClock; end
  initial begin #0.75; forever #2 debugClock=~debugClock; end
  initial begin #1.0; forever #10 rawUartClock=~rawUartClock; end
  initial begin #0; forever #4 rawTxClock=~rawTxClock; end
  initial begin #1.25; forever #4 rawRxClock=~rawRxClock; end
  CommonDynamicRoundtripFixture dut (
    .rateBackend_0_present(rateBackend_0_present),
    .rateBackend_0_gateClosed(rateBackend_0_gateClosed),
    .rateBackend_0_gateOpen(rateBackend_0_gateOpen),
    .rateBackend_0_locked(rateBackend_0_locked),
    .rateBackend_0_resumed(rateBackend_0_resumed),
    .rateBackend_0_fatal(rateBackend_0_fatal),
    .rateBackend_0_quiesce(rateBackend_0_quiesce),
    .rateBackend_0_isolate(rateBackend_0_isolate),
    .rateBackend_0_clockEnable(rateBackend_0_clockEnable),
    .rateBackend_0_program_ready(rateBackend_0_program_ready),
    .rateBackend_0_program_valid(rateBackend_0_program_valid),
    .rateBackend_0_program_bits_hz(rateBackend_0_program_bits_hz),
    .rateBackend_0_program_bits_parameters(rateBackend_0_program_bits_parameters),
    .rateBackend_0_program_bits_token(rateBackend_0_program_bits_token),
    .rateBackend_0_program_bits_fallback(rateBackend_0_program_bits_fallback),
    .rateBackend_0_result_ready(rateBackend_0_result_ready),
    .rateBackend_0_result_valid(rateBackend_0_result_valid),
    .rateBackend_0_result_bits_hz(rateBackend_0_result_bits_hz),
    .rateBackend_0_result_bits_token(rateBackend_0_result_bits_token),
    .rateBackend_0_result_bits_error(rateBackend_0_result_bits_error),
    .rateBackend_1_present(rateBackend_1_present),
    .rateBackend_1_gateClosed(rateBackend_1_gateClosed),
    .rateBackend_1_gateOpen(rateBackend_1_gateOpen),
    .rateBackend_1_locked(rateBackend_1_locked),
    .rateBackend_1_resumed(rateBackend_1_resumed),
    .rateBackend_1_fatal(rateBackend_1_fatal),
    .rateBackend_1_quiesce(rateBackend_1_quiesce),
    .rateBackend_1_isolate(rateBackend_1_isolate),
    .rateBackend_1_clockEnable(rateBackend_1_clockEnable),
    .rateBackend_1_program_ready(rateBackend_1_program_ready),
    .rateBackend_1_program_valid(rateBackend_1_program_valid),
    .rateBackend_1_program_bits_hz(rateBackend_1_program_bits_hz),
    .rateBackend_1_program_bits_parameters(rateBackend_1_program_bits_parameters),
    .rateBackend_1_program_bits_token(rateBackend_1_program_bits_token),
    .rateBackend_1_program_bits_fallback(rateBackend_1_program_bits_fallback),
    .rateBackend_1_result_ready(rateBackend_1_result_ready),
    .rateBackend_1_result_valid(rateBackend_1_result_valid),
    .rateBackend_1_result_bits_hz(rateBackend_1_result_bits_hz),
    .rateBackend_1_result_bits_token(rateBackend_1_result_bits_token),
    .rateBackend_1_result_bits_error(rateBackend_1_result_bits_error),
    .cpuClock(cpuClock),
    .fabricClock(fabricClock),
    .alwaysOnClock(alwaysOnClock),
    .ddrClock(ddrClock),
    .timebaseClock(timebaseClock),
    .debugClock(debugClock),
    .rawUartClock(rawUartClock),
    .rawTxClock(rawTxClock),
    .rawRxClock(rawRxClock),
    .commonColdReset(commonColdReset),
    .io_ddrAxi_aw_ready(io_ddrAxi_aw_ready),
    .io_ddrAxi_aw_valid(io_ddrAxi_aw_valid),
    .io_ddrAxi_aw_bits_id(io_ddrAxi_aw_bits_id),
    .io_ddrAxi_aw_bits_addr(io_ddrAxi_aw_bits_addr),
    .io_ddrAxi_aw_bits_len(io_ddrAxi_aw_bits_len),
    .io_ddrAxi_aw_bits_size(io_ddrAxi_aw_bits_size),
    .io_ddrAxi_aw_bits_burst(io_ddrAxi_aw_bits_burst),
    .io_ddrAxi_aw_bits_lock(io_ddrAxi_aw_bits_lock),
    .io_ddrAxi_aw_bits_cache(io_ddrAxi_aw_bits_cache),
    .io_ddrAxi_aw_bits_prot(io_ddrAxi_aw_bits_prot),
    .io_ddrAxi_aw_bits_qos(io_ddrAxi_aw_bits_qos),
    .io_ddrAxi_w_ready(io_ddrAxi_w_ready),
    .io_ddrAxi_w_valid(io_ddrAxi_w_valid),
    .io_ddrAxi_w_bits_data(io_ddrAxi_w_bits_data),
    .io_ddrAxi_w_bits_strb(io_ddrAxi_w_bits_strb),
    .io_ddrAxi_w_bits_last(io_ddrAxi_w_bits_last),
    .io_ddrAxi_b_ready(io_ddrAxi_b_ready),
    .io_ddrAxi_b_valid(io_ddrAxi_b_valid),
    .io_ddrAxi_b_bits_id(io_ddrAxi_b_bits_id),
    .io_ddrAxi_b_bits_resp(io_ddrAxi_b_bits_resp),
    .io_ddrAxi_ar_ready(io_ddrAxi_ar_ready),
    .io_ddrAxi_ar_valid(io_ddrAxi_ar_valid),
    .io_ddrAxi_ar_bits_id(io_ddrAxi_ar_bits_id),
    .io_ddrAxi_ar_bits_addr(io_ddrAxi_ar_bits_addr),
    .io_ddrAxi_ar_bits_len(io_ddrAxi_ar_bits_len),
    .io_ddrAxi_ar_bits_size(io_ddrAxi_ar_bits_size),
    .io_ddrAxi_ar_bits_burst(io_ddrAxi_ar_bits_burst),
    .io_ddrAxi_ar_bits_lock(io_ddrAxi_ar_bits_lock),
    .io_ddrAxi_ar_bits_cache(io_ddrAxi_ar_bits_cache),
    .io_ddrAxi_ar_bits_prot(io_ddrAxi_ar_bits_prot),
    .io_ddrAxi_ar_bits_qos(io_ddrAxi_ar_bits_qos),
    .io_ddrAxi_r_ready(io_ddrAxi_r_ready),
    .io_ddrAxi_r_valid(io_ddrAxi_r_valid),
    .io_ddrAxi_r_bits_id(io_ddrAxi_r_bits_id),
    .io_ddrAxi_r_bits_data(io_ddrAxi_r_bits_data),
    .io_ddrAxi_r_bits_resp(io_ddrAxi_r_bits_resp),
    .io_ddrAxi_r_bits_last(io_ddrAxi_r_bits_last),
    .io_ddrReady(io_ddrReady),
    .io_bootEnable(io_bootEnable),
    .io_sources(io_sources),
    .io_uartRx(io_uartRx),
    .io_uartTx(io_uartTx),
    .io_gmiiRxData(io_gmiiRxData),
    .io_gmiiRxValid(io_gmiiRxValid),
    .io_gmiiRxError(io_gmiiRxError),
    .io_gmiiTxData(io_gmiiTxData),
    .io_gmiiTxEnable(io_gmiiTxEnable),
    .io_gmiiTxError(io_gmiiTxError),
    .io_linkUp(io_linkUp),
    .io_mdc(io_mdc),
    .io_mdioIn(io_mdioIn),
    .io_triSpeedRgmii_rxRise(io_triSpeedRgmii_rxRise),
    .io_triSpeedRgmii_rxFall(io_triSpeedRgmii_rxFall),
    .io_triSpeedRgmii_txRise(io_triSpeedRgmii_txRise),
    .io_triSpeedRgmii_txFall(io_triSpeedRgmii_txFall),
    .io_triSpeedRgmii_txClockRise(io_triSpeedRgmii_txClockRise),
    .io_triSpeedRgmii_txClockFall(io_triSpeedRgmii_txClockFall),
    .io_triSpeedRgmii_requestedSpeed(io_triSpeedRgmii_requestedSpeed),
    .io_triSpeedRgmii_appliedSpeed(io_triSpeedRgmii_appliedSpeed),
    .io_triSpeedRgmii_pending(io_triSpeedRgmii_pending),
    .io_triSpeedRgmii_linkUp(io_triSpeedRgmii_linkUp),
    .io_triSpeedRgmii_txIdle(io_triSpeedRgmii_txIdle),
    .io_triSpeedRgmii_rxDrained(io_triSpeedRgmii_rxDrained),
    .io_mdioOut(io_mdioOut),
    .io_mdioOe(io_mdioOe),
    .io_jtagDmi_request_ready(io_jtagDmi_request_ready),
    .io_jtagDmi_request_valid(io_jtagDmi_request_valid),
    .io_jtagDmi_request_bits_op(io_jtagDmi_request_bits_op),
    .io_jtagDmi_request_bits_address(io_jtagDmi_request_bits_address),
    .io_jtagDmi_request_bits_data(io_jtagDmi_request_bits_data),
    .io_jtagDmi_response_ready(io_jtagDmi_response_ready),
    .io_jtagDmi_response_valid(io_jtagDmi_response_valid),
    .io_jtagDmi_response_bits_status(io_jtagDmi_response_bits_status),
    .io_jtagDmi_response_bits_data(io_jtagDmi_response_bits_data),
    .io_jtagLinkUp(io_jtagLinkUp),
    .io_maintenance_ready(io_maintenance_ready),
    .io_maintenance_valid(io_maintenance_valid),
    .io_maintenance_bits_epoch(io_maintenance_bits_epoch),
    .io_maintenance_bits_invalidateInstructions(io_maintenance_bits_invalidateInstructions),
    .io_maintenance_bits_invalidateTranslations(io_maintenance_bits_invalidateTranslations),
    .io_maintenanceStatus_valid(io_maintenanceStatus_valid),
    .io_maintenanceStatus_bits_epoch(io_maintenanceStatus_bits_epoch),
    .io_maintenanceStatus_bits_privateOwnersDrained(io_maintenanceStatus_bits_privateOwnersDrained),
    .io_maintenanceStatus_bits_dirtyWritebackCompleted(io_maintenanceStatus_bits_dirtyWritebackCompleted),
    .io_maintenanceStatus_bits_fetchQuiescent(io_maintenanceStatus_bits_fetchQuiescent),
    .io_maintenanceStatus_bits_invalidationsCompleted(io_maintenanceStatus_bits_invalidationsCompleted),
    .io_maintenanceStatus_bits_holdUntilResume(io_maintenanceStatus_bits_holdUntilResume),
    .io_retire_0_valid(io_retire_0_valid),
    .io_retire_0_bits_pc(io_retire_0_bits_pc),
    .io_retire_0_bits_instruction(io_retire_0_bits_instruction),
    .io_retire_0_bits_nextPc(io_retire_0_bits_nextPc),
    .io_retire_0_bits_rd(io_retire_0_bits_rd),
    .io_retire_0_bits_writesRd(io_retire_0_bits_writesRd),
    .io_retire_0_bits_data(io_retire_0_bits_data),
    .io_retire_1_valid(io_retire_1_valid),
    .io_retire_1_bits_pc(io_retire_1_bits_pc),
    .io_retire_1_bits_instruction(io_retire_1_bits_instruction),
    .io_retire_1_bits_nextPc(io_retire_1_bits_nextPc),
    .io_retire_1_bits_rd(io_retire_1_bits_rd),
    .io_retire_1_bits_writesRd(io_retire_1_bits_writesRd),
    .io_retire_1_bits_data(io_retire_1_bits_data),
    .io_trap_valid(io_trap_valid),
    .io_trap_bits_pc(io_trap_bits_pc),
    .io_trap_bits_cause(io_trap_bits_cause),
    .io_cpuCycles(io_cpuCycles),
    .io_instructions(io_instructions),
    .io_fabricCycles(io_fabricCycles),
    .io_timeSnapshot(io_timeSnapshot),
    .io_cpuLinkReady(io_cpuLinkReady),
    .io_fabricLinkReady(io_fabricLinkReady),
    .io_cpuTransportEmpty(io_cpuTransportEmpty),
    .io_fabricTransportEmpty(io_fabricTransportEmpty),
    .io_maintenancePending(io_maintenancePending),
    .io_homeDrained(io_homeDrained)
  );
  native_dynamic_clock_domain backend_0 (
    .aon_clock(alwaysOnClock),
    .common_cold_reset(commonColdReset),
    .source_clock250(sourceClock250),
    .managed_clock(cpuClock),
    .clock_enable(rateBackend_0_clockEnable),
    .isolate(rateBackend_0_isolate),
    .program_valid(rateBackend_0_program_valid),
    .program_ready(rateBackend_0_program_ready),
    .program_hz(rateBackend_0_program_bits_hz),
    .program_parameters(rateBackend_0_program_bits_parameters),
    .program_token(rateBackend_0_program_bits_token),
    .program_fallback(rateBackend_0_program_bits_fallback),
    .result_valid(rateBackend_0_result_valid),
    .result_ready(rateBackend_0_result_ready),
    .result_hz(rateBackend_0_result_bits_hz),
    .result_token(rateBackend_0_result_bits_token),
    .result_error(rateBackend_0_result_bits_error),
    .present(rateBackend_0_present),
    .gate_closed(rateBackend_0_gateClosed),
    .gate_open(rateBackend_0_gateOpen),
    .locked(rateBackend_0_locked),
    .resumed(rateBackend_0_resumed),
    .fatal(rateBackend_0_fatal)
  );
  dynamic_roundtrip_lane_checker #(.LANE(0)) check_0 (
    .aon_clock(alwaysOnClock),
    .managed_clock(cpuClock),
    .clock_enable(rateBackend_0_clockEnable),
    .isolate(rateBackend_0_isolate),
    .program_valid(rateBackend_0_program_valid),
    .program_ready(rateBackend_0_program_ready),
    .program_hz(rateBackend_0_program_bits_hz),
    .program_parameters(rateBackend_0_program_bits_parameters),
    .program_token(rateBackend_0_program_bits_token),
    .program_fallback(rateBackend_0_program_bits_fallback),
    .result_valid(rateBackend_0_result_valid),
    .result_ready(rateBackend_0_result_ready),
    .result_hz(rateBackend_0_result_bits_hz),
    .result_token(rateBackend_0_result_bits_token),
    .result_error(rateBackend_0_result_bits_error),
    .gate_closed(rateBackend_0_gateClosed),
    .gate_open(rateBackend_0_gateOpen),
    .locked(rateBackend_0_locked),
    .resumed(rateBackend_0_resumed),
    .fatal(rateBackend_0_fatal),
    .cold_reset(commonColdReset),
    .request_valid(dut.runtime.io_requests_0_valid),
    .request_ready(dut.runtime.io_requests_0_ready),
    .request_token(dut.runtime.io_requests_0_bits),
    .held_valid(dut.runtime.io_held_0_valid),
    .held_token(dut.runtime.io_held_0_bits_token),
    .held_epoch(dut.runtime.io_held_0_bits_epoch),
    .resume_valid(dut.runtime.io_resume_0_valid),
    .resume_ready(dut.runtime.io_resume_0_ready),
    .resume_token(dut.runtime.io_resume_0_bits_token),
    .resume_epoch(dut.runtime.io_resume_0_bits_epoch),
    .terminal_valid(dut.runtime.io_result_0_valid),
    .terminal_ready(dut.runtime.io_result_0_ready),
    .terminal_token(dut.runtime.io_result_0_bits_token),
    .terminal_epoch(dut.runtime.io_result_0_bits_epoch),
    .terminal_canceled(dut.runtime.io_result_0_bits_canceled),
    .terminal_timed_out(dut.runtime.io_result_0_bits_timedOut),
    .retired_valid(dut.adapter.io_clients_0_retired_valid),
    .retired_ready(dut.adapter.io_clients_0_retired_ready),
    .retired_token(dut.adapter.io_clients_0_retired_bits),
    .runtime_busy(dut.runtime.io_busy),
    .cmu_completed(dut.peripherals.rateCmu.rates.controls_0.io_completed),
    .cmu_errors(dut.peripherals.rateCmu.rates.controls_0.io_errors),
    .cmu_actual_hz(dut.peripherals.rateCmu.rates.controls_0.io_actualHz),
    .cmu_actual_valid(dut.peripherals.rateCmu.rates.controls_0.io_actualValid),
    .cmu_success(dut.peripherals.rateCmu.rates.controls_0.io_lastSuccess)
  );
  native_dynamic_clock_domain #(.MAX_PROGRAM_HZ(250000000)) backend_1 (
    .aon_clock(alwaysOnClock),
    .common_cold_reset(commonColdReset),
    .source_clock250(sourceClock250),
    .managed_clock(fabricClock),
    .clock_enable(rateBackend_1_clockEnable),
    .isolate(rateBackend_1_isolate),
    .program_valid(rateBackend_1_program_valid),
    .program_ready(rateBackend_1_program_ready),
    .program_hz(rateBackend_1_program_bits_hz),
    .program_parameters(rateBackend_1_program_bits_parameters),
    .program_token(rateBackend_1_program_bits_token),
    .program_fallback(rateBackend_1_program_bits_fallback),
    .result_valid(rateBackend_1_result_valid),
    .result_ready(rateBackend_1_result_ready),
    .result_hz(rateBackend_1_result_bits_hz),
    .result_token(rateBackend_1_result_bits_token),
    .result_error(rateBackend_1_result_bits_error),
    .present(rateBackend_1_present),
    .gate_closed(rateBackend_1_gateClosed),
    .gate_open(rateBackend_1_gateOpen),
    .locked(rateBackend_1_locked),
    .resumed(rateBackend_1_resumed),
    .fatal(rateBackend_1_fatal)
  );
  dynamic_roundtrip_lane_checker #(.LANE(1)) check_1 (
    .aon_clock(alwaysOnClock),
    .managed_clock(fabricClock),
    .clock_enable(rateBackend_1_clockEnable),
    .isolate(rateBackend_1_isolate),
    .program_valid(rateBackend_1_program_valid),
    .program_ready(rateBackend_1_program_ready),
    .program_hz(rateBackend_1_program_bits_hz),
    .program_parameters(rateBackend_1_program_bits_parameters),
    .program_token(rateBackend_1_program_bits_token),
    .program_fallback(rateBackend_1_program_bits_fallback),
    .result_valid(rateBackend_1_result_valid),
    .result_ready(rateBackend_1_result_ready),
    .result_hz(rateBackend_1_result_bits_hz),
    .result_token(rateBackend_1_result_bits_token),
    .result_error(rateBackend_1_result_bits_error),
    .gate_closed(rateBackend_1_gateClosed),
    .gate_open(rateBackend_1_gateOpen),
    .locked(rateBackend_1_locked),
    .resumed(rateBackend_1_resumed),
    .fatal(rateBackend_1_fatal),
    .cold_reset(commonColdReset),
    .request_valid(dut.runtime.io_requests_1_valid),
    .request_ready(dut.runtime.io_requests_1_ready),
    .request_token(dut.runtime.io_requests_1_bits),
    .held_valid(dut.runtime.io_held_1_valid),
    .held_token(dut.runtime.io_held_1_bits_token),
    .held_epoch(dut.runtime.io_held_1_bits_epoch),
    .resume_valid(dut.runtime.io_resume_1_valid),
    .resume_ready(dut.runtime.io_resume_1_ready),
    .resume_token(dut.runtime.io_resume_1_bits_token),
    .resume_epoch(dut.runtime.io_resume_1_bits_epoch),
    .terminal_valid(dut.runtime.io_result_1_valid),
    .terminal_ready(dut.runtime.io_result_1_ready),
    .terminal_token(dut.runtime.io_result_1_bits_token),
    .terminal_epoch(dut.runtime.io_result_1_bits_epoch),
    .terminal_canceled(dut.runtime.io_result_1_bits_canceled),
    .terminal_timed_out(dut.runtime.io_result_1_bits_timedOut),
    .retired_valid(dut.adapter.io_clients_1_retired_valid),
    .retired_ready(dut.adapter.io_clients_1_retired_ready),
    .retired_token(dut.adapter.io_clients_1_retired_bits),
    .runtime_busy(dut.runtime.io_busy),
    .cmu_completed(dut.peripherals.rateCmu.rates.controls_1.io_completed),
    .cmu_errors(dut.peripherals.rateCmu.rates.controls_1.io_errors),
    .cmu_actual_hz(dut.peripherals.rateCmu.rates.controls_1.io_actualHz),
    .cmu_actual_valid(dut.peripherals.rateCmu.rates.controls_1.io_actualValid),
    .cmu_success(dut.peripherals.rateCmu.rates.controls_1.io_lastSuccess)
  );
  wire phyConfigured, phyBusy;
  wire [31:0] phyTransactions, phyReads, phyWrites, phyStatusReads, phyBmsrReads, phyNoAcks;
  rtl8211f_pin_model phy (
    .clk(rawTxClock), .reset(commonColdReset), .mdc(io_mdc),
    .mdio_out(io_mdioOut), .mdio_oe(io_mdioOe), .mdio_in(io_mdioIn),
    .wire_link(1'b1), .wire_speed(2'd2), .full_duplex(1'b1), .an_complete(1'b1),
    .remote_fault(1'b0), .inject_no_ack(1'b0), .in_transaction(phyBusy),
    .page(), .transaction_count(phyTransactions), .read_count(phyReads),
    .write_count(phyWrites), .status_count(phyStatusReads), .bmsr_count(phyBmsrReads),
    .no_ack_count(phyNoAcks), .last_phy(), .last_register(), .last_write(), .last_data(),
    .configuration_complete(phyConfigured)
  );
  wire mediaReady = dut.peripherals.gmac.linkUp && !dut.peripherals.gmac.mediaPending;
  wire [31:0] completed0=dut.peripherals.rateCmu.rates.controls_0.io_completed;
  wire [31:0] completed1=dut.peripherals.rateCmu.rates.controls_1.io_completed;
  reg [63:0] done_pc=0, fail_pc=0, last_retired_pc=0;
  integer cycles=0, retired_instructions=0, stagedWrites=0, mmioWrites=0, mmioRequests=0, mmioReplies=0;
  integer rawTxEdges=0, rawRxEdges=0, fixed250Edges=0, bootCycle=0;
  reg finished=0;
  reg boot_smoke=0;
  reg telemetry_smoke=0;
  reg [31:0] rom0_first=0,rom1_first=0;
  initial begin
    boot_smoke=$test$plusargs("boot_smoke");
    telemetry_smoke=$test$plusargs("telemetry_smoke");
    if(!$value$plusargs("rom0_first=%h",rom0_first) || !$value$plusargs("rom1_first=%h",rom1_first))
      $fatal(1,"ROUNDTRIP_REQUIRED_ROM_WORDS");
    #0.001;
    if(dut.fabric.rom.banks_0_ext.Memory[0]!==rom0_first || dut.fabric.rom.banks_1_ext.Memory[0]!==rom1_first)
      $fatal(1,"ROUNDTRIP_ROM_INITIALIZATION_ORACLE bank0=%h bank1=%h",dut.fabric.rom.banks_0_ext.Memory[0],dut.fabric.rom.banks_1_ext.Memory[0]);
    $display("ROUNDTRIP_ROM_INITIALIZED bank0=%h bank1=%h",rom0_first,rom1_first);
  end
  initial begin
    if(!$value$plusargs("done_pc=%h",done_pc) || !$value$plusargs("fail_pc=%h",fail_pc))
      $fatal(1,"ROUNDTRIP_REQUIRED_PLUSARGS done_pc and fail_pc");
    $display("ROUNDTRIP_MODEL native SV behavioral primitives; NOT UNISIM, mapped timing, or board qualification");
    $display("ROUNDTRIP_CLOCKS AON=50MHz rawMAC/RXC=125MHz DDR/timer/debug/reference=250MHz CPU/fabric=real managed50->100->50");
    // Explicit assertion edge resets retained owners before managed clocks exist.
    #1; commonColdReset=1;
    repeat(20) @(negedge alwaysOnClock);
    commonColdReset=0;
    // Cold-start boot hold only. All real managed and fixed clocks keep running.
    if(boot_smoke || telemetry_smoke) repeat(100) @(negedge alwaysOnClock);
    else wait(phyConfigured && mediaReady);
    @(negedge alwaysOnClock);
    io_bootEnable=1; bootCycle=cycles;
    $display("ROUNDTRIP_BOOT time_ns=%0t phy_transactions=%0d status_reads=%0d rawMAC_edges=%0d",$time,phyTransactions,phyStatusReads,rawTxEdges);
  end
  always @(posedge rawTxClock) if(!commonColdReset) rawTxEdges=rawTxEdges+1;
  always @(posedge rawRxClock) if(!commonColdReset) rawRxEdges=rawRxEdges+1;
  always @(posedge sourceClock250) if(!commonColdReset) fixed250Edges=fixed250Edges+1;
  // Independent, bounded read-only AXI memory for six unique guest cache lines.
  // It responds only to actual accepted AR owners, preserves ID/len/last, and
  // holds every R beat under backpressure. No monitor or CPU event is injected.
  integer ddrReads=0, ddrBeats=0, ddrBeat=0, ddrWait=0;
  reg ddrReadBusy=0;
  reg [3:0] ddrReadId=0;
  reg [7:0] ddrReadLen=0;
  always @(posedge ddrClock) begin
    if(commonColdReset) begin
      ddrReadBusy<=0; io_ddrAxi_ar_ready<=1; io_ddrAxi_r_valid<=0;
      ddrReads=0; ddrBeats=0; ddrWait<=0;
    end else begin
      if(io_ddrAxi_aw_valid || io_ddrAxi_w_valid)
        $fatal(1,"ROUNDTRIP_UNEXPECTED_DDR_WRITE");
      if(io_ddrAxi_ar_valid && io_ddrAxi_ar_ready) begin
        if(ddrReadBusy || ddrReads>=6 || io_ddrAxi_ar_bits_addr!==ddrReads*64 ||
           io_ddrAxi_ar_bits_len!==7 || io_ddrAxi_ar_bits_size!==3 || io_ddrAxi_ar_bits_burst!==1)
          $fatal(1,"ROUNDTRIP_DDR_READ_OWNER address=%h count=%0d len=%0d",io_ddrAxi_ar_bits_addr,ddrReads,io_ddrAxi_ar_bits_len);
        ddrReadBusy<=1; io_ddrAxi_ar_ready<=0;
        ddrReadId<=io_ddrAxi_ar_bits_id; ddrReadLen<=io_ddrAxi_ar_bits_len;
        ddrBeat<=0; ddrWait<=9; ddrReads=ddrReads+1;
      end
      if(ddrReadBusy && !io_ddrAxi_r_valid) begin
        if(ddrWait>0) ddrWait<=ddrWait-1;
        else begin
          io_ddrAxi_r_valid<=1; io_ddrAxi_r_bits_id<=ddrReadId;
          io_ddrAxi_r_bits_data<=64'h13579bdf2468ace0;
          io_ddrAxi_r_bits_resp<=0; io_ddrAxi_r_bits_last<=(ddrBeat==ddrReadLen);
        end
      end
      if(io_ddrAxi_r_valid && io_ddrAxi_r_ready) begin
        ddrBeats=ddrBeats+1; io_ddrAxi_r_valid<=0;
        if(ddrBeat==ddrReadLen) begin ddrReadBusy<=0; io_ddrAxi_ar_ready<=1; end
        else begin ddrBeat<=ddrBeat+1; ddrWait<=2; end
      end
    end
  end
  integer telemetryChecks=0;
  always @(posedge fabricClock) if(!commonColdReset) begin
    if(dut.peripherals.rateCmu.registers_request_valid && dut.peripherals.rateCmu.registers_request_ready) begin
      mmioRequests=mmioRequests+1;
      if(dut.peripherals.rateCmu.registers_request_bits_write) begin
        if(dut.peripherals.rateCmu.registers_request_bits_address[6:0]==7'h30) begin
          if(stagedWrites!=mmioWrites || stagedWrites>=4 ||
             dut.peripherals.rateCmu.registers_request_bits_address!==((stagedWrites<2)?64'h10080830:64'h100808b0) ||
             dut.peripherals.rateCmu.registers_request_bits_data!==((stagedWrites%2==0)?64'h0a280a:64'h14280a))
            $fatal(1,"ROUNDTRIP_STAGED_PARAMETER_ORACLE");
          stagedWrites=stagedWrites+1;
        end else begin
        if(stagedWrites!=mmioWrites+1 || mmioWrites>=4 || dut.peripherals.rateCmu.registers_request_bits_address!==((mmioWrites<2)?64'h10080800:64'h10080880) ||
           dut.peripherals.rateCmu.registers_request_bits_data!==((mmioWrites%2==0)?64'd100000000:64'd50000000) ||
           dut.peripherals.rateCmu.registers_request_bits_size!==3 || dut.peripherals.rateCmu.registers_request_bits_byteEnable!==8'hff)
          $fatal(1,"ROUNDTRIP_GUEST_MMIO_WRITE_ORACLE index=%0d address=%h data=%h",mmioWrites,dut.peripherals.rateCmu.registers_request_bits_address,dut.peripherals.rateCmu.registers_request_bits_data);
        mmioWrites=mmioWrites+1;
        end
      end
    end
    if(dut.peripherals.rateCmu.registers_response_valid && dut.peripherals.rateCmu.registers_response_ready) begin
      if(mmioReplies>=mmioRequests || dut.peripherals.rateCmu.registers_response_bits_error)
        $fatal(1,"ROUNDTRIP_GUEST_MMIO_REPLY_ORACLE");
      mmioReplies=mmioReplies+1;
    end
  end
  always @(posedge alwaysOnClock) if(!commonColdReset) begin
    cycles=cycles+1;
    if(cycles < 20) $display("STARTUP_FAULT_TRACE cycle=%0d failed=%b observed=%b guard=%b close=%b debug=%b cleanup=%b receipt=%b safe=%b armed=%b",cycles,dut.failed,dut.observedFault,dut._peripherals_rateSafety_fault,dut._runtime_io_closeFault,dut._debugFaultSync_levelOut,dut._runtime_io_cleanupFault,dut._peripherals_rateSafety_receipt_valid,dut.fixedAonSafe,dut.armed);
    if(dut.failed || dut.runtime.io_cleanupFault || dut.runtime.io_closeFault)
      $fatal(1,"ROUNDTRIP_REAL_PLATFORM_FAULT failed=%b cleanup=%b close=%b",dut.failed,dut.runtime.io_cleanupFault,dut.runtime.io_closeFault);
    if(rateBackend_0_program_valid && rateBackend_0_program_ready && (completed1!==0 || completed0>1))
      $fatal(1,"ROUNDTRIP_CPU_SEQUENCE_ORDER");
    if(rateBackend_1_program_valid && rateBackend_1_program_ready && (completed0!==2 || completed1>1))
      $fatal(1,"ROUNDTRIP_FABRIC_SEQUENCE_ORDER");
    if(io_bootEnable && retired_instructions==0 && cycles-bootCycle>=1000)
      $fatal(1,"ROUNDTRIP_FIRST_RETIRE_DEADLINE cpuReset=%b cpuLink=%b fabricLink=%b cpuCycles=%h",dut._cpuRelease_resetOut,io_cpuLinkReady,io_fabricLinkReady,io_cpuCycles);
    if(cycles%25000==0)
      $display("ROUNDTRIP_PROGRESS time_ns=%0t boot=%b phy=%0d media=%b retired=%0d last_pc=%h cpu_state=%0d fabric_state=%0d cpu_done=%0d fabric_done=%0d epoch_busy=%b",$time,io_bootEnable,phyTransactions,mediaReady,retired_instructions,last_retired_pc,dut.peripherals.rateCmu.rates.controls_0.io_state,dut.peripherals.rateCmu.rates.controls_1.io_state,completed0,completed1,dut.runtime.io_busy);
    if(cycles%25000==0 && io_bootEnable)
      $display("ROUNDTRIP_TELEMETRY_DIAGNOSTIC seq=%0d valid=%b retire=%0d scalar=%0d data_A=%0d refill_lines=%0d DDR_AR=%0d DDR_R=%0d",dut.monitor.bank.sequence_0,dut.monitor.bank.valid_0,dut.monitor.bank.snapshot_0_1,dut.monitor.bank.snapshot_0_2,dut.monitor.bank.snapshot_0_3,dut.monitor.bank.snapshot_0_5,dut.monitor.bank.snapshot_1_1,dut.monitor.bank.snapshot_1_5);
    if(cycles%5000==0 && dut.runtime.io_busy)
      $display("ROUNDTRIP_DRAIN_PROGRESS time_ns=%0t cpu_held=%b fabric_held=%b fabric_idle=%b control_idle=%b fixed_idle=%b close_proof=%h mac_park_request=%b mac_mdio_drained=%b mac_phy_parked=%b phy_state=%0d phy_operation=%0d",$time,dut.runtime.io_cpuHeld_valid,dut.runtime.io_fabricHeld_valid,dut.runtime.io_fabricAllObligationsIdle,dut.runtime.io_fabricControlOwnersIdle,dut.runtime.io_fabricFixedOwnersIdle,dut.runtime.io_closeProof,dut.peripherals.gmac.controlPark_request,dut.peripherals.gmac.controlPark_mdioDrained,dut.peripherals.gmac.controlPark_phyParked,dut.peripherals.gmac.phy.state,dut.peripherals.gmac.phy.operation);
  end
  task automatic observe_retire(input [63:0] pc);
    begin
      retired_instructions=retired_instructions+1; last_retired_pc=pc;
      if(boot_smoke) begin
        if(pc!==64'h80000000 || io_retire_0_bits_instruction!==rom0_first)
          $fatal(1,"BOOT_SMOKE_FIRST_INSTRUCTION_ORACLE pc=%h instruction=%h",pc,io_retire_0_bits_instruction);
        $display("BOOT_SMOKE_PASS first_pc=%h instruction=%h CPU_cycles=%0d cpuLink=%b fabricLink=%b no frequency qualification",pc,io_retire_0_bits_instruction,io_cpuCycles,io_cpuLinkReady,io_fabricLinkReady);
        $finish;
      end
      if(io_retire_0_bits_instruction===32'h5a100013) begin
        telemetryChecks=telemetryChecks+1;
        $display("ROUNDTRIP_GUEST_TELEMETRY_CHECK index=%0d actual_ddr_reads=%0d actual_ddr_beats=%0d",telemetryChecks,ddrReads,ddrBeats);
        if(telemetry_smoke) begin
          if(telemetryChecks!=1 || ddrReads!=1 || ddrBeats!=8 || mmioWrites!=0 ||
             check_0.programs!=0 || check_1.programs!=0)
            $fatal(1,"TELEMETRY_SMOKE_WRONG_SCOPE");
          $display("TELEMETRY_SMOKE_PASS ordinary_guest_MMIO=1 DDR_lines=1 DDR_beats=8 actual_refill_counter_positive=1 no_rate_transition=1 no_PHY_or_drain_qualification=1");
          $finish;
        end
      end
      if(pc===fail_pc) $fatal(1,"ROUNDTRIP_GUEST_FAIL_PC pc=%h",pc);
      if(pc===done_pc && !finished) begin
        finished=1;
        if(telemetryChecks!=6 || ddrReads!=6 || ddrBeats!=48 || ddrReadBusy ||
           completed0!==2 || completed1!==2 || mmioWrites!=4 || stagedWrites!=4 || mmioReplies!=mmioRequests ||
           check_0.programs!=2 || check_1.programs!=2 || check_0.results!=2 || check_1.results!=2 ||
           check_0.retirements!=2 || check_1.retirements!=2 || check_0.checked_periods<8 || check_1.checked_periods<8 ||
           !phyConfigured || phyNoAcks!=0 || !mediaReady || dut.runtime.io_busy ||
           dut.peripherals.rateCmu.rates.controls_0.io_actualHz!==32'd50000000 ||
           dut.peripherals.rateCmu.rates.controls_1.io_actualHz!==32'd50000000)
          $fatal(1,"ROUNDTRIP_INCOMPLETE_SUCCESS_LEDGER");
        $display("ROUNDTRIP_TELEMETRY_PASS snapshots=6 guest_MMIO=1 actual_DDR_reads=6 actual_DDR_beats=48 real_retire_cache_and_memory_events=1");
        $display("ROUNDTRIP_PASS CPU50->100->50 FABRIC50->100->50 programs=4 results=4 real_epoch_retirements=4 mmio_writes=%0d mmio_requests=%0d mmio_replies=%0d retired=%0d elapsed_ns=%0t rawMAC_edges=%0d RXC_edges=%0d fixed250_edges=%0d",mmioWrites,mmioRequests,mmioReplies,retired_instructions,$time,rawTxEdges,rawRxEdges,fixed250Edges);
        $finish;
      end
    end
  endtask
  always @(posedge cpuClock) if(!commonColdReset) begin
    if(!dut._cpuRelease_resetOut && (^{io_cpuCycles,io_trap_valid,io_retire_0_valid,dut.cpu.tile.core.io_instructionRequest_valid,dut.cpu.tile.core.io_instructionResponse_valid})===1'bx)
      $fatal(1,"ROUNDTRIP_UNKNOWN_CPU_CONTROL cycles=%h retire=%b fetch=%b response=%b",io_cpuCycles,io_retire_0_valid,dut.cpu.tile.core.io_instructionRequest_valid,dut.cpu.tile.core.io_instructionResponse_valid);
    if(!dut._cpuRelease_resetOut && dut.cpu.tile.core.io_instructionResponse_valid &&
       (^dut.cpu.tile.core.io_instructionResponse_bits_instruction)===1'bx)
      $fatal(1,"ROUNDTRIP_UNKNOWN_INSTRUCTION_REPLY");
    if(io_trap_valid) $fatal(1,"ROUNDTRIP_UNEXPECTED_TRAP pc=%h cause=%h",io_trap_bits_pc,io_trap_bits_cause);
    if(io_retire_0_valid) observe_retire(io_retire_0_bits_pc);
    if(io_retire_1_valid) observe_retire(io_retire_1_bits_pc);
  end
  initial begin
    // Observation budget only: real PHY startup plus four residual MDIO poll
    // groups exceeds5ms. DUT, guest, MDIO and protocol timeouts are unchanged.
    #6000000;
    $fatal(1,"ROUNDTRIP_SIMULATION_TIMEOUT 6ms boot=%b phy_transactions=%0d media_ready=%b cpu_done=%0d fabric_done=%0d last_pc=%h",io_bootEnable,phyTransactions,mediaReady,completed0,completed1,last_retired_pc);
  end

endmodule
`default_nettype wire
`timescale 1ns/1ps
// Independent test oracle. Inputs only: no force, drain ACK, or epoch shortcut.
module dynamic_roundtrip_lane_checker #(parameter integer LANE=0) (
  input wire aon_clock, cold_reset, managed_clock,
  input wire clock_enable, isolate, gate_closed, gate_open, locked, resumed, fatal,
  input wire program_valid, program_ready, program_fallback,
  input wire [31:0] program_hz, program_token,
  input wire [23:0] program_parameters,
  input wire result_valid, result_ready, result_error,
  input wire [31:0] result_hz, result_token,
  input wire request_valid, request_ready,
  input wire [31:0] request_token,
  input wire held_valid,
  input wire [31:0] held_token,
  input wire [7:0] held_epoch,
  input wire resume_valid, resume_ready,
  input wire [31:0] resume_token,
  input wire [7:0] resume_epoch,
  input wire terminal_valid, terminal_ready, terminal_canceled, terminal_timed_out,
  input wire [31:0] terminal_token,
  input wire [7:0] terminal_epoch,
  input wire retired_valid, retired_ready,
  input wire [31:0] retired_token,
  input wire runtime_busy,
  input wire [31:0] cmu_completed, cmu_errors, cmu_actual_hz,
  input wire cmu_actual_valid, cmu_success
);
  integer programs=0, results=0, requests=0, resumes=0, terminals=0, retirements=0;
  integer completions=0, managed_edges=0, checked_periods=0, close_windows=0;
  integer edges_after_program=0;
  reg [31:0] pending_hz=32'd50000000, pending_program_token=0, pending_lease_token=0;
  reg [7:0] pending_epoch=0, previous_epoch=0;
  reg program_pending=0, lease_pending=0, held_seen=0, closed_previous=0;
  realtime previous_edge=0.0, elapsed=0.0, expected_period=20.0;
  always @(negedge clock_enable or posedge cold_reset) previous_edge=0.0;
  always @(posedge managed_clock) if(!cold_reset) begin
    if(gate_closed === 1'b1) $fatal(1,"ROUNDTRIP_EDGE_WHILE_GATE_CLOSED lane=%0d",LANE);
    managed_edges=managed_edges+1;
    edges_after_program=edges_after_program+1;
    if(previous_edge!=0.0) begin
      elapsed=$realtime-previous_edge;
      expected_period=(pending_hz==32'd100000000) ? 10.0 : 20.0;
      if(elapsed<expected_period-0.001 || elapsed>expected_period+0.001)
        $fatal(1,"ROUNDTRIP_WRONG_MANAGED_PERIOD lane=%0d measured=%0.3f expected=%0.3f hz=%0d",LANE,elapsed,expected_period,pending_hz);
      checked_periods=checked_periods+1;
    end
    previous_edge=$realtime;
  end
  always @(posedge aon_clock) if(!cold_reset) begin
    if(fatal === 1'b1 || cmu_errors !== 32'b0)
      $fatal(1,"ROUNDTRIP_BACKEND_OR_CMU_FAULT lane=%0d fatal=%b errors=%h",LANE,fatal,cmu_errors);
    if(gate_closed && !closed_previous) close_windows=close_windows+1;
    closed_previous=gate_closed;
    if(request_valid && request_ready) begin
      if(lease_pending || requests>=2) $fatal(1,"ROUNDTRIP_DUPLICATE_EPOCH_REQUEST lane=%0d",LANE);
      pending_lease_token=request_token;
      requests=requests+1; lease_pending=1; held_seen=0;
      $display("ROUNDTRIP_EPOCH_REQUEST time_ns=%0t lane=%0d token=%0d",$time,LANE,request_token);
    end
    if(held_valid) begin
      if(!lease_pending || held_token!==pending_lease_token)
        $fatal(1,"ROUNDTRIP_UNOWNED_HELD lane=%0d",LANE);
      if(!held_seen) begin
        if(requests>1 && held_epoch===previous_epoch) $fatal(1,"ROUNDTRIP_REUSED_EPOCH lane=%0d",LANE);
        pending_epoch=held_epoch; previous_epoch=held_epoch; held_seen=1;
        $display("ROUNDTRIP_EPOCH_HELD time_ns=%0t lane=%0d token=%0d epoch=%0d",$time,LANE,held_token,held_epoch);
      end else if(held_epoch!==pending_epoch) $fatal(1,"ROUNDTRIP_HELD_EPOCH_CHANGED lane=%0d",LANE);
    end
    if(program_valid && program_ready) begin
      if(program_pending || programs>=2 || !lease_pending || !held_seen)
        $fatal(1,"ROUNDTRIP_UNOWNED_PROGRAM lane=%0d",LANE);
      if(!gate_closed || clock_enable || !isolate || program_fallback)
        $fatal(1,"ROUNDTRIP_PROGRAM_WITHOUT_NORMAL_CLOSED_ISOLATED_GATE lane=%0d",LANE);
      if(program_hz!==((programs==0)?32'd100000000:32'd50000000) ||
         program_parameters!==((programs==0)?24'h0a280a:24'h14280a))
        $fatal(1,"ROUNDTRIP_WRONG_PROGRAM_ORDER lane=%0d count=%0d hz=%0d",LANE,programs,program_hz);
      pending_hz=program_hz; pending_program_token=program_token;
      programs=programs+1; program_pending=1; edges_after_program=0; previous_edge=0.0;
      $display("ROUNDTRIP_PROGRAM time_ns=%0t lane=%0d hz=%0d token=%0d",$time,LANE,program_hz,program_token);
    end
    if(result_valid && result_ready) begin
      if(!program_pending || result_token!==pending_program_token || result_hz!==pending_hz || result_error)
        $fatal(1,"ROUNDTRIP_PROGRAM_RESULT_CONSERVATION lane=%0d hz=%0d token=%0d error=%b",LANE,result_hz,result_token,result_error);
      program_pending=0; results=results+1;
    end
    if(resume_valid && resume_ready) begin
      if(!lease_pending || !held_seen || resume_token!==pending_lease_token || resume_epoch!==pending_epoch ||
         results!=programs || programs!=requests || resumes>=requests || !resumed || !locked || !gate_open || edges_after_program<4)
        $fatal(1,"ROUNDTRIP_RESUME_BEFORE_REAL_TARGET_EDGES lane=%0d edges=%0d",LANE,edges_after_program);
      resumes=resumes+1;
    end
    if(terminal_valid && terminal_ready) begin
      if(!lease_pending || terminal_token!==pending_lease_token || terminal_epoch!==pending_epoch ||
         terminal_canceled || terminal_timed_out || resumes!=requests || terminals>=requests)
        $fatal(1,"ROUNDTRIP_EPOCH_TERMINAL_CONSERVATION lane=%0d",LANE);
      terminals=terminals+1;
    end
    if(retired_valid && retired_ready) begin
      if(!lease_pending || retired_token!==pending_lease_token || runtime_busy || terminals!=requests ||
         !resumed || !locked || !gate_open || gate_closed || edges_after_program<4)
        $fatal(1,"ROUNDTRIP_COMPLETION_BEFORE_REAL_EPOCH_RETIREMENT lane=%0d",LANE);
      retirements=retirements+1; lease_pending=0;
    end
    // The controller increments completed on this AON edge's real retired.fire.
    #0.001;
    if(cmu_completed!==completions) begin
      if(cmu_completed!==completions+1 || retirements!=completions+1 ||
         results!=retirements || programs!=retirements || !cmu_actual_valid || !cmu_success || cmu_actual_hz!==pending_hz)
        $fatal(1,"ROUNDTRIP_PREMATURE_OR_INCORRECT_CMU_COMPLETION lane=%0d completed=%0d retired=%0d actual=%0d",LANE,cmu_completed,retirements,cmu_actual_hz);
      completions=completions+1;
      $display("ROUNDTRIP_COMPLETED time_ns=%0t lane=%0d completed=%0d actual_hz=%0d edges_after_program=%0d",$time,LANE,completions,cmu_actual_hz,edges_after_program);
    end
  end
endmodule
