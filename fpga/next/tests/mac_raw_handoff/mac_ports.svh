reg  sourceClock = 0;
reg  rawTxClock = 0;
reg  rawRxClock = 0;
reg  commonReset = 0;
wire  registers_request_ready;
reg  registers_request_valid = 0;
reg [63:0] registers_request_bits_address = 0;
reg  registers_request_bits_write = 0;
reg [2:0] registers_request_bits_size = 0;
reg [63:0] registers_request_bits_data = 0;
reg [7:0] registers_request_bits_byteEnable = 0;
reg  registers_response_ready = 0;
wire  registers_response_valid;
wire [63:0] registers_response_bits_data;
wire  registers_response_bits_error;
wire  streams_txData_ready;
reg  streams_txData_valid = 0;
reg [31:0] streams_txData_bits_data = 0;
reg [3:0] streams_txData_bits_keep = 0;
reg  streams_txData_bits_last = 0;
wire  streams_txControl_ready;
reg  streams_txControl_valid = 0;
reg [31:0] streams_txControl_bits_data = 0;
reg [3:0] streams_txControl_bits_keep = 0;
reg  streams_txControl_bits_last = 0;
reg  streams_rxData_ready = 0;
wire  streams_rxData_valid;
wire [31:0] streams_rxData_bits_data;
wire [3:0] streams_rxData_bits_keep;
wire  streams_rxData_bits_last;
reg  streams_rxStatus_ready = 0;
wire  streams_rxStatus_valid;
wire [31:0] streams_rxStatus_bits_data;
wire [3:0] streams_rxStatus_bits_keep;
wire  streams_rxStatus_bits_last;
wire  control_0_ack;
wire  control_0_wake;
reg  control_0_clockEnable = 0;
reg  control_0_quiesce = 0;
reg  control_0_isolate = 0;
reg  control_0_allowAdmission = 0;
wire  control_1_ack;
wire  control_1_wake;
reg  control_1_clockEnable = 0;
reg  control_1_quiesce = 0;
reg  control_1_isolate = 0;
reg  control_1_allowAdmission = 0;
wire  txClock;
wire  rxClock;
wire [7:0] gmiiTxData;
wire  gmiiTxEnable;
wire  gmiiTxError;
reg [4:0] rawRgmiiRxRise = 0;
reg [4:0] rawRgmiiRxFall = 0;
wire [4:0] rgmiiTxRise;
wire [4:0] rgmiiTxFall;
wire  rgmiiTxClockRise;
wire  rgmiiTxClockFall;
wire  linkUp;
wire [1:0] requestedSpeed;
wire [1:0] appliedSpeed;
wire  mediaPending;
wire  txIdle;
wire  rxDrained;
wire  mdc;
reg  mdioIn = 0;
wire  mdioOut;
wire  mdioOe;
wire  irq;
wire  localIdle_0;
wire  localIdle_1;
TriSpeedManagedGmac dut(
.sourceClock(sourceClock),
.rawTxClock(rawTxClock),
.rawRxClock(rawRxClock),
.commonReset(commonReset),
.registers_request_ready(registers_request_ready),
.registers_request_valid(registers_request_valid),
.registers_request_bits_address(registers_request_bits_address),
.registers_request_bits_write(registers_request_bits_write),
.registers_request_bits_size(registers_request_bits_size),
.registers_request_bits_data(registers_request_bits_data),
.registers_request_bits_byteEnable(registers_request_bits_byteEnable),
.registers_response_ready(registers_response_ready),
.registers_response_valid(registers_response_valid),
.registers_response_bits_data(registers_response_bits_data),
.registers_response_bits_error(registers_response_bits_error),
.streams_txData_ready(streams_txData_ready),
.streams_txData_valid(streams_txData_valid),
.streams_txData_bits_data(streams_txData_bits_data),
.streams_txData_bits_keep(streams_txData_bits_keep),
.streams_txData_bits_last(streams_txData_bits_last),
.streams_txControl_ready(streams_txControl_ready),
.streams_txControl_valid(streams_txControl_valid),
.streams_txControl_bits_data(streams_txControl_bits_data),
.streams_txControl_bits_keep(streams_txControl_bits_keep),
.streams_txControl_bits_last(streams_txControl_bits_last),
.streams_rxData_ready(streams_rxData_ready),
.streams_rxData_valid(streams_rxData_valid),
.streams_rxData_bits_data(streams_rxData_bits_data),
.streams_rxData_bits_keep(streams_rxData_bits_keep),
.streams_rxData_bits_last(streams_rxData_bits_last),
.streams_rxStatus_ready(streams_rxStatus_ready),
.streams_rxStatus_valid(streams_rxStatus_valid),
.streams_rxStatus_bits_data(streams_rxStatus_bits_data),
.streams_rxStatus_bits_keep(streams_rxStatus_bits_keep),
.streams_rxStatus_bits_last(streams_rxStatus_bits_last),
.control_0_ack(control_0_ack),
.control_0_wake(control_0_wake),
.control_0_clockEnable(control_0_clockEnable),
.control_0_quiesce(control_0_quiesce),
.control_0_isolate(control_0_isolate),
.control_0_allowAdmission(control_0_allowAdmission),
.control_1_ack(control_1_ack),
.control_1_wake(control_1_wake),
.control_1_clockEnable(control_1_clockEnable),
.control_1_quiesce(control_1_quiesce),
.control_1_isolate(control_1_isolate),
.control_1_allowAdmission(control_1_allowAdmission),
.txClock(txClock),
.rxClock(rxClock),
.gmiiTxData(gmiiTxData),
.gmiiTxEnable(gmiiTxEnable),
.gmiiTxError(gmiiTxError),
.rawRgmiiRxRise(rawRgmiiRxRise),
.rawRgmiiRxFall(rawRgmiiRxFall),
.rgmiiTxRise(rgmiiTxRise),
.rgmiiTxFall(rgmiiTxFall),
.rgmiiTxClockRise(rgmiiTxClockRise),
.rgmiiTxClockFall(rgmiiTxClockFall),
.linkUp(linkUp),
.requestedSpeed(requestedSpeed),
.appliedSpeed(appliedSpeed),
.mediaPending(mediaPending),
.txIdle(txIdle),
.rxDrained(rxDrained),
.mdc(mdc),
.mdioIn(mdioIn),
.mdioOut(mdioOut),
.mdioOe(mdioOe),
.irq(irq),
.localIdle_0(localIdle_0),
.localIdle_1(localIdle_1)
);
