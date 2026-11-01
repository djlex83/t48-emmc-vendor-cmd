[English](t48-status.md) · [Deutsch](t48-status.de.md) · [中文](t48-status.zh.md)

# T48 / eMMC — status record

Everything here was established from our own USB captures and card reads unless it is
explicitly marked as an assumption. Device serial data (raw CID) has been removed; the
card model and the die revision are kept because they are not identifying on their own.

---

## 1. Card

| Field | Value |
|---|---|
| Model | Samsung **KLMAG1JENB-B041**, 16 GB, eMMC 5.1 |
| MID / PNM | 0x15 (Samsung) / **…JNB4R**, production date 5-2017 |
| EXT_CSD_REV | 8 (MMC 5.1) |
| USER | 14 910 MB, SEC_COUNT 0x01D1F000 = 30 535 680 blocks |
| BOOT1 / BOOT2 / RPMB | 4 MB each |
| RPMB | protected by an authentication key, writer counter 331 524 |
| PARTITION_CONFIG (EXT_CSD[179]) | 0x00 after our byte write (was 0x78, left behind by an earlier tool run) |

`PARTITION_CONFIG` was set to `0x00` (access = USER, boot-enable off) with a CMD6 byte
write (`27 46 00 00 00 00 b3 03`) during the area probe. That state is correct for
installing the card. Note that other cards we read later showed `0x48`; the values are
from different cards and different moments — see `rpmb-key-findings.md`.

## 2. What happened to the card

* `BOOT1.BIN` and `BOOT2.BIN` (4 MB each) were written back, 2 × 4 MB, error-free,
  followed by an 8 MB read-back check.
* **User area saved and empty:** a full read through our own driver, 15 634 268 160 bytes,
  at ~11.8 MB/s. `find_metadata.py` found **0 occupied 4-KiB blocks**, no CID / VCT0 /
  RPMB hits — the entire user area of this die is zero.
* Consequence for the RPMB key: on **this** die there is no Samsung metadata block, so
  no key in the user area. The metadata route (a different card, KMDP6001DB-B425) does
  not apply here.

### 2.1 The second card in the socket ("JTD4R")

* Same capacity and revision, `PARTITION_CONFIG` 0x00.
* User area **with real data**: LBA 0 is an ARM boot vector (`71 00 00 ea …`), partitions
  from 0x40000, 0xFF fill at 0x100000, code from 0x800000. MediaTek DRM strings such as
  `MTDRM_RPMBLoadMacKey` appear in the image.
* Metadata search **negative**: no CID in any byte order, no "Boot Identification". The
  `VCT0` and `RPMB` hits sit in payload data (Base64 strings, the MTK DRM library).
* **No MBR / GPT / PGPT:** LBA 0 is already a bootloader (`MTK/DTV/ROMCODE/MSDCBOOT`).
  The layout comes from the loader, not from a partition table.
* Platform: MediaTek DTV, strings "Preloader T8032", "PH7M_EU_5596", build date
  Nov 8 2021.
* The MTK DRM library loads the key **over RPMB** (`MTDRM_RPMBLoadMacKey`); it is not
  stored in the image. So the device image does not yield a key either.

## 3. T48 USB protocol (from the captures)

Frames: commands `OUT 0x01` → reply `IN 0x81`; payload `OUT 0x02` / `IN 0x82`.

**Initialisation:** `00` (info, ×2) · `24 f0` / `24 e0` / `24 f1` (session) · `3e 01` ·
`03` (64 B, BEGIN_TRANS) · `39` (status) · `21` (capabilities) · `05` CID · `06` CSD ·
`08 48 00 02` extCSD · `04` END_TRANS.

**extCSD reply:** 528 bytes = 8 header + 512 extCSD + 8 status; `extCSD[i] = buf[i+8]`,
checked against EXT_CSD[162]=01, [179]=0x48, [192]=8, [212..215]=0x01D1F000.

**Single block read** (verified from the capture):

