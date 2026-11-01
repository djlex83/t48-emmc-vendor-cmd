[English](rpmb-key-findings.md) · [Deutsch](rpmb-key-findings.de.md) · **中文**

# RPMB 密钥 —— 两个视频与 OP-TEE issue 说了什么

**状态：第三方陈述，不是我们自己的实测。** 以下全部内容来自教程视频或公开 issue 跟踪器，
不是我们亲自跑过的硬件。放在这里是因为它决定了我们的搜索策略，不是因为它已被证实。

---

## 视频 1 —— UFI eMMC ToolBox，三星 moviNAND

* RPMB 密钥**位于控制器固件转储中**。`Read eMMC Fw` 把它读出来，显示的数值随后被填入
  `Enter RPMB Key`。对三星来说，这就是拿到明文密钥的途径 —— 与用户区无关。
* `Read eMMC Fw` 是**只读操作** —— 没有备份义务，没有写入风险。
* **计数器不能直接设定。** 它只能通过对旧 RPMB 分区执行 RPMB 帧写入来恢复。
* 计数器**不是启动关键**：视频中以计数器 0 也能启动。丢失的是旧的加密数据，不是设备。
* 原芯片保持不动，在第二张卡上做实验。这正是我们遵守的规则。

## 视频 2 —— 另一个盒子，手机维修

* 该盒子有 `Read RPMB Key`，**直接从完好的卡**上读取密钥（三星）。然后 `Write RPMB Key`
  写到一张空卡 → 状态 `Legacy write protection mode`，计数器 0。
* 之后卡片仍然报告 `Device not boot inbuilt` / `Partition configuration 0` /
  `User area invalid for boot`。这是与密钥**无关**的启动阻碍，完全位于 extCSD 分区配置中。
  只有修正这一点之后才进入 EDL 模式并继续刷机。
* 结论：只有密钥不够 —— `PARTITION_CONFIG` 必须与设备匹配，否则即使是正确配置的卡也无法启动。

## OP-TEE issue #4019

* 密钥**每颗 eMMC 唯一**，由 TEE 生成（`CFG_RPMB_WRITE_KEY=y` 是工厂构建选项，会把它一次性
  写入卡片）。之后 `tee_rpmb_init()` 检测到它已编程。
* 密钥**既不会被读回也不会被重新推导**；该 issue 没有把熔丝、OTP、HUK 或控制器固件列为来源。
* 文中描述的唯一暴露面：正常世界可以诱导安全世界覆盖它 —— 此时密钥会以明文通过总线。
* “once you have the RPMB key the security of RPMB is gone.”

## 这对我们的阴性结果意味着什么

我们自己的尝试一无所获：密钥既不在用户区转储中，也无法从 CID/CSD 推导 ——
**25,165,728 次 HMAC 校验无命中**。来源在这两者之外。三星在控制器固件区；联发科可能在
SoC/TEE 中，但这**尚未**证实。

上面两个来源指向同一方向：三星密钥是控制器侧的机密，而厂商提供的路径是对固件的读取
—— 不是用户区里的某个结构。

## 手头卡片的 extCSD（只读，从未写入）

| 字段 | 值 | 含义 |
|---|---|---|
| EXT_CSD_REV | 0x08 | eMMC 5.1 |
| SEC_COUNT | 30535680 | 15.63 GB = 0x3A3E00000（恰好覆盖 KD 转储） |
| BOOT_SIZE_MULT | 0x14 (20) | 每个启动分区 2560 KiB = 2.5 MiB |
| RPMB_SIZE_MULT | 0x1F (31) | RPMB 3968 KiB = 3.875 MiB |
| PART_SETTING_COMPLETED | 0x00 | 分区**未**被不可逆锁定 |
| PARTITION_CONFIG | 0x48 | BootEnable = **BOOT2**，Access = BOOT1 |
| BOOT_BUS_WIDTH | 0x00 | 1 bit，无高速启动 |
| BOOT_WP / WR_REL | 0x00 | 无启动区写保护标志 |

涉及：两张索尼 KD-49XD7005 和两张飞利浦 65PUS810212。它们只在 `0xFE`（卡固件版本）与
`0x10C`/`0x10D` 上不同 —— 出厂配置在所有卡上完全一致。

**对写入计划的结论：** 设备从 **BOOT2** 启动。因此必须写入 BOOT2（2.5 MiB），否则无论
RPMB 状态如何都无法启动。`PART_SETTING_COMPLETED` 保持为 `0` —— 置 `1` 是**不可逆**的，
且根据源卡的实际情况并不需要。
