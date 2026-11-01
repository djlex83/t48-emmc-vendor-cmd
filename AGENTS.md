# AGENTS.md — instructions for AI agents and human contributors

This file tells an AI agent (or a human) exactly what to do in this repository: which
binary to analyse, what to search for, what counts as a finding, and how to report it back
so the analysis can continue.

Read `README.md` first. It states the question. This file states the work.

---

## 1. The question, in one sentence

**Do the Samsung eMMC vendor commands (CMD1 knock `0x69FF87A9`, CMD60 `0xEFAC60FC`,
CMD62 `0xEFAC62EC` / `0x10210002`) reach the card through a consumer programmer — and where
does the RPMB key that EasyJTAG displays actually come from?**

Two sub-questions:

* **A1 — Forwarding.** Can UFPI or EasyJTAG send CMD62 with an arbitrary argument? Is the
  command executed by the eMMC, or filtered by the programmer firmware?
* **A2 — Key source.** When EasyJTAG shows an RPMB key, is it read from a metadata block on
  the card (boot identification), or from the controller after a firmware write and
  re-detect?

Answering either one is progress. Answering both closes the project's main open item.

---

## 2. What is already known

Full notes are in `docs/ufpi-findings.md`. The short version:

* UFPI is host-driven over USB; its RPMB key write/authenticate functions run **inside the
  programmer firmware** (opcodes `0x93` / `0x94`), not as host command frames.
* A host-side CMD56 helper exists: opcode `0x38` dispatches to code near `0xedf350`.
  CMD56 is used for the "Micron Health Report", not for Samsung vendor commands.
* An unlock sequence exists in the UFPI binary as the triple
  `0x1BE / 0xEFAC62EC`, `0x1BE / 0x0FAC0070`, `0x3E / 0x00DECCEE`.
  Note the second magic: `0x0FAC0070`, not the Samsung `0x10210002`.
* EasyJTAG reportedly displays an RPMB key on KMDP6001DB-B425, read from boot
  identification metadata around `0x20000000` (80 pages), validated before display.
  We have not reproduced this on our own hardware.

Everything else in this repository is measurement we performed ourselves on an
XGecu T48. Our T48 driver is in `scripts/`.

---

## 3. Your task — pick one

### Task A — static analysis of the UFPI binary

Goal: find every code path that emits a CMD60 or CMD62 vendor command.

Concrete steps:

1. Obtain the UFPI binary (vendor installer, or an existing local copy). Do not redistribute
   it; analyse it.
2. Locate the command dispatcher: the host sends a small opcode byte over USB, the
   programmer translates it into MMC commands. Start from the known opcodes
   (`0x38`, `0x93`, `0x94`, `0x1BE`, `0x3E`) and walk the switch.
3. Search for the constants as **immediates**, not strings:
   `EFAC62EC`, `EFAC60FC`, `69FF87A9`, `10210002`, `10210001`, `00DECCEE`, `CBAD1160`,
   `ABCD1280`, `0FAC0070`.
   A match adjacent to a command index of 60 or 62 is a live vendor path.
4. For every hit, determine: which UI function calls it, which opcode carries it, and
   whether an argument is host-supplied or fixed in firmware.
5. Report the opcode → command word → argument-source mapping.

**Deliverable:** an issue titled `UFPI: vendor command path <opcode>`, containing the
disassembly excerpt, the calling function, and the answer to A1.

### Task B — static analysis of the EasyJTAG binary

Goal: find where the displayed RPMB key comes from.

Concrete steps:

1. Locate the RPMB-key display function (strings such as `RPMB`, `Key`, `KEY`, `CID`,
   `Boot Config`, `Boot1`, `Boot2` are useful starting points).
2. Walk backwards from the display to the value source. Two shapes are possible:
   * a block-read path (LBA-based, sector reads, `0x20000000` area) → metadata on the card;
   * a controller/RAM path (firmware activate, CMD62, backdoor) → controller RAM.
3. Check for a hash or validation step before display (EasyJTAG is reported to validate
   the key). Validation implies the value is *trusted to be correct*, which tells you it
   came from a known structure.
4. Report the byte offsets, the partition (USER / BOOT1 / BOOT2 / metadata area), and the
   read primitive used.

**Deliverable:** an issue titled `EasyJTAG: RPMB key source`, with the read path and the
card models the code branches on.

### Task C — capture from hardware you own

If you own UFPI or EasyJTAG and can run it:

1. Capture the USB traffic (Wireshark + USBPcap on Windows, `usbmon` on Linux) filtered on
   the programmer's VID/PID.
2. Run exactly one function: the RPMB-key display, or a vendor/unlock command if the tool
   exposes one.
3. Attach the capture (or a hex excerpt of the relevant frames) to an issue.
4. State the card model, the tool version and the menu path.

**A capture of a tool that refuses the command is as useful as one that succeeds.** We need
to know whether the tool ever sends it.

---

## 4. Method notes

* Work statically first. Hardware runs on a real card and can change its state.
* Never send an unknown command to a card to "see what happens". On this command family
  `CMD38` erases and `CMD28`/`CMD29` set or clear write protection.
* If you must probe, compare the **full 512-byte extCSD** before and after. It is the
  cheapest detector for an unintended write.
* Our T48 findings are in `README.md` §2 and `SAMSUNG-VENDOR-CMD.md` §5.1. Read them before
  repeating anything: several obvious experiments are already known to be inconclusive.
  In particular, a plain region re-read cannot detect the read-RAM backdoor, because the
  backdoor requires CMD38 to stage the data.

---

## 5. Issue format

Every finding goes into an issue. Use this shape:

```
Title: UFPI|EasyJTAG: <what you found>

## Question addressed
A1 (forwarding) / A2 (key source) / other

## Evidence
- Binary: version, build, size
- Address / function: 0x…, name if recovered
- Excerpt: minimal disassembly or hex, with surrounding context
- Card model and tool version, if from hardware

## What it means
One paragraph. State confidence: confirmed / probable / speculative.

## What it does not prove
Be explicit. This repository has already been burned once by a plausible-looking
signal that turned out to be noise.
```

Do not open one issue per address. Group by finding.

**Do not attach:** RPMB key material, device serial numbers, licence files, credentials, or
the vendor binary itself. Describe, do not distribute.

---

## 6. What we are not doing

* No DRM circumvention. This is device repair.
* No mass exploitation of other people's cards.
* No redistribution of vendor tools or extracted firmware images.

If a step would require any of these, stop and open an issue instead.
