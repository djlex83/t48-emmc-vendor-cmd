**English** · [Deutsch](README.de.md) · [中文](README.zh.md)

# Samsung eMMC vendor commands from a programmer — measurements and an open question

We are repairing a Sony TV by reading and rewriting the eMMC of its mainboard. Along the
way we tried to reach the Samsung eMMC vendor command API — the one that leads to the
controller's BootROM mode — from a consumer programmer (XGecu T48) on macOS, using a
Python USB driver we wrote ourselves.

This repository documents what we measured, what it does **not** prove, and what we would
need to close the gap. If you own an UFPI or an EasyJTAG, you may be able to answer the
question in ten minutes.

Scope: device repair and data recovery on our own hardware. Not DRM circumvention.
Details, authorization and legal posture: **[LEGAL.md](LEGAL.md)**.

---

## 1. Why this matters

The RPMB key of an eMMC is write-only by design (JEDEC): the controller holds it, HMAC-SHA-256
authenticates every RPMB frame, and no standard command returns it. Recent work
([arXiv 2511.22340](https://arxiv.org/abs/2511.22340)) bypasses the HMAC check with
electromagnetic fault injection — but that yields keyless *writes*, never the key itself.

The vendor API is a different road. [Oran Avraham's `i9300_emmc_toolbox`](https://github.com/oranav/i9300_emmc_toolbox)
(Galaxy S3, Samsung VTU00M, 2017) documents it in plain C:

| Step | Command | Argument |
|---|---|---|
| Enter BootROM recovery mode | CMD1 (SEND_OP_COND) | `0x69FF87A9` (a knock, not an OCR value) |
| Unlock CMD60 | CMD60 | `0xEFAC60FC` |
| Activate firmware slot | CMD60 | `0xABCD1280` + type |
| Start timer (returns a value) | CMD60 | `0xABCD1240` |
| Unlock CMD62 | CMD62 | `0xEFAC62EC` |
| Open read-RAM backdoor | CMD62 | `0x10210002` |
| Leave CMD62 | CMD62 | `0x00DECCEE` |

Once the read-RAM backdoor is open, the **normal block path is redirected to controller
RAM**: CMD35 (address) → CMD36 (length) → CMD38 (perform) → CMD17 (fetch one 512-byte block).
`dump_fw_bootrom.c` in that repository dumps the whole 128 KB controller firmware this way,
without any authentication, because the controller is no longer executing its own firmware.

Whether the RPMB key lives in that readable RAM is unknown. If it does, the key is a
side effect of the dump.

---

## 2. What we measured on the T48

The T48 speaks a proprietary USB protocol. For eMMC it has a command gate, top opcode `0x27`:

```
host  -> 27 <sub_op> 00 00 <arg32 LE>           (8 bytes, EP1 OUT)
device -> 27 00 10 00 00 09 <flags> 00          (8 bytes, EP1 IN)
```

Every supported sub-opcode follows the pattern `sub_op = 0x40 + CMD number`:

```
0x46 → CMD6    0x4C → CMD12   0x4D → CMD13   0x50 → CMD16
0x57 → CMD23   0x5C → CMD28   0x5D → CMD29
```

which would make CMD1 = `0x41`, CMD60 = `0x7C`, CMD62 = `0x7E`.

The reverse-engineering notes claimed `reply_buf[1] != 0` marks success. **That is wrong on
this firmware**: byte 1 is `0x00` for every reply, including commands that demonstrably work.
Byte 6 looked like a status byte at first, but it is not:

* `0x7E` answers identically for arguments `0`, `0xFFFFFFFF`, `0xEFAC62EC` and `0x00DECCEE`.
* `0x4C` answers identically for arguments `0` and `0xFFFFFFFF`.
* `0x41` returned `0x08` in one run and `0x00` in another, with the same argument.
* In an A/B alternation, the **first** packet after each change carried `0x08` and every
  following packet `0x00` — for every sub-opcode alike. `0x57` answered `0x48` when read
  after a 20 ms delay.

Those values (`0x00`, `0x08`, `0x40`, `0x48`) are transient bits. **The 8-byte reply carries
no card status.**

Two things are nevertheless solid:

* `0xFF` gets **no reply at all** and wedges the programmer until a physical replug. The
  firmware range-checks the sub-opcode.
* `0x7C` and `0x7E` do reply, so they lie inside that accepted range — which therefore
  extends past CMD31. Only values outside it are rejected.

A read-RAM backdoor test (read the same 16 KiB region before and after
`CMD62 / 0x10210002`) showed no change, but it is **not evidence**: the backdoor requires
CMD38 to stage the data, and a plain mass read goes through CMD18. We deliberately did not
send CMD38 — without an open backdoor it is an **erase** command.

The card stayed untouched throughout: a full 512-byte extCSD comparison before and after
every run showed no difference.

---

## 3. The open question

**Does the T48's bitstream forward CMD60/CMD62 to the card at all?**

* Everything suggests it does not: `Xgpro.exe` contains no vendor-command strings, and all
  eMMC flows live as FPGA bitstreams (`.alg`) in the programmer firmware.
* Nothing we can observe proves it either way. The programmer does not expose card
  responses at this layer.

The one experiment that settles it is a logic analyser on the eMMC bus: send `0x46` (a known
working command) and `0x7E`, and compare whether either produces traffic on CLK/CMD/DAT0.
We are setting that up.

---

## 4. What we need from you

If you own an **UFPI** or an **EasyJTAG**, any of these would help enormously:

1. **Can your tool send CMD62 with an arbitrary argument?**
   Send `CMD62 0xEFAC62EC` followed by `CMD62 0x10210002` to a Samsung eMMC
   (KLMAG/KLMBG/KMDP family, eMMC 5.x) and report what the card answers — R1 status, errors,
   timeouts. Even "the tool refuses" is a useful answer.

2. **Where does the RFID/RPMB key shown in your tool come from?**
   EasyJTAG displays an RPMB key on some cards. Is it read from a boot or identification
   metadata block on the card, or from the controller after a firmware write and re-detect?
   A description of the menu path is enough.

3. **USB capture of the vendor-command path.**
   Wireshark + USBPcap (Windows) or `usbmon` (Linux), filtered on the programmer's VID/PID,
   while you run the vendor or RPMB-key function once. The frame layout is what we cannot
   guess.

4. **Does your tool have a BootROM / Recovery / "unlock eMMC" mode?**
   What does it send?

Please open an issue with what you find, or send a capture. Card model, tool version and the
exact menu path matter more than prose.

---

## 5. Safety notes (for anyone reproducing)

* Do **not** sweep sub-opcodes. Under the `0x40 + CMD` mapping, `0x40` is CMD0
  (GO_IDLE_STATE), `0x4F` is CMD15 (GO_INACTIVE_STATE), `0x58` is CMD24 (**write**), and
  `0x5C`/`0x5D` are CMD28/CMD29 (**write protect**).
* Do **not** send `0xFF` or any value outside `0x40`–`0x7F`: it wedges the programmer until
  the USB cable is replugged.
* `CMD38` without an open read-RAM backdoor erases. Never use it as a probe.
* Always compare the full extCSD before and after an experiment; it is the cheapest way to
  notice that something was written.

---

## 6. Files

* `SAMSUNG-VENDOR-CMD.md` — the vendor API write-up, with the full measurement record (§5.1)
  and a list of what the T48 can and cannot do.
* `WEITERE-WEGE.md` — the two tracks we are pursuing: logic analyser on the eMMC bus, and
  replacing the FPGA bitstream.
* `AGENTS.md` — instructions for AI agents and contributors: which binary to analyse, what
  to search for, how to file an issue. Also available in Chinese (`AGENTS.zh.md`).
* `docs/ufpi-findings.md` — what we already know about UFPI and EasyJTAG command handling.
  Also in [German](docs/ufpi-findings.de.md) and [Chinese](docs/ufpi-findings.zh.md).
* `docs/sony-partitions.md` — the Sony DTV partition layout and why a repair needs no RPMB
  key. Also in [German](docs/sony-partitions.de.md) and
  [Chinese](docs/sony-partitions.zh.md).
* `docs/t48-status.md` — the complete status record: protocol details, the verified
  write/erase tests, the RPMB frame layer, and the decoded `.alg` container. Also in
  [German](docs/t48-status.de.md) and [Chinese](docs/t48-status.zh.md).
* `docs/rpmb-key-findings.md` — everything we gathered about *where the RPMB key comes
  from*: two tool videos and the OP-TEE issue, our negative result, and the extCSD facts
  that constrain the write plan. Also in [German](docs/rpmb-key-findings.de.md) and
  [Chinese](docs/rpmb-key-findings.zh.md).
* `docs/attack-tree.md` — the analysis plan as a tree: which branches are closed by
  measurement, which are still open, and the cheapest experiment that settles each one.
  This is also the checklist for contributors. Also in
  [German](docs/attack-tree.de.md) and [Chinese](docs/attack-tree.zh.md).
* `scripts/` — our Python driver for the T48 USB protocol and the probe scripts
  (`t48_mmc.py` is the driver: identify, CSD/extCSD, partitions, bulk read/write, RPMB
  frames, profile selection with `--voltage`/`--width`, `selftest`; plus `sub_op_probe.py`,
  `sub_op_timing.py`, `sub_op_capture.py`, `sub_op_stability.py`, `reply_width.py`,
  `vendor_forward_test.py`).

No RPMB key material, no device serial numbers and no credentials appear anywhere in this
repository. There is nothing of that kind to find in it.