```
27 46 00 00 00 03 b3 01             pipe setup
14 00 00 00 00 00 00 00 01 00 00 02 addressing (block count 1)
OUT 512 B on pipe 0x02              control buffer: zeros, token at 484–499,
                                    byte 511 = 0x02
15 00 00 02 00 00 00 00 01 00 00 02 read
IN 0x82 (max 520) → 528 bytes       16-byte header + 512-byte frame
```

**Token chain:** the host generates 16 random bytes per session and must echo back the 16
bytes the programmer returned last in every further request. Without that echo the
programmer firmware waits and hangs; only physical replugging helps.

**Mass stream:** 40-byte descriptor, opcode **`0d` = read**, **`1f` = write**:

| Offset | Value | Meaning |
|---|---|---|
| +0 | 0x0d | opcode, read |
| +1 | 1 | block mode (LBA in 512-byte blocks) |
| +4 | LBA | **start address** (`(byte_addr>>9) \| (high<<23)`) |
| +8 | 512 | block size |
| +12 | 32 | blocks per 16-KiB frame |
| +16 | frame count | 16400-byte frames in the stream |
| +20 | 32 | address step per frame |
| +24 | 32 | blocks per frame |
| +28 | 1 / 4 | read / write |
| +32 | 1 | constant, set in the eMMC init path |

- A dump reads **16400 bytes from pipe 0x82**. The 0x10040 variant on pipe 0x81 is the
  blank-check path, not the dump.
- A frame is accepted only if `frame[0] & 0x7FFFFFFF == 0`; otherwise the vendor tool
  aborts with "Error code / Status reg".
- Our earlier hand-built descriptor always put 0 at +4. That is fixed in the driver
  (`mass_descriptor(start_lba, frames)`).

**Write path** (reconstructed from the vendor binary, verified on the device):

- Descriptor `1f 01 …`, +28 = 4, other fields as for read.
- Frames of 16400 bytes: header byte 0, +4 running LBA (step 32 blocks), +8 = 512,
  +12 = 32, from +16 the 16 KiB.
- After each full 1-MB block the **first frame of the next group** (frame 64, 128, …)
  carries header byte **2**; after that frame the host reads 64 bytes from `0x81` and
  treats byte 0 as an error code.
- Completion: send STATUS `0x39`, read 32 bytes from `0x81`. Byte 0 = 0x02 means
  "EMMC Running TimeOut"; otherwise u16@+2 / u32@+4 form the error text.
- Abort/failure: send a frame with header byte **1**, then the same completion.

**Erase (opcode 0x0e):** 16-byte command, byte 0 = `0e`, bytes 4–7 = start LBA, bytes
8–11 = **inclusive** end LBA. Reply: 8 bytes from `0x81`, byte 1 = error code. Before
each block the vendor tool checks card status via CMD13 (`0x4c`) and polls until the
range is no longer busy.

Write and erase were **verified on the device** (BOOT1, blank):

| Test | Result |
|---|---|
| write 1 MB (64 frames) | 1 048 576 bytes read back, **0 differences** |
| write 4 MB (256 frames, 3 × 1-MB acknowledgement) | 4 194 304 bytes, **0 differences**, frame 64 correct |
| erase 2048 blocks (1 MB) | read-back probe: 0 non-zero bytes |
| erase 8192 blocks (4 MB) | read-back probe: 0 non-zero bytes |

Still locked behind `T48_ALLOW_WRITE=1` so that no script writes by accident.

### 3.2 Partition access

Area selection goes through the PARTITION_ACCESS bits in EXT_CSD[179]:
`27 46 00 00 00 <value> <index> <access>`, access 1 = set bits, 2 = clear bits,
3 = write byte.

| Area | Command sequence |
|---|---|
| USER | `27 46 00 00 00 07 b3 02` (clear bits 0..2) |
| BOOT1 | `… 07 b3 02`, then `27 46 00 00 00 01 b3 01` |
| BOOT2 | `… 07 b3 02`, then `27 46 00 00 00 02 b3 01` |
| RPMB | `… 07 b3 02`, then `27 46 00 00 00 03 b3 01` |

