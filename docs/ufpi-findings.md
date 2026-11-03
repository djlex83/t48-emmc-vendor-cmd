[English](ufpi-findings.md) · [Deutsch](ufpi-findings.de.md) · [中文](ufpi-findings.zh.md)

# UFPI and EasyJTAG — starting points for analysis

Condensed from our own reverse-engineering notes (`EASYJTAG-HANDOFF.md` §9.11 and §9.12),
2026. Treat every line as **a lead to verify, not a fact to quote**. Nothing here was
confirmed on our hardware — we own neither tool.

---

## 1. UFPI

### Architecture

UFPI is host-driven over USB: the PC sends a small opcode byte, the programmer firmware
executes the corresponding operation on the card. Several card-level flows therefore never
appear as host command frames — they run entirely inside the programmer.

| Opcode (host) | Meaning |
|---|---|
| `0x38` | host-side CMD56 helper; dispatches to code near `0xedf350` |
| `0x3E / 0x00DECCEE` | exits an unlocked mode |
| `0x93` | RPMB key write (inside programmer firmware) |
| `0x94` | RPMB authenticate (inside programmer firmware) |
| `0x1BE / 0xEFAC62EC` | first element of an unlock triple |
| `0x1BE / 0x0FAC0070` | second element — **note: not** the Samsung `0x10210002` |

### What the triples mean

```
0x1BE / 0xEFAC62EC      Samsung CMD62 unlock magic
0x1BE / 0x0FAC0070      a second magic we have not identified
0x3E  / 0x00DECCEE      leave CMD62
```

The first and third match the Samsung vendor API exactly. The middle one does not. It may be
a UFPI-specific vendor code, a different generation of the magic, or an argument to a
different command — this is the single most interesting open item in the UFPI binary.

### CMD56

The host-side CMD56 helper exists and is used for the **"Micron Health Report"** function
(code near virtual address `0xf48b40`, arguments `0x11` and `0x21`). CMD56 is a Toshiba/Micron
-family vendor interface and is **not** the Samsung CMD60/62 path. Do not conflate them.

### What to check first

1. Is `0x1BE` a fixed two-byte host opcode, or does the second byte carry the MMC argument?
   The pair format suggests a command word split across two bytes.
2. What does `0x0FAC0070` do — which branch of the firmware handles it?
3. Does any code path build the sequence `CMD62 0xEFAC62EC` → `CMD62 0x10210002`?
   Search for `10210002` as an immediate. If it never appears, UFPI cannot open the read-RAM
   backdoor and the answer to A1 is "no".

---

## 2. EasyJTAG

### RPMB key display

EasyJTAG reportedly displays an RPMB key on **KMDP6001DB-B425**, read from the boot
identification metadata area around **`0x20000000`**, 80 pages, with the key validated
before display. That is a **card-metadata** path, not a controller path.

If that holds, it answers A2 for that card model: the key is stored readable on the card,
not recovered from the controller.

### Why this matters for our project

Our target is KLMAG1JENB-B041 (eMMC 5.1, 16 GB). Whether the same metadata area exists and
holds a key on that model is unknown. Two checks a contributor can run:

1. `dump` the USER area around LBA `0x100000` (the `0x20000000` byte offset, at 512-byte
   sectors) and look for a structured 80-page block with a plausible 32-byte key.
2. Check whether EasyJTAG branches on card model before offering the RPMB tab. If it does,
   the metadata path likely exists only on specific families.

### Open contradiction to resolve

A tutorial video claims the RPMB key appears in the RPMB tab **after an FFU write-back and a
re-detect**, and stays identical across repeated reads. That is consistent with a controller
state change (CMD60 firmware activation) rather than a static metadata block. Two sources,
two mechanisms. Resolving this is exactly what issues A2 and Task C are for.

### The export table is the only readable part (measured 3.11.2026)

`EasyAPI.dll` (9 841 664 B, sha256 `b6c109ad…ba9c360d`, PE32/x86) and `EasyAPI2.dll`
(14 748 160 B) are packed: every section header reports size `0` and the code lives in a
`.vmp0` section. Ghidra 12.1.4 imports the DLL and finishes auto-analysis in 7 s, but
resolves **zero** procedures by name — searching procedures for `Samsung` returns nothing.
The bodies are closed to us. What packing leaves intact is the **export table**, and the
export names are themselves the finding (106 exports in V1, 114 in V2):

