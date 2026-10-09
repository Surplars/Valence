Valence Stage2 TFTP Pacing v2 — 2026-10-09

本版改什么
实板日志已证实旧版 window4 的 RRQ/OACK/ACK4 一致，且无重传/超时；慢在主机逐包等待。
旧日志的粗粒度 monotonic 计时还会把短操作记录为0，不能据此认定读取/发送本身不耗时。
本版用 perf_counter_ns 的高分辨率单调计时记录进度、read/send/ack_wait/pacing/elapsed 和事件。
正延迟只作用在每个发送/重传窗口内部相邻 DATA 之间；新窗口首包与窗口末尾不额外 sleep。
显式 --packet-delay-us 0 可禁用 pacing。它不会启动忙等、改全局计时器或修改系统配置。
高分辨率计时不保证操作系统的 sleep 能达到微秒调度；0与正延迟可进行可复现对照。

默认值与范围
默认仍为 window 上限1、block上限1024、delay100微秒；window1不执行逐包等待。
本版改变计时和 pacing，不改变 OACK、累计ACK、重传上限或缺口恢复算法。
默认省略 --manifest 仍校验旧V3配对；显式V4清单校验V4，不放松整文件SHA256。
实际window = 客户端请求与主机上限的较小值。RRQ不含windowsize则始终window1。
只向 --board 指定IPv4提供两个固定RRQ名：Image、valence-vl100.dtb。
manifest不能增加其他文件名、服务目录或任意路径。

解压与准确路径
把V4固件ZIP内容解压到同一父目录下的 v4 文件夹。
本工具ZIP正常解压后得到 Valence-Stage2-TFTP-Pacing-v2-20261009 文件夹。
本工具的 stage2_tftp.py、netboot_host.py、stage2-pair-v4.json 直接位于该文件夹。
不要混用上一版netboot_host.py，也不要单独覆盖V4固件目录的BootROM服务器。
新版stage2脚本会校验相邻引擎SHA256并在ENGINE日志打印 stage2-pacing-v2-20261009。

由上述父目录打开终端：
  cd Valence-Stage2-TFTP-Pacing-v2-20261009

V4固件ZIP为避免重复大载荷，只包含valence.vld，先生成原始Image：
  python ../v4/extract_payloads.py --image
如果 ../v4/Image 已经存在且是该V4提取物，跳过；提取器拒绝覆盖已有文件。
不要将valence.vld或组合OpenSBI BIN当作原始Image。

稳定window1基线：
  python stage2_tftp.py --image ../v4/Image --dtb ../v4/valence-vl100.dtb --manifest stage2-pair-v4.json --bind 192.168.137.1 --board 192.168.137.30
板端下载前：
  setenv tftpwindowsize 1

window4、无主机逐包等待的对照：
先Ctrl-C停止之前的主机服务，再启动：
  python stage2_tftp.py --image ../v4/Image --dtb ../v4/valence-vl100.dtb --manifest stage2-pair-v4.json --bind 192.168.137.1 --board 192.168.137.30 --max-windowsize 4 --packet-delay-us 0
板端下载前：
  setenv tftpwindowsize 4
  printenv tftpwindowsize
也可两端均改成2，先试window2。无需saveenv或重编译U-Boot。

window4、100微秒窗口内延迟对照：
  python stage2_tftp.py --image ../v4/Image --dtb ../v4/valence-vl100.dtb --manifest stage2-pair-v4.json --bind 192.168.137.1 --board 192.168.137.30 --max-windowsize 4 --packet-delay-us 100
每次对照先停止上一服务；同一时间只开一个监听同端口的服务。
0是显式关闭节流，会提高瞬时到包速率；若出现丢包/重传，应退回window1或尝试window2/正延迟。
未声称window4或delay0一定更快；Windows实测性能和板端容量仍需本次对照验证。

V3兼容
  python stage2_tftp.py --image <V3目录>/Image --dtb <V3目录>/valence-vl100.dtb --bind 192.168.137.1 --board 192.168.137.30
不指定manifest时严格使用原V3大小和SHA256，也可指定stage2-pair-v3.json。
不要为了通过检查自行修改清单里的大小/哈希。服务期间不要修改或替换已校验的Image/DTB。

日志
REQUEST_RECEIVED列出RRQ选项；REQUEST_ACCEPTED才是实际生效blksize/windowsize。
LIMITS包含packet_delay_us、pacing模式、timing_clock='perf_counter_ns'及计时器分辨率。
TFTP STATS中pacing是实际进入sleep的耗时，不是目标延迟的简单相加。
read/send/ack_wait/elapsed采用同一高分辨率时钟，仍保留可注入的测试时钟接口。
正常完成、失败、Ctrl-C和输入文件消失均输出统计。Ctrl-C退出码130。
--once仍表示首次成功传输一个文件后退出；Image与DTB均需传时不要加--once。
FIRST_ACK_AFTER_DATA_OBSERVED只表示收到ACK，其有效性由引擎判断。
eof_acked=yes只说明主机收到最终ACK，必须按镜像说明检查板端CRC后再booti。
V4 Image CRC32 491d21cc；DTB CRC32 4efaaa66。
V4 Image临时地址0x84000000，DTB0x90000000；不可用旧0x83000000 DTB地址。

已知协议边界
U-Boot忽略旧重复DATA，不会总是立即补ACK；中间ACK丢失可能等约5秒的板端超时ACK。
U-Boot收到最终DATA退出下载后若最终ACK丢失，主机会报告未确认完成，应核对板端CRC。
上述状态机行为未更改，也未将“没有ACK”伪报为成功。

检查与依赖
  python -B -m unittest discover -s tests -v
仅需Python3.8或更新版本及标准库。实际host测试在Python3.12，语法按3.8检查。
测试覆盖合成小文件localhost UDP、独立U-Boot式ACK/loss/wrap，以及零延迟/窗口内pacing/调度超时。
没有模拟或保证Windows的真实网卡/线程调度，也不替代真实板测。
确切测试数量/范围见VALIDATION.json；Git与源码发布清单绑定本目录的文件字节。
此小包没有固件大文件；原v1包保留可回退。本版只更新独立stage2工具副本。

仓库源码版说明
本目录导入已审核的 stage2-tftp-pacing-v2-20261009 小包源码；README 在此改名为 README.md。
此处 netboot_host.py 是独立 stage2 引擎，包含本版计时和 pacing 修复；
工程 fpga/firmware/netboot_host.py 保持原有 BootROM 下载行为，不应互相覆盖。
完整原始 host-tests.log、pair-verification.log 与 SHA256SUMS 留在外部交付包，未放入源码 Git。
严格配对清单和测试所需 Python 源码均在本目录；Image/DTB 是单独交付的输入。
从仓库使用时，可 cd 到 fpga/firmware/tools/stage2_tftp，按实际 V4 解压路径替换上面的 ../v4。
窗口取值 1..16 是协议上限；localhost 动态覆盖 1/2/4，独立 loss/wrap 接收模型覆盖 2/4。
显式 0 pacing 在注入时钟测试覆盖 1/2/4/16；这不构成所有窗口的实板吞吐或容量验证。
