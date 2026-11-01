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

---

## 3. How these notes were produced

Static analysis of the vendor binaries: string search, opcode table recovery, disassembly
around command dispatch, and cross-reference walking. No dynamic analysis was performed,
because the tools were never run.

That is the main limitation: **every finding above is unverified.** Verification requires
either the hardware (Task C) or a second independent analysis of the same binary.
