`timescale 1ns/1ps
`default_nettype none
// Shared board shell. CPU300 (I1) / CPU100 (A1) is selected at export/IP creation.
// Default fabric uses MIG UI250. VALENCE_INDEPENDENT_FIXED_DOMAINS selects a separate fabric output;
// DDR, timebase and debug stay on UI250. VALENCE_DYNAMIC_CLOCK_DOMAINS is
// separate explicit opt-in: independent CPU/fabric MMCME4, stable AON50.
// MAC125/PAD250/REF500 share the public quarter-clock divider reset epoch.
// Source candidate only: mapped CDC/ROM, three-speed timing and board are unverified.
module soc_top_common_ddr #(
    // Explicit diagnostic override only; production/default keeps single1100.
    parameter integer RX_CASCADE_STAGE_DELAY_PS = -1,
    // Explicit TX diagnostic candidate; one falling-PAD release driver.
    parameter integer TX_LOCAL_PAD_RESET_RELEASE = 0
) (
    input wire clk_in1_p, clk_in1_n,
    input wire sys_rst_n, button_n, uart_rxd,
    output wire uart_txd, led,
    input wire eth_rxc, eth_rx_ctl,
    input wire [3:0] eth_rxd,
    output wire eth_txc, eth_tx_ctl,
    output wire [3:0] eth_txd,
    output wire eth_mdc, eth_reset_gate,
    inout wire eth_mdio,
    output wire [16:0] c0_ddr4_adr,
    output wire [1:0] c0_ddr4_ba,
    output wire [0:0] c0_ddr4_cke, c0_ddr4_cs_n, c0_ddr4_odt, c0_ddr4_bg,
    output wire c0_ddr4_reset_n, c0_ddr4_act_n,
    output wire [0:0] c0_ddr4_ck_t, c0_ddr4_ck_c,
    inout wire [3:0] c0_ddr4_dm_dbi_n,
    inout wire [31:0] c0_ddr4_dq,
    inout wire [3:0] c0_ddr4_dqs_t, c0_ddr4_dqs_c
);
    wire board_reset = ~sys_rst_n | ~button_n;
    wire dci_ready;
    native_dci_startup dci_startup(.cold_reset(board_reset), .ready(dci_ready));
    wire mig_reset = board_reset | ~dci_ready;
    wire ui_clk, ui_reset, calib_complete, clk_soc, clk_aon, clk_tx, clk_rx, clk_delay;
    wire cpu_locked, eth_locked, mmcm_locked, clk_tx_forward, clk_tx_pad;
    `ifdef VALENCE_DYNAMIC_CLOCK_DOMAINS
    wire aon_locked;
    // Runtime CPU/fabric unlock MUST NOT reset AON/DDR or retained owners.
    assign mmcm_locked = aon_locked & eth_locked;
`else
    assign mmcm_locked = cpu_locked & eth_locked;
`endif
    wire ui_reset_request = mig_reset | ui_reset | ~calib_complete | ~mmcm_locked;
    (* ASYNC_REG = "TRUE" *) reg [2:0] ui_reset_pipe;
    always @(posedge ui_clk or posedge ui_reset_request)
        if (ui_reset_request) ui_reset_pipe <= 3'b111;
        else ui_reset_pipe <= {ui_reset_pipe[1:0], 1'b0};
    wire ui_aresetn = ~ui_reset_pipe[2];

    wire clk_fabric;
`ifndef VALENCE_INDEPENDENT_FIXED_DOMAINS
    assign clk_fabric = ui_clk;
