[English](ufpi-findings.md) · [Deutsch](ufpi-findings.de.md) · **中文**

# UFPI 与 EasyJTAG —— 分析的入手点

整理自我们自己的逆向笔记（`EASYJTAG-HANDOFF.md` §9.11 与 §9.12），2026 年。
每一行都是**待验证的线索，不是可引用的结论**。以下内容没有一项在我们自己的硬件上得到确认
—— 我们并不拥有这两款工具。

---

## 1. UFPI

### 架构

UFPI 由主机通过 USB 驱动：PC 发送一个小的操作码字节，编程器固件在卡上执行对应操作。
因此若干卡级流程根本不会以主机命令帧的形式出现 —— 它们完全在编程器内部运行。

| 操作码（主机） | 含义 |
|---|---|
| `0x38` | 主机侧 CMD56 辅助函数；跳转到 `0xedf350` 附近的代码 |
| `0x3E / 0x00DECCEE` | 退出某个已解锁模式 |
| `0x93` | 写入 RPMB 密钥（在编程器固件内部） |
| `0x94` | RPMB 认证（在编程器固件内部） |
| `0x1BE / 0xEFAC62EC` | 解锁三元组的第一个元素 |
| `0x1BE / 0x0FAC0070` | 第二个元素 —— **注意：不是**三星的 `0x10210002` |

### 三元组的含义

```
0x1BE / 0xEFAC62EC      三星 CMD62 解锁码
0x1BE / 0x0FAC0070      一个我们尚未识别的第二解锁码
0x3E  / 0x00DECCEE      退出 CMD62
```

第一个与第三个与三星厂商 API 完全一致，中间那个不一致。它可能是 UFPI 专有的厂商码、
另一代解锁码，或另一条命令的参数 —— 这是 UFPI 二进制中目前最值得追查的未决点。

### CMD56

主机侧的 CMD56 辅助函数确实存在，用于 **“Micron Health Report”** 功能
（代码位于虚拟地址 `0xf48b40` 附近，参数 `0x11` 与 `0x21`）。CMD56 属于东芝/美光
系列的厂商接口，**不是**三星的 CMD60/62 路径。不要把两者混为一谈。

### 应先检查什么

1. `0x1BE` 是固定的两字节主机操作码，还是第二个字节承载 MMC 参数？
   这种成对格式暗示命令字被拆到两个字节中。
2. `0x0FAC0070` 做什么 —— 固件里哪个分支处理它？
3. 是否任何代码路径会构造 `CMD62 0xEFAC62EC` → `CMD62 0x10210002` 这一序列？
   按立即数搜索 `10210002`。如果它从未出现，UFPI 就无法打开读 RAM 后门，
   对 A1 的回答就是“否”。

---

## 2. EasyJTAG

### RPMB 密钥的显示

据报道，EasyJTAG 能在 **KMDP6001DB-B425** 上显示 RPMB 密钥，来源是 **`0x20000000`**
附近的启动识别元数据区，共 80 页，显示前会先校验密钥。那是**卡元数据**路径，
不是控制器路径。

如果属实，它就为这个卡型回答了 A2：密钥以可读形式存放在卡上，而不是从控制器取回。

### 这对本项目意味着什么

我们的目标是 KLMAG1JENB-B041（eMMC 5.1，16 GB）。该型号上是否存在相同的元数据区、
其中是否存有密钥，目前未知。贡献者可以做的两项检查：

1. `dump` LBA `0x100000` 附近的 USER 区（即字节偏移 `0x20000000`，按 512 字节扇区计），
   寻找一个结构化的 80 页块，内含一个可信的 32 字节密钥。
2. 检查 EasyJTAG 在提供 RPMB 标签页之前是否按卡型分支。若是，则该元数据路径很可能
   只存在于特定系列。

### 需要解决的对立说法

一个教程视频声称，RPMB 密钥在 **FFU 回写并重新识别之后**才出现在 RPMB 标签页，
并且在反复读取中保持不变。这更符合控制器状态变化（CMD60 固件激活），而不是静态
元数据块。两个来源，两种机制。A2 与 Task C 正是为澄清这一点设立的。

### 只有导出表是可读的（2026.11.03 实测）

`EasyAPI.dll`（9 841 664 B，sha256 `b6c109ad…ba9c360d`，PE32/x86）与 `EasyAPI2.dll`
（14 748 160 B）都加过壳：每个节区头都报大小 `0`，代码位于 `.vmp0` 节。Ghidra 12.1.4
导入该 DLL 并在 7 秒内完成自动分析，但**一个**具名函数都解析不出来——按 `Samsung` 搜索
函数返回空。函数体对我们是关闭的。加壳保留完好的是**导出表**，而导出名本身就是发现
（V1 共 106 个导出，V2 共 114 个）：

