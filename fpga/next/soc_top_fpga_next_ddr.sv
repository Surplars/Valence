`timescale 1ns/1ps
// 200 MHz oscillator -> MIG UI250 -> CPU100 / AON-UART50 / MAC TX125 MHz.
// The physical oscillator is buffered only by MIG; AXI uses an asynchronous CDC IP.
// SOURCE-ONLY EXPERIMENT: matched to FpgaNextConfig.TriSpeedCandidate.
// No native-clock simulation, synthesis, STA, bitstream or board qualification.
// JTAG reservation pins deliberately have no package assignments here.
module soc_top_fpga_next_ddr (
    input wire jtag_tck, jtag_tms, jtag_tdi, jtag_trst_n, jtag_debug_por_n,
    output wire jtag_tdo, jtag_tdo_oe,
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
    wire ui_clk, ui_reset, calib_complete, clk_soc, clk_aon, clk_tx, clk_rx, clk_delay;
    wire cpu_locked, eth_locked, mmcm_locked, clk_tx_forward, clk_tx_pad;
    assign mmcm_locked = cpu_locked & eth_locked;
    wire ui_reset_request = board_reset | ui_reset | ~calib_complete | ~mmcm_locked;
    (* ASYNC_REG = "TRUE" *) reg [2:0] ui_reset_pipe;
    always @(posedge ui_clk or posedge ui_reset_request)
        if (ui_reset_request) ui_reset_pipe <= 3'b111;
        else ui_reset_pipe <= {ui_reset_pipe[1:0], 1'b0};
    wire ui_aresetn = ~ui_reset_pipe[2];

    clk_wiz_ddr u_clk_wiz (
        .clk_in1(ui_clk), .clk_out1(clk_soc), .clk_out2(clk_aon), .clk_out3(),
        .reset(board_reset | ui_reset), .locked(cpu_locked)
    );
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
    // All board/UI/calibration/clock-unlock causes assert ui_reset_pipe
    // asynchronously. Its qualified output directly asserts CPU reset;
    // CPU release then waits three clk_soc edges without combinational CDC.
    wire reset_request = ~ui_aresetn;
    (* ASYNC_REG = "TRUE" *) reg [2:0] reset_pipe;
    always @(posedge clk_soc or posedge reset_request)
        if (reset_request) reset_pipe <= 3'b111;
        else reset_pipe <= {reset_pipe[1:0], 1'b0};
    wire soc_reset = reset_pipe[2];
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
    native_rgmii_trispeed_quarter #(.RX_DATA_DELAY_PS(1100)) u_rgmii (
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
    // two-FF pad synchronizer and divider40@100MHz (1.25MHz MDC). Never add
    // native_phy_board_control, firmware forced-1G initialization or a second
    // asynchronous MDIO reader around this boundary.
    wire [1:0] requested_speed, applied_speed;
    wire media_pending, media_link_up, media_tx_idle, media_rx_drained;
    wire [3:0] cpu_awid;
    wire [31:0] cpu_awaddr;
    wire [7:0] cpu_awlen;
    wire [2:0] cpu_awsize;
    wire [1:0] cpu_awburst;
    wire cpu_awlock;
    wire [3:0] cpu_awcache;
    wire [2:0] cpu_awprot;
    wire [3:0] cpu_awqos;
    wire cpu_awvalid;
    wire cpu_awready;
    wire [63:0] cpu_wdata;
    wire [7:0] cpu_wstrb;
    wire cpu_wlast;
    wire cpu_wvalid;
    wire cpu_wready;
    wire [3:0] cpu_bid;
    wire [1:0] cpu_bresp;
    wire cpu_bvalid;
    wire cpu_bready;
    wire [3:0] cpu_arid;
    wire [31:0] cpu_araddr;
    wire [7:0] cpu_arlen;
    wire [2:0] cpu_arsize;
    wire [1:0] cpu_arburst;
    wire cpu_arlock;
    wire [3:0] cpu_arcache;
    wire [2:0] cpu_arprot;
    wire [3:0] cpu_arqos;
    wire cpu_arvalid;
    wire cpu_arready;
    wire [3:0] cpu_rid;
    wire [63:0] cpu_rdata;
    wire [1:0] cpu_rresp;
    wire cpu_rlast;
    wire cpu_rvalid;
    wire cpu_rready;
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
    FpgaNextSocTop u_soc (
        .clock(clk_soc), .reset(soc_reset), .io_ddrReady(~soc_reset),
        .io_peripheralClock(clk_aon), .io_alwaysOnClock(clk_aon),
        .io_nativeGmac_rawTxClock(clk_tx), .io_nativeGmac_rawRxClock(clk_rx),
        .io_nativeGmac_rxData(8'b0), .io_nativeGmac_rxValid(1'b0),
        .io_nativeGmac_rxError(1'b0), .io_nativeGmac_linkUp(1'b0),
        .io_nativeGmac_txData(), .io_nativeGmac_txEnable(), .io_nativeGmac_txError(),
        .io_nativeGmac_triSpeedRgmii_rxRise(rgmii_rx_rise),
        .io_nativeGmac_triSpeedRgmii_rxFall(rgmii_rx_fall),
        .io_nativeGmac_triSpeedRgmii_txRise(rgmii_tx_rise),
        .io_nativeGmac_triSpeedRgmii_txFall(rgmii_tx_fall),
        .io_nativeGmac_triSpeedRgmii_txClockRise(rgmii_txc_rise),
        .io_nativeGmac_triSpeedRgmii_txClockFall(rgmii_txc_fall),
        .io_nativeGmac_triSpeedRgmii_requestedSpeed(requested_speed),
        .io_nativeGmac_triSpeedRgmii_appliedSpeed(applied_speed),
        .io_nativeGmac_triSpeedRgmii_pending(media_pending),
        .io_nativeGmac_triSpeedRgmii_linkUp(media_link_up),
        .io_nativeGmac_triSpeedRgmii_txIdle(media_tx_idle),
        .io_nativeGmac_triSpeedRgmii_rxDrained(media_rx_drained),
        .io_nativeGmac_mdc(eth_mdc), .io_nativeGmac_mdioIn(mdio_pad),
        .io_nativeGmac_mdioOut(mdio_out), .io_nativeGmac_mdioOe(mdio_oe),
        .jtag_tck(jtag_tck), .jtag_tms(jtag_tms), .jtag_tdi(jtag_tdi),
        .jtag_trstN(jtag_trst_n), .jtag_debugPorN(jtag_debug_por_n),
        .jtag_tdo(jtag_tdo), .jtag_tdoOe(jtag_tdo_oe),
        .io_uartRx(uart_rxd), .io_uartTx(uart_txd),
        .io_ddrAxi_aw_bits_id(cpu_awid),
        .io_ddrAxi_aw_bits_addr(cpu_awaddr),
        .io_ddrAxi_aw_bits_len(cpu_awlen),
        .io_ddrAxi_aw_bits_size(cpu_awsize),
        .io_ddrAxi_aw_bits_burst(cpu_awburst),
        .io_ddrAxi_aw_bits_lock(cpu_awlock),
        .io_ddrAxi_aw_bits_cache(cpu_awcache),
        .io_ddrAxi_aw_bits_prot(cpu_awprot),
        .io_ddrAxi_aw_bits_qos(cpu_awqos),
        .io_ddrAxi_aw_valid(cpu_awvalid),
        .io_ddrAxi_aw_ready(cpu_awready),
        .io_ddrAxi_w_bits_data(cpu_wdata),
        .io_ddrAxi_w_bits_strb(cpu_wstrb),
        .io_ddrAxi_w_bits_last(cpu_wlast),
        .io_ddrAxi_w_valid(cpu_wvalid),
        .io_ddrAxi_w_ready(cpu_wready),
        .io_ddrAxi_b_bits_id(cpu_bid),
        .io_ddrAxi_b_bits_resp(cpu_bresp),
        .io_ddrAxi_b_valid(cpu_bvalid),
        .io_ddrAxi_b_ready(cpu_bready),
        .io_ddrAxi_ar_bits_id(cpu_arid),
        .io_ddrAxi_ar_bits_addr(cpu_araddr),
        .io_ddrAxi_ar_bits_len(cpu_arlen),
        .io_ddrAxi_ar_bits_size(cpu_arsize),
        .io_ddrAxi_ar_bits_burst(cpu_arburst),
        .io_ddrAxi_ar_bits_lock(cpu_arlock),
        .io_ddrAxi_ar_bits_cache(cpu_arcache),
        .io_ddrAxi_ar_bits_prot(cpu_arprot),
        .io_ddrAxi_ar_bits_qos(cpu_arqos),
        .io_ddrAxi_ar_valid(cpu_arvalid),
        .io_ddrAxi_ar_ready(cpu_arready),
        .io_ddrAxi_r_bits_id(cpu_rid),
        .io_ddrAxi_r_bits_data(cpu_rdata),
        .io_ddrAxi_r_bits_resp(cpu_rresp),
        .io_ddrAxi_r_bits_last(cpu_rlast),
        .io_ddrAxi_r_valid(cpu_rvalid),
        .io_ddrAxi_r_ready(cpu_rready)
    );
    axi_clock_converter_ddr u_axi_cdc (
        .s_axi_aclk(clk_soc), .s_axi_aresetn(~soc_reset),
        .m_axi_aclk(ui_clk), .m_axi_aresetn(ui_aresetn),
        .s_axi_awid(cpu_awid),
        .s_axi_awaddr(cpu_awaddr),
        .s_axi_awlen(cpu_awlen),
        .s_axi_awsize(cpu_awsize),
        .s_axi_awburst(cpu_awburst),
        .s_axi_awlock(cpu_awlock),
        .s_axi_awcache(cpu_awcache),
        .s_axi_awprot(cpu_awprot),
        .s_axi_awqos(cpu_awqos),
        .s_axi_awregion(4'b0000),
        .s_axi_awvalid(cpu_awvalid),
        .s_axi_awready(cpu_awready),
        .s_axi_wdata(cpu_wdata),
        .s_axi_wstrb(cpu_wstrb),
        .s_axi_wlast(cpu_wlast),
        .s_axi_wvalid(cpu_wvalid),
        .s_axi_wready(cpu_wready),
        .s_axi_bid(cpu_bid),
        .s_axi_bresp(cpu_bresp),
        .s_axi_bvalid(cpu_bvalid),
        .s_axi_bready(cpu_bready),
        .s_axi_arid(cpu_arid),
        .s_axi_araddr(cpu_araddr),
        .s_axi_arlen(cpu_arlen),
        .s_axi_arsize(cpu_arsize),
        .s_axi_arburst(cpu_arburst),
        .s_axi_arlock(cpu_arlock),
        .s_axi_arcache(cpu_arcache),
        .s_axi_arprot(cpu_arprot),
        .s_axi_arqos(cpu_arqos),
        .s_axi_arregion(4'b0000),
        .s_axi_arvalid(cpu_arvalid),
        .s_axi_arready(cpu_arready),
        .s_axi_rid(cpu_rid),
        .s_axi_rdata(cpu_rdata),
        .s_axi_rresp(cpu_rresp),
        .s_axi_rlast(cpu_rlast),
        .s_axi_rvalid(cpu_rvalid),
        .s_axi_rready(cpu_rready),
        .m_axi_awid(mig_awid),
        .m_axi_awaddr(mig_awaddr),
        .m_axi_awlen(mig_awlen),
        .m_axi_awsize(mig_awsize),
        .m_axi_awburst(mig_awburst),
        .m_axi_awlock(mig_awlock),
        .m_axi_awcache(mig_awcache),
        .m_axi_awprot(mig_awprot),
        .m_axi_awqos(mig_awqos),
        .m_axi_awvalid(mig_awvalid),
        .m_axi_awready(mig_awready),
        .m_axi_wdata(mig_wdata),
        .m_axi_wstrb(mig_wstrb),
        .m_axi_wlast(mig_wlast),
        .m_axi_wvalid(mig_wvalid),
        .m_axi_wready(mig_wready),
        .m_axi_bid(mig_bid),
        .m_axi_bresp(mig_bresp),
        .m_axi_bvalid(mig_bvalid),
        .m_axi_bready(mig_bready),
        .m_axi_arid(mig_arid),
        .m_axi_araddr(mig_araddr),
        .m_axi_arlen(mig_arlen),
        .m_axi_arsize(mig_arsize),
        .m_axi_arburst(mig_arburst),
        .m_axi_arlock(mig_arlock),
        .m_axi_arcache(mig_arcache),
        .m_axi_arprot(mig_arprot),
        .m_axi_arqos(mig_arqos),
        .m_axi_arvalid(mig_arvalid),
        .m_axi_arready(mig_arready),
        .m_axi_rid(mig_rid),
        .m_axi_rdata(mig_rdata),
        .m_axi_rresp(mig_rresp),
        .m_axi_rlast(mig_rlast),
        .m_axi_rvalid(mig_rvalid),
        .m_axi_rready(mig_rready)
    );
    ddr4_0 u_ddr (
        .sys_rst(board_reset), .c0_sys_clk_p(clk_in1_p), .c0_sys_clk_n(clk_in1_n),
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