`endif
`ifdef VALENCE_DYNAMIC_CLOCK_DOMAINS
    clk_wiz_common u_clk_wiz (
        .clk_in1(ui_clk), .clk_out1(clk_aon),
        .reset(board_reset | ui_reset), .locked(aon_locked));
    wire [1:0] rate_enable, rate_isolate, rate_quiesce, rate_present;
    wire [1:0] rate_closed, rate_open, rate_locked, rate_resumed, rate_fatal;
    wire [1:0] rate_program_valid, rate_program_ready, rate_fallback;
    wire [1:0] rate_result_valid, rate_result_ready, rate_error;
    wire [23:0] rate_parameters[0:1];
    wire [31:0] rate_hz[0:1], rate_token[0:1], rate_result_hz[0:1], rate_result_token[0:1];
    native_dynamic_clock_domain cpu_clock (
        .aon_clock(clk_aon), .common_cold_reset(soc_reset), .source_clock250(ui_clk),
        .clock_enable(rate_enable[0]), .isolate(rate_isolate[0]),
        .program_valid(rate_program_valid[0]), .program_ready(rate_program_ready[0]),
        .program_parameters(rate_parameters[0]), .program_hz(rate_hz[0]), .program_token(rate_token[0]), .program_fallback(rate_fallback[0]),
        .result_valid(rate_result_valid[0]), .result_ready(rate_result_ready[0]),
        .result_hz(rate_result_hz[0]), .result_token(rate_result_token[0]), .result_error(rate_error[0]),
        .managed_clock(clk_soc), .present(rate_present[0]), .gate_closed(rate_closed[0]),
        .gate_open(rate_open[0]), .locked(rate_locked[0]), .resumed(rate_resumed[0]), .fatal(rate_fatal[0]));
    native_dynamic_clock_domain #(.MAX_PROGRAM_HZ(250000000)) fabric_clock (
        .aon_clock(clk_aon), .common_cold_reset(soc_reset), .source_clock250(ui_clk),
        .clock_enable(rate_enable[1]), .isolate(rate_isolate[1]),
        .program_valid(rate_program_valid[1]), .program_ready(rate_program_ready[1]),
        .program_parameters(rate_parameters[1]), .program_hz(rate_hz[1]), .program_token(rate_token[1]), .program_fallback(rate_fallback[1]),
        .result_valid(rate_result_valid[1]), .result_ready(rate_result_ready[1]),
        .result_hz(rate_result_hz[1]), .result_token(rate_result_token[1]), .result_error(rate_error[1]),
        .managed_clock(clk_fabric), .present(rate_present[1]), .gate_closed(rate_closed[1]),
        .gate_open(rate_open[1]), .locked(rate_locked[1]), .resumed(rate_resumed[1]), .fatal(rate_fatal[1]));
    assign cpu_locked = rate_locked[0];
`else
    clk_wiz_common u_clk_wiz (
        .clk_in1(ui_clk), .clk_out1(clk_soc), .clk_out2(clk_aon),
`ifdef VALENCE_INDEPENDENT_FIXED_DOMAINS
        .clk_out3(clk_fabric),
