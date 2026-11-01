[English](README.md) · [Deutsch](README.de.md) · **中文**

# 通过编程器访问三星 eMMC 厂商命令 —— 实测结果与一个未解问题

我们正在修理一台索尼电视：读取并重写主板的 eMMC。在此过程中，我们尝试用一台消费级编程器
（XGecu T48），在 macOS 上通过自写的 Python USB 驱动，访问三星 eMMC 的**厂商命令接口**
——也就是通往控制器 BootROM 模式的那条路。

本仓库记录了我们的实测结果、**尚未**证实的部分，以及我们需要什么才能补上这个缺口。
如果你有 UFPI 或 EasyJTAG，你可能十分钟内就能回答这个问题。

适用范围：对自己硬件上的设备进行维修和数据恢复。不涉及 DRM 规避。
范围、授权与法律定位详见 **[LEGAL.zh.md](LEGAL.zh.md)**。

---

## 1. 为什么这重要

按 JEDEC 规范，eMMC 的 RPMB 密钥是只写的：控制器持有密钥，每个 RPMB 帧都用
HMAC-SHA-256 认证，任何标准命令都不会返回密钥。近期的工作
（[arXiv 2511.22340](https://arxiv.org/abs/2511.22340)）用电磁故障注入绕过 HMAC 校验
——但这得到的是**无需密钥的写入**，从来不是密钥本身。

厂商命令是另一条路。[Oran Avraham 的 `i9300_emmc_toolbox`](https://github.com/oranav/i9300_emmc_toolbox)
（Galaxy S3，三星 VTU00M，2017 年）用清晰的 C 代码记录了它：

| 步骤 | 命令 | 参数 |
|---|---|---|
| 进入 BootROM 恢复模式 | CMD1 (SEND_OP_COND) | `0x69FF87A9`（敲门码，不是合法的 OCR 值） |
| 解锁 CMD60 | CMD60 | `0xEFAC60FC` |
| 激活固件槽 | CMD60 | `0xABCD1280` + type |
| 启动定时器（有返回值） | CMD60 | `0xABCD1240` |
| 解锁 CMD62 | CMD62 | `0xEFAC62EC` |
| 打开读 RAM 后门 | CMD62 | `0x10210002` |
| 退出 CMD62 | CMD62 | `0x00DECCEE` |

读 RAM 后门一旦打开，**正常的块读写路径就会被重定向到控制器 RAM**：
CMD35（地址）→ CMD36（长度）→ CMD38（执行）→ CMD17（取回一个 512 字节块）。
该仓库中的 `dump_fw_bootrom.c` 就是这样完整导出 128 KB 控制器固件，完全不需要认证，
因为控制器已经不再执行它自己的固件。

RPMB 密钥是否就在那段可读 RAM 中，目前未知。如果确实如此，密钥就是这次导出的副产品。

---

## 2. 我们在 T48 上实测到了什么

T48 使用私有 USB 协议。对 eMMC，它有一个命令入口，顶层操作码 `0x27`：

```
主机 -> 27 <sub_op> 00 00 <arg32 LE>           （8 字节，EP1 OUT）
设备 -> 27 00 10 00 00 09 <flags> 00           （8 字节，EP1 IN）
```

所有已知的子操作码都遵循 `sub_op = 0x40 + CMD 号` 的规律：

```
0x46 → CMD6    0x4C → CMD12   0x4D → CMD13   0x50 → CMD16
0x57 → CMD23   0x5C → CMD28   0x5D → CMD29
```

按此规律，CMD1 = `0x41`，CMD60 = `0x7C`，CMD62 = `0x7E`。

逆向笔记中称 `reply_buf[1] != 0` 表示成功。**在这版固件上这是错的**：字节 1 在每一条应答中
都是 `0x00`，包括那些明显可用的命令。字节 6 乍看像状态字节，其实不是：

* `0x7E` 对参数 `0`、`0xFFFFFFFF`、`0xEFAC62EC`、`0x00DECCEE` 的应答完全相同。
* `0x4C` 对参数 `0` 与 `0xFFFFFFFF` 的应答完全相同。
* `0x41` 在参数完全相同的情况下，一次返回 `0x08`，另一次返回 `0x00`。
* 在 A/B 交替试验中，每次切换后的**第一个**包携带 `0x08`，之后的每个包都是 `0x00`
  ——对所有子操作码都一样。`0x57` 在读取前等待 20 ms 时返回 `0x48`。

这些值（`0x00`、`0x08`、`0x40`、`0x48`）是瞬态位。**这 8 字节应答不携带任何卡状态。**

但有两点是确实成立的：

* `0xFF` **完全没有应答**，并且会让编程器卡死直到物理重插。固件确实对子操作码做了范围检查。
* `0x7C` 和 `0x7E` 有应答，说明它们在该范围内——也就是说这个可接受范围超过 CMD31。
  只有超出范围的值才会被拒绝。

我们还做了一个读 RAM 后门测试（在 `CMD62 / 0x10210002` 前后读取同一段 16 KiB 区域），
结果没有变化——但这**不构成证据**：后门需要 CMD38 才能把数据放进缓冲区，而普通的大块读取走的是
CMD18。我们有意没有发送 CMD38——在后门未打开时它是**擦除**命令。

全程卡片未受影响：每次运行前后对全部 512 字节 extCSD 逐字节比较，结果完全一致。

---

## 3. 未解问题

**T48 的位流究竟会不会把 CMD60/CMD62 转发给卡片？**

* 所有迹象都指向“不会”：`Xgpro.exe` 中没有任何厂商命令字符串，eMMC 的全部流程都以
  FPGA 位流（`.alg`）的形式存在于编程器固件中。
* 但我们无法观测到任何信息可以证明或否定它。编程器在这一层不暴露卡片应答。

唯一能下定论的实验是在 eMMC 总线上接逻辑分析仪：发送 `0x46`（已知可用的命令）和 `0x7E`，
比较两者是否在 CLK/CMD/DAT0 上产生任何波形。我们正在搭建这个测试。

---

## 4. 我们需要你的帮助

如果你有 **UFPI** 或 **EasyJTAG**，以下任意一项都会非常有价值：

1. **你的工具能否发送带任意参数的 CMD62？**
   对一张三星 eMMC（KLMAG/KLMBG/KMDP 系列，eMMC 5.x）发送 `CMD62 0xEFAC62EC`，随后发送
   `CMD62 0x10210002`，并报告卡片的应答——R1 状态、错误码、超时。即使答案是“工具拒绝执行”
   也有价值。

2. **你工具里显示的 RPMB 密钥从哪里来？**
   EasyJTAG 能在某些卡上显示 RPMB 密钥。它是从卡上的启动区或识别元数据块读出的，
   还是在写入固件并重新识别之后从控制器读出的？只要描述菜单路径就够了。

3. **厂商命令路径的 USB 抓包。**
   Wireshark + USBPcap（Windows）或 `usbmon`（Linux），按编程器的 VID/PID 过滤，
   在你执行一次厂商功能或 RPMB 密钥功能时抓包。帧布局是我们猜不出来的部分。

4. **你的工具是否有 BootROM / Recovery / “解锁 eMMC” 模式？**
   它会发送什么？

请在 issue 中贴出你的结果，或发送抓包文件。卡片型号、工具版本和确切的菜单路径比文字描述更重要。

---

## 5. 安全提示（给复现者）

* **不要**扫描子操作码。按 `0x40 + CMD` 的映射，`0x40` 是 CMD0（GO_IDLE_STATE），
  `0x4F` 是 CMD15（GO_INACTIVE_STATE），`0x58` 是 CMD24（**写入**），
  `0x5C`/`0x5D` 是 CMD28/CMD29（**写保护**）。
* **不要**发送 `0xFF` 或 `0x40`–`0x7F` 之外的任何值：它会让编程器卡死，必须重插 USB 线。
* 在读 RAM 后门未打开时，`CMD38` 是擦除。绝不要把它当作探测手段。
* 每次实验前后都比较完整 extCSD；这是发现“有东西被写入”的最廉价方法。

---

## 6. 文件

* `SAMSUNG-VENDOR-CMD.md` — 厂商命令接口的完整记录，含实测数据（§5.1）
  以及 T48 能做与不能做的清单（德文）。
* `WEITERE-WEGE.md` — 我们正在推进的两条路线：eMMC 总线上的逻辑分析仪，
  以及替换 FPGA 位流（德文）。
* `AGENTS.md` — 给 AI 智能体与贡献者的工作说明：分析哪个二进制、搜索什么、如何开 issue。
  另有中文版 `AGENTS.zh.md`。
* `docs/ufpi-findings.md` — 我们已知的 UFPI 与 EasyJTAG 命令处理情况
  （另有[德文版](docs/ufpi-findings.de.md)与[中文版](docs/ufpi-findings.zh.md)）。
* `docs/sony-partitions.md` — 索尼 DTV 分区布局，以及为什么维修不需要 RPMB 密钥
  （另有[德文版](docs/sony-partitions.de.md)与[中文版](docs/sony-partitions.zh.md)）。
* `docs/t48-status.zh.md` — 完整状态记录：协议细节、已验证的写入/擦除测试、
  RPMB 帧层，以及已解析的 `.alg` 容器
  （另有[英文版](docs/t48-status.md)与[德文版](docs/t48-status.de.md)）。
* `docs/rpmb-key-findings.zh.md` — 我们收集到的全部关于**RPMB 密钥来源**的资料：
  两个工具视频、OP-TEE issue、我们的阴性结果，以及决定写入计划的 extCSD 数值。
  另有[英文版](docs/rpmb-key-findings.md)与[德文版](docs/rpmb-key-findings.de.md)。
* `scripts/` — 我们自己写的 T48 USB 协议驱动与探测脚本
  （`sub_op_probe.py`、`sub_op_timing.py`、`sub_op_capture.py`、`sub_op_stability.py`、
  `reply_width.py`、`vendor_forward_test.py`）。

本仓库不含任何 RPMB 密钥材料、设备序列号或凭据。其中没有这类内容可被找到。