| 导出名 | 名称所表达的内容 |
|---|---|
| `eMMC_RPMB_Read`、`eMMC_RPMB_ReadCounter` | 读取 RPMB 数据，以及读取计数器 |
| `eMMC_SamsungBootTrickCMDInit` / `…CMDFinish` | 启动技巧是一个**两段式**操作 |
| `eMMC_SamsungBootRPMBChangeInit` / `…Finish` | 更改 boot/RPMB 关系，同样两段式 |
| `eMMC_SamsungDumpFirmware` | 从卡上读取*控制器*固件 |
| `eMMC_SamsungRemoveWriteProtection` | 去除写保护，一个调用 |
| `eMMC_SamsungVTU00MRepair` | 以该控制器系列命名的修复路径 |
| `eMMC_SamsungFactoryWriteCID`、`eMMC_SamsungFactoryWriteCSD`、`eMMC_WriteCSD`、`eMMC_extCSD_SingleItemWrite` | 改写标识与配置 |
| `eMMC_SamsungFactoryResetCMD`、`eMMC_FactoryResetCMD42`、`eMMC_OTPGetSize/GetStatus/Lock/Unlock`、`eMMC_JEDEC_HWPART_CONFIG`、`eMMC_Switch_Part`、`eMMC_LockUnlockPassword` | 维护面的其余部分 |
| `BoxSetDFUMode`、`BoxAESEncrypt`、`BoxAESDecrypt`、`BoxSECDecrypt`、`GetBoxFirmwareChar`、`SetBoxPinoutMode` | 盒子本身：DFU 模式、加密、引脚映射模式 |

仅凭名称即可得出两个结论。

1. **不存在 eMMC 密钥导出函数。** 两个 DLL 中唯一以 Key 命名的导出是 `UFS_SetRPMBKey`、
   `UFS_ProgramRPMBKey`、`UFS_CheckRPMBKey`——那是 UFS 命名域，不是 eMMC。此 API 能读
   RPMB 数据和 RPMB 计数器；它没有暴露任何编程或导出 eMMC 密钥的途径。
2. `eMMC_SamsungDumpFirmware` 证明该盒子上存在控制器固件的**读取**通路。这正是我们的 T48
   所缺的能力，也是敢于对卡做固件更新的前提（攻击树，节点 K）。

### 该工具的 694 份日志文件里有什么（2026.11.03 实测）

本地一份安装自带协议历史：`Logs/`，694 个文件，11 MB，工具版本 1.6.4.0 – 2.0.2.0，
2021 年 4 月至 2023 年 4 月。统计结果，标识符与十六进制串已有意剔除：

| 观察 | 计数 |
|---|---|
| RPMB 判定行 | 800 |
| … 计数器 = 0，判定 `Clean` | 244 |
| … 计数器 = 0，判定 `Maybe not clean` | 130 |
| … 计数器 > 0，判定 `Not Clean` | 426，无一例外 |
| 含 `identification` 的行 | **0** |
| 报告密钥的行 | **0** — `valid` 只出现在 GPT 头旁边 |
| 含 `key` 的行 | 全部是*固件包分区名* |

因此判定值纯粹是**已写块计数器**的函数，而 JEDEC 允许任何人在没有密钥的情况下读它：
`Response: Clean` 只意味着“计数器为 0"。

那些 `key` 行与 RPMB 无关。它们是手机固件包（`*.tar.md5`、`*.pit`）中的分区，从 lz4 解包
后作为普通用户区数据写入 ROM1：`keystorage`（512 KB，Raw）、`keydata`、`keyrefuge`、
`keystore`、`keymaster`、`omekeystore`，以及 `rpmbak`（512 KB，Raw）。一个名字直叫
**rpmbak** 的分区就是存放在用户区的 RPMB 备份。这是本项目里第一个让设备在完全不持有密钥
的情况下恢复 RPMB 内容的机制，而且可以在我们自己的主板上验证：在我们已有的分区表里搜索
这些名字。

### 这没有解决什么

主机日志只记录主机选择记录的内容。盒子固件对我们不可读（`emmc.dat`，65 536 B，高熵，
无向量表——加密），因此无法从主机侧排除未文档化的通路。我们能说的是：在这套工具自己
留下的 11 MB 日志里没有任何密钥读取，而 `RPMB key is VALID` 这一措辞在所有这些版本中
都不出现。Issue #4 依然成立，只是现在具体得多——点名询问 `eMMC_RPMB_Read` 与
`eMMC_SamsungBootTrickCMDInit/Finish`。

---

## 3. 这些笔记是如何产生的

对厂商二进制的静态分析：字符串搜索、操作码表恢复、命令分发器附近的汇编分析、
交叉引用追踪、导出表枚举，以及阅读一份安装留下的日志集。没有做动态分析，
因为这些工具从未被运行过。

这也是主要局限：**以上每一项从二进制得出的推论都未经证实。** 验证需要硬件（Task C），
或对同一二进制的第二次独立分析。标注为“实测"的章节是对我们磁盘上已有文件的计数——
可复现，但仍然不是硬件运行。