`endif
        .reset(board_reset | ui_reset), .locked(cpu_locked)
    );
`endif
    // Shared REF500 -> phase-related MAC125/PAD250. Forwarded TXC is DATA
    // to an ODDR, never an internal fabric-generated or multiplexed clock.
    native_gmac_quarter_clock network_clock (
        .ui_clock(ui_clk), .cold_reset(board_reset | ui_reset),
        .tx_source(clk_tx), .tx_forward_source(clk_tx_forward),
        .tx_pad_source(clk_tx_pad), .delay_source(clk_delay), .locked(eth_locked));
    (* ASYNC_REG="TRUE" *) reg [2:0] delay_reset_pipe;
    always @(posedge clk_delay or posedge reset_request)
        if (reset_request) delay_reset_pipe <= 3'b111;
        else delay_reset_pipe <= {delay_reset_pipe[1:0],1'b0};
    // At least 128ns of IDELAYCTRL reset AFTER stable REFCLK; synchronous release.
    reg [63:0] delay_reset_guard;
    always @(posedge clk_delay or posedge delay_reset_pipe[2])
        if (delay_reset_pipe[2]) delay_reset_guard <= {64{1'b1}};
        else delay_reset_guard <= {delay_reset_guard[62:0],1'b0};
    wire delay_reset = delay_reset_guard[63];
    wire delay_ready;
    // Board/UI/calibration/fixed-clock unlock causes assert common reset.
    // Dynamic CPU/fabric unlock is locally fail-closed, not a cold reset cause.
    // There is no raw ready crossing into the CPU domain.
    wire reset_request = ~ui_aresetn;
    // Common assertion reaches every owner; each Chisel domain releases locally.
    // The UI reset pipe is the only board-level owner reset source.
    wire soc_reset = reset_request;
    assign led = ~soc_reset;

    // Keep PHY and TX reset asserted until all replicated IDELAYCTRLs are
    // calibrated. Reassert on RDY loss; release is synchronized per domain.
    // Release PHY reset after 10ms on the un-gated AON clock. The carrier
    // NMOS inverts this signal: HIGH asserts PHYRSTB LOW, LOW releases it.
    wire phy_reset_request = board_reset | ui_reset | ~mmcm_locked | ~delay_ready;
    (* ASYNC_REG="TRUE" *) reg [2:0] phy_reset_pipe;
    always @(posedge clk_aon or posedge phy_reset_request)
        if (phy_reset_request) phy_reset_pipe <= 3'b111;
        else phy_reset_pipe <= {phy_reset_pipe[1:0],1'b0};
    reg [18:0] phy_reset_count;
    always @(posedge clk_aon or posedge phy_reset_pipe[2])
        if (phy_reset_pipe[2]) phy_reset_count <= 0;
        else if (phy_reset_count != 19'd500000) phy_reset_count <= phy_reset_count + 1'b1;
    assign eth_reset_gate = phy_reset_count != 19'd500000;
    wire rx_pad;
    IBUF rx_clock_pad (.I(eth_rxc), .O(rx_pad));
    // RXC may be 125, 25 or 2.5 MHz, or stop completely. Do not instantiate
    // the legacy 125MHz RX MMCM, and do not reset packet/DMA owners on RXC loss.
    BUFG rx_clock_buffer(.I(rx_pad), .O(clk_rx));
    (* ASYNC_REG="TRUE" *) reg [2:0] rx_reset_pipe;
    wire rx_reset_request = soc_reset | ~delay_ready;
    always @(posedge clk_rx or posedge rx_reset_request)
        if (rx_reset_request) rx_reset_pipe <= 3'b111;
        else rx_reset_pipe <= {rx_reset_pipe[1:0],1'b0};
    wire tx_reset_raw, tx_reset_pad;
    native_tx_word_reset_boundary tx_release (
        .clock_tx(clk_tx), .inhibit(soc_reset | ~delay_ready),
        .reset_raw(tx_reset_raw), .reset_forward(tx_reset_pad));
    wire [4:0] rgmii_rx_rise, rgmii_rx_fall, rgmii_tx_rise, rgmii_tx_fall;
    wire rgmii_txc_rise, rgmii_txc_fall;
    native_rgmii_trispeed_quarter #(.RX_DATA_DELAY_PS(1100),
        .RX_CASCADE_STAGE_DELAY_PS(RX_CASCADE_STAGE_DELAY_PS),
        .LOCAL_PAD_RESET_RELEASE(TX_LOCAL_PAD_RESET_RELEASE),
        .REGISTER_SELECTED_HALF(0)) u_rgmii (
        .delay_clock(clk_delay), .delay_reset(delay_reset), .delay_ready(delay_ready),
        .tx_clock(clk_tx), .tx_pad_clock(clk_tx_pad), .tx_pad_reset(tx_reset_pad),
        .tx_reset(tx_reset_raw), .rx_clock(clk_rx), .rx_reset(rx_reset_pipe[2]),
        .tx_rise(rgmii_tx_rise), .tx_fall(rgmii_tx_fall),
        .txc_rise(rgmii_txc_rise), .txc_fall(rgmii_txc_fall),
        .rx_rise(rgmii_rx_rise), .rx_fall(rgmii_rx_fall),
        .rgmii_rx_data(eth_rxd), .rgmii_rx_control(eth_rx_ctl),
        .rgmii_tx_data(eth_txd), .rgmii_tx_control(eth_tx_ctl), .rgmii_tx_clock(eth_txc));
    wire mdio_pad, mdio_out, mdio_oe;
    IOBUF mdio_pad_buffer (.IO(eth_mdio), .I(mdio_out), .T(~mdio_oe), .O(mdio_pad));
    // The Chisel managed PHY is the sole MDIO owner. It includes its own
    // two-FF pad synchronizer and source-domain MDC divider. Never add
    // native_phy_board_control, firmware forced-1G initialization or a second
    // asynchronous MDIO reader around this boundary.
    wire [1:0] requested_speed, applied_speed;
    wire media_pending, media_link_up, media_tx_idle, media_rx_drained;
    wire [3:0] mig_awid;
    wire [31:0] mig_awaddr;
    wire [7:0] mig_awlen;
    wire [2:0] mig_awsize;
    wire [1:0] mig_awburst;
    wire mig_awlock;
    wire [3:0] mig_awcache;
    wire [2:0] mig_awprot;
    wire [3:0] mig_awqos;
    wire mig_awvalid;
    wire mig_awready;
    wire [63:0] mig_wdata;
    wire [7:0] mig_wstrb;
    wire mig_wlast;
    wire mig_wvalid;
    wire mig_wready;
    wire [3:0] mig_bid;
    wire [1:0] mig_bresp;
    wire mig_bvalid;
    wire mig_bready;
    wire [3:0] mig_arid;
    wire [31:0] mig_araddr;
    wire [7:0] mig_arlen;
    wire [2:0] mig_arsize;
    wire [1:0] mig_arburst;
    wire mig_arlock;
    wire [3:0] mig_arcache;
    wire [2:0] mig_arprot;
    wire [3:0] mig_arqos;
    wire mig_arvalid;
    wire mig_arready;
    wire [3:0] mig_rid;
    wire [63:0] mig_rdata;
    wire [1:0] mig_rresp;
    wire mig_rlast;
    wire mig_rvalid;
    wire mig_rready;
    wire dmi_link_up, dmi_req_valid, dmi_req_ready, dmi_rsp_valid, dmi_rsp_ready;
    wire [1:0] dmi_req_op, dmi_rsp_status;
    wire [6:0] dmi_req_address;
    wire [31:0] dmi_req_data, dmi_rsp_data;
    // Both cores use the same custom loader protocol. Board chain includes one
    // other TAP's BYPASS bit: USER2 frame is 65 clocks, not legacy 64 clocks.
    ValenceI1BscanDebugPort #(.ENABLE(1), .JTAG_CHAIN(2), .SCAN_BITS(65)) u_debug (
        .debug_clk(ui_clk), .debug_por_n(~soc_reset), .dmi_reset_n(dmi_link_up),
        .dmi_req_valid(dmi_req_valid), .dmi_req_ready(dmi_req_ready),
        .dmi_req_op(dmi_req_op), .dmi_req_address(dmi_req_address), .dmi_req_data(dmi_req_data),
        .dmi_rsp_valid(dmi_rsp_valid), .dmi_rsp_ready(dmi_rsp_ready),
        .dmi_rsp_status(dmi_rsp_status), .dmi_rsp_data(dmi_rsp_data));
    CommonMachinePlatform u_soc (
        .cpuClock(clk_soc), .fabricClock(clk_fabric), .alwaysOnClock(clk_aon),
`ifdef VALENCE_DYNAMIC_CLOCK_DOMAINS
        .rateBackend_0_present(rate_present[0]),
        .rateBackend_0_gateClosed(rate_closed[0]),
        .rateBackend_0_gateOpen(rate_open[0]),
        .rateBackend_0_locked(rate_locked[0]),
        .rateBackend_0_resumed(rate_resumed[0]),
        .rateBackend_0_fatal(rate_fatal[0]),
        .rateBackend_0_clockEnable(rate_enable[0]),
        .rateBackend_0_isolate(rate_isolate[0]),
        .rateBackend_0_quiesce(rate_quiesce[0]),
        .rateBackend_0_program_valid(rate_program_valid[0]),
        .rateBackend_0_program_ready(rate_program_ready[0]),
        .rateBackend_0_program_bits_parameters(rate_parameters[0]),
        .rateBackend_0_program_bits_hz(rate_hz[0]),
        .rateBackend_0_program_bits_token(rate_token[0]),
        .rateBackend_0_program_bits_fallback(rate_fallback[0]),
        .rateBackend_0_result_valid(rate_result_valid[0]),
        .rateBackend_0_result_ready(rate_result_ready[0]),
        .rateBackend_0_result_bits_hz(rate_result_hz[0]),
        .rateBackend_0_result_bits_token(rate_result_token[0]),
        .rateBackend_0_result_bits_error(rate_error[0]),
        .rateBackend_1_present(rate_present[1]),
        .rateBackend_1_gateClosed(rate_closed[1]),
        .rateBackend_1_gateOpen(rate_open[1]),
        .rateBackend_1_locked(rate_locked[1]),
        .rateBackend_1_resumed(rate_resumed[1]),
        .rateBackend_1_fatal(rate_fatal[1]),
        .rateBackend_1_clockEnable(rate_enable[1]),
        .rateBackend_1_isolate(rate_isolate[1]),
        .rateBackend_1_quiesce(rate_quiesce[1]),
        .rateBackend_1_program_valid(rate_program_valid[1]),
        .rateBackend_1_program_ready(rate_program_ready[1]),
        .rateBackend_1_program_bits_parameters(rate_parameters[1]),
        .rateBackend_1_program_bits_hz(rate_hz[1]),
        .rateBackend_1_program_bits_token(rate_token[1]),
        .rateBackend_1_program_bits_fallback(rate_fallback[1]),
        .rateBackend_1_result_valid(rate_result_valid[1]),
        .rateBackend_1_result_ready(rate_result_ready[1]),
        .rateBackend_1_result_bits_hz(rate_result_hz[1]),
        .rateBackend_1_result_bits_token(rate_result_token[1]),
        .rateBackend_1_result_bits_error(rate_error[1]),
`endif
`ifdef VALENCE_INDEPENDENT_FIXED_DOMAINS
        .ddrClock(ui_clk), .timebaseClock(ui_clk), .debugClock(ui_clk),
`endif
        .rawUartClock(clk_aon), .rawTxClock(clk_tx), .rawRxClock(clk_rx),
        .commonColdReset(soc_reset), .io_ddrReady(calib_complete & ui_aresetn),
        .io_bootEnable(1'b1), .io_sources(31'b0),
        .io_uartRx(uart_rxd), .io_uartTx(uart_txd),
        .io_gmiiRxData(8'b0), .io_gmiiRxValid(1'b0), .io_gmiiRxError(1'b0), .io_linkUp(1'b0),
        .io_triSpeedRgmii_rxRise(rgmii_rx_rise), .io_triSpeedRgmii_rxFall(rgmii_rx_fall),
        .io_triSpeedRgmii_txRise(rgmii_tx_rise), .io_triSpeedRgmii_txFall(rgmii_tx_fall),
        .io_triSpeedRgmii_txClockRise(rgmii_txc_rise), .io_triSpeedRgmii_txClockFall(rgmii_txc_fall),
        .io_mdc(eth_mdc), .io_mdioIn(mdio_pad), .io_mdioOut(mdio_out), .io_mdioOe(mdio_oe),
        .io_jtagLinkUp(dmi_link_up),
        .io_jtagDmi_request_valid(dmi_req_valid), .io_jtagDmi_request_ready(dmi_req_ready),
        .io_jtagDmi_request_bits_op(dmi_req_op), .io_jtagDmi_request_bits_address(dmi_req_address),
        .io_jtagDmi_request_bits_data(dmi_req_data),
        .io_jtagDmi_response_valid(dmi_rsp_valid), .io_jtagDmi_response_ready(dmi_rsp_ready),
        .io_jtagDmi_response_bits_status(dmi_rsp_status), .io_jtagDmi_response_bits_data(dmi_rsp_data),
        .io_maintenance_valid(1'b0), .io_maintenance_bits_epoch('0),
        .io_maintenance_bits_invalidateInstructions(1'b0), .io_maintenance_bits_invalidateTranslations(1'b0),
        .io_ddrAxi_aw_bits_id(mig_awid),
        .io_ddrAxi_aw_bits_addr(mig_awaddr),
        .io_ddrAxi_aw_bits_len(mig_awlen),
        .io_ddrAxi_aw_bits_size(mig_awsize),
        .io_ddrAxi_aw_bits_burst(mig_awburst),
        .io_ddrAxi_aw_bits_lock(mig_awlock),
        .io_ddrAxi_aw_bits_cache(mig_awcache),
        .io_ddrAxi_aw_bits_prot(mig_awprot),
        .io_ddrAxi_aw_bits_qos(mig_awqos),
        .io_ddrAxi_aw_valid(mig_awvalid),
        .io_ddrAxi_aw_ready(mig_awready),
        .io_ddrAxi_w_bits_data(mig_wdata),
        .io_ddrAxi_w_bits_strb(mig_wstrb),
        .io_ddrAxi_w_bits_last(mig_wlast),
        .io_ddrAxi_w_valid(mig_wvalid),
        .io_ddrAxi_w_ready(mig_wready),
        .io_ddrAxi_b_bits_id(mig_bid),
        .io_ddrAxi_b_bits_resp(mig_bresp),
        .io_ddrAxi_b_valid(mig_bvalid),
        .io_ddrAxi_b_ready(mig_bready),
        .io_ddrAxi_ar_bits_id(mig_arid),
        .io_ddrAxi_ar_bits_addr(mig_araddr),
        .io_ddrAxi_ar_bits_len(mig_arlen),
        .io_ddrAxi_ar_bits_size(mig_arsize),
        .io_ddrAxi_ar_bits_burst(mig_arburst),
        .io_ddrAxi_ar_bits_lock(mig_arlock),
        .io_ddrAxi_ar_bits_cache(mig_arcache),
        .io_ddrAxi_ar_bits_prot(mig_arprot),
        .io_ddrAxi_ar_bits_qos(mig_arqos),
        .io_ddrAxi_ar_valid(mig_arvalid),
        .io_ddrAxi_ar_ready(mig_arready),
        .io_ddrAxi_r_bits_id(mig_rid),
        .io_ddrAxi_r_bits_data(mig_rdata),
        .io_ddrAxi_r_bits_resp(mig_rresp),
        .io_ddrAxi_r_bits_last(mig_rlast),
        .io_ddrAxi_r_valid(mig_rvalid),
        .io_ddrAxi_r_ready(mig_rready)
    );
    ddr4_0 u_ddr (
        .sys_rst(mig_reset), .c0_sys_clk_p(clk_in1_p), .c0_sys_clk_n(clk_in1_n),
        .c0_ddr4_ui_clk(ui_clk), .c0_ddr4_ui_clk_sync_rst(ui_reset),
        .c0_init_calib_complete(calib_complete), .c0_ddr4_aresetn(ui_aresetn),
        .c0_ddr4_adr(c0_ddr4_adr),
        .c0_ddr4_ba(c0_ddr4_ba),
        .c0_ddr4_cke(c0_ddr4_cke),
        .c0_ddr4_cs_n(c0_ddr4_cs_n),
        .c0_ddr4_odt(c0_ddr4_odt),
        .c0_ddr4_bg(c0_ddr4_bg),
        .c0_ddr4_reset_n(c0_ddr4_reset_n),
        .c0_ddr4_act_n(c0_ddr4_act_n),
        .c0_ddr4_ck_t(c0_ddr4_ck_t),
        .c0_ddr4_ck_c(c0_ddr4_ck_c),
        .c0_ddr4_dm_dbi_n(c0_ddr4_dm_dbi_n),
        .c0_ddr4_dq(c0_ddr4_dq),
        .c0_ddr4_dqs_t(c0_ddr4_dqs_t),
        .c0_ddr4_dqs_c(c0_ddr4_dqs_c),
        .c0_ddr4_s_axi_awid(mig_awid),
        .c0_ddr4_s_axi_awaddr(mig_awaddr[30:0]),
        .c0_ddr4_s_axi_awlen(mig_awlen),
        .c0_ddr4_s_axi_awsize(mig_awsize),
        .c0_ddr4_s_axi_awburst(mig_awburst),
        .c0_ddr4_s_axi_awlock(mig_awlock),
        .c0_ddr4_s_axi_awcache(mig_awcache),
        .c0_ddr4_s_axi_awprot(mig_awprot),
        .c0_ddr4_s_axi_awqos(mig_awqos),
        .c0_ddr4_s_axi_awvalid(mig_awvalid),
        .c0_ddr4_s_axi_awready(mig_awready),
        .c0_ddr4_s_axi_wdata(mig_wdata),
        .c0_ddr4_s_axi_wstrb(mig_wstrb),
        .c0_ddr4_s_axi_wlast(mig_wlast),
        .c0_ddr4_s_axi_wvalid(mig_wvalid),
        .c0_ddr4_s_axi_wready(mig_wready),
        .c0_ddr4_s_axi_bid(mig_bid),
        .c0_ddr4_s_axi_bresp(mig_bresp),
        .c0_ddr4_s_axi_bvalid(mig_bvalid),
        .c0_ddr4_s_axi_bready(mig_bready),
        .c0_ddr4_s_axi_arid(mig_arid),
        .c0_ddr4_s_axi_araddr(mig_araddr[30:0]),
        .c0_ddr4_s_axi_arlen(mig_arlen),
        .c0_ddr4_s_axi_arsize(mig_arsize),
        .c0_ddr4_s_axi_arburst(mig_arburst),
        .c0_ddr4_s_axi_arlock(mig_arlock),
        .c0_ddr4_s_axi_arcache(mig_arcache),
        .c0_ddr4_s_axi_arprot(mig_arprot),
        .c0_ddr4_s_axi_arqos(mig_arqos),
        .c0_ddr4_s_axi_arvalid(mig_arvalid),
        .c0_ddr4_s_axi_arready(mig_arready),
        .c0_ddr4_s_axi_rid(mig_rid),
        .c0_ddr4_s_axi_rdata(mig_rdata),
        .c0_ddr4_s_axi_rresp(mig_rresp),
        .c0_ddr4_s_axi_rlast(mig_rlast),
        .c0_ddr4_s_axi_rvalid(mig_rvalid),
        .c0_ddr4_s_axi_rready(mig_rready)
    );
endmodule

`default_nettype wire