| Export | What the name says |
|---|---|
| `eMMC_RPMB_Read`, `eMMC_RPMB_ReadCounter` | RPMB data read, and counter read |
| `eMMC_SamsungBootTrickCMDInit` / `…CMDFinish` | the boot trick as a **two-stage** operation |
| `eMMC_SamsungBootRPMBChangeInit` / `…Finish` | changing the boot/RPMB relation, also two-stage |
| `eMMC_SamsungDumpFirmware` | reading the *controller* firmware off the card |
| `eMMC_SamsungRemoveWriteProtection` | write-protect removal as a single call |
| `eMMC_SamsungVTU00MRepair` | a repair path named for exactly this controller family |
| `eMMC_SamsungFactoryWriteCID`, `eMMC_SamsungFactoryWriteCSD`, `eMMC_WriteCSD`, `eMMC_extCSD_SingleItemWrite` | identity and configuration rewriting |
| `eMMC_SamsungFactoryResetCMD`, `eMMC_FactoryResetCMD42`, `eMMC_OTPGetSize/GetStatus/Lock/Unlock`, `eMMC_JEDEC_HWPART_CONFIG`, `eMMC_Switch_Part`, `eMMC_LockUnlockPassword` | the rest of the maintenance surface |
| `BoxSetDFUMode`, `BoxAESEncrypt`, `BoxAESDecrypt`, `BoxSECDecrypt`, `GetBoxFirmwareChar`, `SetBoxPinoutMode` | the box itself: DFU mode, crypto, pinout modes |

Two conclusions follow from the names alone.

1. **There is no eMMC key export.** The only key-named exports in either DLL are
   `UFS_SetRPMBKey`, `UFS_ProgramRPMBKey`, `UFS_CheckRPMBKey` — the UFS namespace, not eMMC.
   This API can read RPMB data and the RPMB counter; it exposes no way to program or export
   an eMMC key.
2. `eMMC_SamsungDumpFirmware` proves that a controller-firmware **read** path exists on this
   box. That is precisely the primitive our T48 lacks, and it is the precondition for doing a
   card firmware update at all (attack tree, node K).

### What 694 log files of this tool contain (measured 3.11.2026)

A local installation carries its own protocol history: `Logs/`, 694 files, 11 MB, tool
versions 1.6.4.0 – 2.0.2.0, April 2021 – April 2023. Counted, with identifiers and hex runs
left out on purpose:

| observation | count |
|---|---|
| RPMB verdict lines | 800 |
| … with counter = 0, verdict `Clean` | 244 |
| … with counter = 0, verdict `Maybe not clean` | 130 |
| … with counter > 0, verdict `Not Clean` | 426, no exception |
| lines containing `identification` | **0** |
| lines reporting a key | **0** — `valid` occurs only next to GPT headers |
| lines containing `key` | every one of them is a *firmware-package partition name* |

So the verdict is a pure function of the **written-word counter**, which JEDEC lets anyone
read without a key: `Response: Clean` means "counter 0" and nothing more.

The `key` lines are not RPMB at all. They are partitions of a phone firmware package
(`*.tar.md5`, `*.pit`), unpacked from lz4 and written to ROM1 as ordinary user-area data —
`keystorage` (512 KB, Raw), `keydata`, `keyrefuge`, `keystore`, `keymaster`, `omekeystore`,
and `rpmbak` (512 KB, Raw). A partition literally named **rpmbak** is an RPMB backup kept in
the user area. That is the first mechanism in this whole project that would let a device
restore RPMB content without ever holding a key, and it is checkable on our own boards:
search the partition tables we have for those names.

### What this does not settle

A host log records what the host chose to write down. The box firmware is not readable to us
(`emmc.dat`, 65 536 B, high entropy, no vector table — encrypted), so an undocumented path
cannot be ruled out from the host side. What we can say is this: in 11 MB of this tool's own
history there is no key read, and the wording `RPMB key is VALID` does not occur in any of
these versions. Issue #4 still stands, and it is now much sharper — ask about
`eMMC_RPMB_Read` and `eMMC_SamsungBootTrickCMDInit/Finish` by name.

---

## 3. How these notes were produced

Static analysis of the vendor binaries: string search, opcode table recovery, disassembly
around command dispatch, cross-reference walking, export-table enumeration, and the reading
of a log corpus that the installation left behind. No dynamic analysis was performed, because
the tools were never run.

That is the main limitation: **every inference from the binaries is unverified.** Verification
requires either the hardware (Task C) or a second independent analysis of the same binary.
The sections marked "measured" are counts over files already on our disk — reproducible, but
still not a hardware run.