**Correction:** an earlier driver version only set the bits without clearing first. With
an active boot partition the access bits stayed unchanged — a "USER" read could in truth
read BOOT1. `setup_area()` now clears first.

### 3.3 RPMB area returns error frames

Every 512-byte block of an area-3 read ends with `00 01 00 00` at offset 508. That is the
RPMB result field **0x0001 = General Failure**: unauthenticated reads return the same
error frame in every 16-KiB block, which is why all area-3 dumps look identical. It is
not an addressing error.

Cross-check inside the vendor tool: both RPMB read paths build the same request —
type 4 (authenticated read), nonce set, but **MAC bytes zero**. So the tool reads RPMB
unauthenticated, and on a card with a key 0x0001 is inevitable. The only path that uses
a key is the "program key" path (type 1) — that **sets** a key, it does not read one.
No key read exists in that software.

### 3.4 RPMB frame layer in the driver (verified on the device)

The 528-byte reply of the 14/15 path is **16-byte header + 512-byte RPMB frame**. Our
earlier note "500 bytes of data + 16-byte token" was wrong: the observed "token echo" at
byte 500 is the JEDEC nonce field.

| Offset | Field | Length |
|---|---|---|
| 0–195 | stuff (zeros) | 196 |
| 196–227 | MAC | 32 |
| 228–483 | data | 256 |
| 484–499 | nonce (returned) | 16 |
| 500–503 | write counter (reply only) | 4 |
| 504–505 | address | 2 |
| 506–507 | block count | 2 |
| 508–509 | result | 2 |
| 510–511 | request/response type | 2 |

Big-endian — **except one measured quirk**: the type field comes back byte-swapped
(type 2 → `02 00`), so `rpmb_parse()` reports both `type` and `type_be`.

Measured:

| Request | Result |
|---|---|
| type 2 counter | result 0x0000, counter **33 638** (0x00008366), nonce returned correctly |
| type 4 read, address 0, MAC = 0 | result **0x0001**, rest of frame empty, nonce **not** returned |
| header byte 5 | 0x09 observed; meaning still unknown |

CLI: `t48_mmc.py rpmb counter` · `rpmb read <addr> [blocks]` · `rpmb result`. Because of
the one-read-per-session rule: **one RPMB request per process run**. A type-3 write path
is deliberately not implemented — it needs the key we do not have.

## 4. Firmware update (FFU) — ruled out for the T48

* The vendor software contains **no** strings for FFU, `EFAC60FC`/`CBAD1160`, CMD60/CMD62
  or vendor commands. "Reflash firmware" refers to the programmer's own firmware.
* The `cmp r12b, 8` path and the CMD60 magic exist only in the UFPI dongle code.
* **The T48 cannot update eMMC firmware.** A matching image exists, but it cannot be
  loaded through this programmer.

### 4.1 The reference FFU flow (from EasyJTAG/UFPI, for a vendor tool later)

Preconditions: `EXT_CSD_REV` (byte 192) = 8, and a **controller firmware image** for an
equivalent card (not the device ROM).

1. **Unlock:** CMD60 `0xEFAC60FC`, then CMD60 `0xCBAD1160`.
2. **Optional erase:** CMD35 arg 0 → CMD36 arg 0 → CMD38, timeout 120 s.
3. **Write:** CMD23 with the size in sectors → CMD25 over the whole range; then wait.
4. **Verify:** CMD23 → CMD18 reads everything back, block-wise `memcmp`.
5. **Reset:** CMD0 with the stored argument, wait 15 s, then reinit at 1 bit.

**Risk, read before any attempt:**

* Step 2 erases with **group index 0**. If the FFU unlock (step 1) did not take, that
  lands in the **user area** — the riskiest operation in this whole project. Only with a
  full backup, only on a disposable card.
* An FFU needs controller firmware **from an equivalent card**, not the Android/Tizen
  ROM. For our 16-GB card there is **no exact match** in the available database; only a
  32-GB variant exists. Do not use it untested.

**Relation to the RPMB key:** an FFU writes controller firmware; it **does not read a
key**. "Program new key" works only while RPMB is **still unprogrammed** (counter 0).
Our card's counter is 33 638, so RPMB is programmed; a new key cannot be chosen freely
there, and "reset RPMB" would destroy the RPMB content. Whether an FFU resets the RPMB
state itself is **not established** — do not rely on it.

## 4a. Algorithm files (`.alg`) — container decoded

Inventory: 354 files, families `EMMC_41_18` … `EMMC_54_33`, `NAND_xx`, `SPI25Fxx`,
`28F32Pxx`, `TTL1` and others. **No `.alg` file is published here.**

| Offset | Content |
|---|---|
| 0x000 | 32-byte ASCII name ("EMMC211210", "EMMC", …) |
| 0x020 | 256-byte description (empty in all files we have) |
| 0x120 | 4 DWORD header values (all 0 here) |
| 0x130–0x21F | zero fill |
| 0x220 | DWORD **0x0005327C**, identical in all 354 files |
| 0x224 | DWORD **checksum**, little-endian |
| 0x228 | 16 bytes of `FF` |
| 0x238 | magic `99 55 66 AA`, then payload |

**Checksum (solved, 354/354 files match):** reflected CRC-32, poly `0xEDB88320`, init
`0xFFFFFFFF`, **without final XOR** ("JAMCRC") over all bytes **from 0x228 to EOF**.
In Python: `(zlib.crc32(d[0x228:]) ^ 0xFFFFFFFF) & 0xFFFFFFFF`.

**Loading and upload:** the loader accepts files up to **98 336 bytes** of payload, reads
from 0x220 into a static buffer, then sends 8 bytes `{0x26, 0x00, 0x00, 0x00, <length>}`
on **EP 0x01 OUT**, waits 100 ms and sends the buffer from 0x220. The `.alg` is
**transferred unchanged to the programmer and executed there**. The file name is a
family prefix (`EMMC_`, `NAND_`, `VGA_`, …) + chip index in hex + `_33`/`_18` for eMMC.

**Payload:** a 16-bit little-endian word stream, ~22 % zero words; the first 32 bytes are
identical across **all** families (a shared prologue). We searched all 354 files for the
byte patterns of the FFU constants: **0 hits**. The eMMC `.alg` files are programmer
code, not an MMC command stream.

**Not needed for our driver:** read/write/erase run through the built-in firmware
descriptors (`0d`/`1f`/`0e`). The vendor tool loads the `.alg` in addition because the
programmer executes chip-specific routines from it.

## 5. Next steps

Done on the device: address field verified; full user-area backup (all zeros);
`PARTITION_CONFIG` reset; write and erase verified byte-identical; second card backed up
and analysed offline; RPMB frame layer built and measured; `.alg` container decoded.

Driver test series: `py_compile` clean, `selftest` 25 checks / 0 errors; `read` 1 frame;
`dump --resume` fills only the missing frame; `verify` reports 0 differing blocks and rc 5
with the exact off-byte on a flipped byte; write/erase refuse without `T48_ALLOW_WRITE=1`;
argument errors return rc 2.

**Open:**

1. **RPMB key:** not obtainable through the user area on this die. What remains is the
   vendor side — an EasyJTAG box with the Samsung boot trick, or UFPI (`0x93`), both
   Windows plus hardware we do not own. The T48 demonstrably cannot read it.
2. **FFU:** the reference flow is documented (§4.1). Execution needs EasyJTAG/UFPI and a
   matching controller firmware image; there is no exact match for our 16-GB card.
3. **Forwarding:** whether the T48 bitstream passes CMD60/CMD62 at all is still unproven —
   see `../WEITERE-WEGE.md` and issue #1.
