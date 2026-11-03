[English](attack-tree.md) · [Deutsch](attack-tree.de.md) · [中文](attack-tree.zh.md)

# Attack tree: where could the RPMB key come from?

An analysis plan in the order of test cost, with one honest status line per node.
It is also the checklist contributors can work from: each open node names the single
cheapest experiment that would settle it.

Dates and measurements: 2026-10/11. Our own measurements are marked **[we]**, third-party
claims we could not reproduce are marked **[3rd]**, and a node we merely found plausible is
marked **[open]**.

Scope reminder: our own hardware, device repair, no DRM circumvention, no key material or
serial numbers in this repository. See [LEGAL.md](../LEGAL.md).

---

## 0. The goal, stated honestly

We want to *repair boards*, and the RPMB key matters for exactly one sub-goal: authenticated
writes to the RPMB partition. Everything else on these boards works without it — that is the
finding in [sony-partitions.md](sony-partitions.md).

So the tree has two roots, and they are not the same question:

| Root | Question | Status |
|---|---|---|
| **R1** | Can we obtain the RPMB key of a given card? | one card yes **[3rd-confirmed]**, our two 16 GB cards no |
| **R2** | Do we need it for the repair? | **no** for every step we have measured so far |

For R1 we already have a positive data point: one card's key was obtained through a commercial
box and verified cryptographically (the derived MAC matched). That result stands, but it did not
come from the T48 and we cannot reproduce that path with the hardware we own.

---

## 1. The tree

```
R1  Obtain the RPMB key of a specific card
│
├── A  Card-embedded boot identification metadata          [3rd] + [we: negative]
│      Claims: metadata region at 0x20000000, 80 pages, holds CID,
│      write counter and the 32-byte key. Tool log: "RPMB key is VALID".
│      Our test: searched both 16 GB cards end to end — no metadata block,
│      no CID in any byte order, no "Boot Identification" string.
│      Verdict: path exists on some Samsung dies, is absent on ours.
│      A second, much larger negative: in 694 EasyJTAG log files already
│      on our table (11 MB, v1.6.4–2.0.2) the word identification occurs
│      in 0 lines and a key in 0 lines — see ufpi-findings.md.
│
├── B  Controller RAM via the vendor command API            [open]  ← the live branch
│      BootROM knock (CMD1 0x69FF87A9), CMD60/CMD62 unlocks,
│      read-RAM backdoor (CMD62 0x10210002), then CMD35/36/38/17.
│      Documented for VTU00M by oranav (GPLv3, linked not copied).
│      The primitive does exist somewhere: EasyJTAG exports
│      eMMC_SamsungBootTrickCMDInit/Finish — a named, two-stage vendor trick.
│      Our blocker: we cannot see whether the T48 bitstream forwards
│      CMD60/CMD62 at all — the programmer hides card responses.
│      → this is issue #1 and the logic-analyser measurement series.
│
├── C  Read it out of the RPMB partition                    [we: closed]
│      Raw reads of the RPMB area return Result 0x0001 (general failure);
│      16384 B read, 99.8 % zeros, the only non-zero bytes are the result
│      field. Proved on the device, twice. Closed.
│
├── D  Recover it from the host software or an image        [we: closed]
│      Full user-area backup analysed offline: the MediaTek DRM library
│      names MTDRM_RPMBLoadMacKey — the key is loaded *through* RPMB,
│      never stored in the image. Entropy check on the region that holds
│      the DRM strings: no 32-byte random block anywhere. Closed.
│
├── E  Brute force / search                                 [we: closed]
│      25,165,728 candidate keys tested against a known-good frame:
│      zero hits. HMAC-SHA-256 over a 256-bit key is not searchable. Closed.
│
├── F  Bypass the check instead of the key (EMFI)           [3rd]  out of scope for us
│      Published result (keyless writes, both read and write). Needs a
│      glitch coil and pulse generator. No soldering in this project, and
│      it does not yield a key anyway. Not our path.
│
└── G  Ask people who own the tooling                       [open]  ← the cheap branch
       UFPI / EasyJTAG owners: issues #3 (do vendor commands reach the
       card?) and #4 (where does the displayed key come from?).
       Zero cost to us, and one answer settles more than our own week.
```

The repair root, in parallel:

```
R2  Repair the board
│
├── H  Boot chain without RPMB                              [we: open]
│      Verified: write and erase paths byte-identical, extCSD readable,
│      partition access switchable. No step measured so far needs the key.
│
├── I  Fresh card provisioning                              [open]
│      Does the TV write the key itself when the counter is 0? The vendor
│      command API cannot be used to check this on the T48, but a stick
│      update test on the TV answers it directly.
│
├── J  "Remove write protection" as its own problem         [3rd]
│      Reported mechanism: rewrite CSD — clear bits 12/13 of CSD byte 14,
│      recompute CRC7, CMD16 16 → CMD27, preceded by firmware-unlock
│      opcodes that our T48 does not implement. Separate subtree, and
│      potentially destructive: needs a full backup first.
│
└── K  Firmware update of the card itself (FFU)             [we: measured, gated by B]
       The *card* is willing: in a local collection of 587 extCSD dumps,
       531 report EXT_CSD[308] = 1 (FFU_FEATURE_SUPPORT), and all nine
       dumps of our AJTD4R variant do, FW_REV 02.00. The blocker is the
       transport: the documented flow opens with CMD60 0xEFAC60FC, and the
       answer to node B decides whether any programmer can reach it.
       And the undo step has a name on the peer tool: eMMC_SamsungDumpFirmware
       reads the controller firmware off the card. The T48 has no equivalent,
       and that gap — not the card — is why we stay away from FFU.
```

---

## 2. Node detail, ordered by how cheaply each can be settled

### B — controller RAM (the only branch that still leads to a key on our cards)

Everything in this branch waits on one binary fact: **does a `0x27` packet with sub-opcode
`0x7E` put a waveform on the eMMC bus?**

Cheapest settling: logic analyser on CLK/CMD/DAT0 in the BGA socket adapter, four channels,
24 MS/s is enough because we only need "edges or no edges". Send `0x46` first (a command we
know works) as the positive control, then `0x7E` in the same session, same card.

Outcome mapping:

| Result | What it means |
|---|---|
| `0x46` shows traffic, `0x7E` shows none | bitstream does not forward vendor commands → branch B dead on the T48, Weg 3 (own bitstream) becomes mandatory |
| `0x7E` shows traffic | forwarding works → the open question moves to the card's answer, which we still cannot see; next step is decoding the response on DAT0 |
| neither shows traffic | our model of the command gate is wrong; re-derive from the bus |

Do **not** probe by sweeping sub-opcodes. `0xFF` wedges the programmer until a physical
replug, and the mapping `sub_op = 0x40 + CMD` puts CMD0, CMD15, CMD24 (write) and CMD28/29
(write protect) inside the range a sweep would cross.

### G — the tooling questions

Free to us, and the highest expected value. The exact asks are in README §4 and issues #3/#4.
What we need from someone with UFPI or EasyJTAG, in priority order:

1. Whether the tool will send `CMD62 0xEFAC62EC` and then `CMD62 0x10210002`, and what the
   card answers. "The tool refuses" is a real answer.
2. Where the key shown in the RPMB screen comes from — metadata block or controller — plus
   the exact menu path.
3. A USB capture of that function, filtered on the programmer's VID/PID.

### A — the metadata claim

Held open by the third-party log, disproved for our two cards by direct search. What would
change our mind: a dump of a card where the tool shows a key, plus the byte offset it read.
We could then check whether that offset is even addressable on the T48.

### C, D, E — closed branches

Closed by measurement, and listed here so nobody spends effort reopening them. They stay
closed unless a new card model is added to the bench: the findings are die-specific.

### I — the provisioning question

The cheapest experiment in the whole tree and the one with the biggest effect on the repair:
prepare a USB stick (FAT32, `.pkg` in the root), boot the TV from it with a card whose counter
is 0, and log the LED states plus whether RPMB writes appear. If the TV provisions the card
itself, the key question stops mattering for the repair entirely.

### K — the firmware-update question

The card is not the obstacle. Measured across 587 extCSD dumps on our bench, 531 advertise
`FFU_FEATURE_SUPPORT` (`EXT_CSD[308] = 1`), and all nine dumps of our AJTD4R variant do, at
FW_REV 02.00. A firmware update is a real feature of this die.

Two things still stop us from running one, and both are about irreversibility:

| Blocker | Why |
|---|---|
| transport | the documented flow opens with `CMD60 / 0xEFAC60FC`; whether any programmer can put that on the bus is precisely node B |
| no undo | there is no backup path for controller firmware on the T48 — dumping it needs the same read-RAM backdoor that is still unproven. A wrong image does not fail safe: it replaces the code the controller boots. |

The image side is partly solved: the vendor firmware set is not capacity-specific, and one of
our two cards has an exact match (same PNM, same controller family) while the other has none
in its capacity — the closest file there is for the 32 GB sibling. Any match should still be
checked against `EXT_CSD[254..255]` before an attempt.

So the honest answer to "can we try FFU on our own card" is: **not yet, and not on the card
that carries a real image.** It is the only operation in this project that cannot be undone,
its gate is unanswered, and a positive answer from node B costs us one afternoon with a logic
analyser. If that answer ever comes back positive, the first FFU belongs on the empty sample
card and stays an explicit decision, not an experiment.

---

## 3. What we can do ourselves, in cost order

No new hardware needed for any of these. Ranked by value per hour.

1. **Bitstream diffing — run, negative.** The `.alg` set is complete on our bench: 354
   containers, five eMMC families each present as a `_18` and `_33` variant. We XORed them
   as planned, on the decompressed streams (340 604 B = 170 302 16-bit words each), and the
   method does not deliver what we hoped. The pair that should differ only in IO standard
   (`GEN_18`/`GEN_33`) differs in 9.19 % of bytes; a cross-family pair (`EMMC_41_18` vs
   `NAND_15`) differs in 10.80 % — there is no contrast, and the differences spread evenly
   over all bit positions and the whole stream. Reason: every variant is an independently
   placed and routed design, not a parameterised derivative, so an XOR of two routed
   Spartan-6 streams shows routing, not IO attributes. **The pin map cannot be derived this
   way.** What is left for that track: direct frame-address decoding, or the board itself.
   Numbers and the full table are in [../WEITERE-WEGE.md](../WEITERE-WEGE.md).
2. **Newer Xgpro build, static diff.** We hold two installer versions. A string-and-import
   diff between them can show whether the vendor command surface grew, without touching
   the hardware. Same method as the bitstream diff: compare, do not guess.
3. **UFPI opcode path — already settled, no test left.** Our own static analysis of the
   unpacked UFPI binary showed the RPMB workers are 0x89 bytes each and carry no read: the
   `0x93` worker takes a 32-byte key from a host-typed 64-hex-character field
   (`"Enter RPMB Auth Key (32 bytes)"`) and hands `req[0..3] = 0x93` plus those 32 bytes to
   the programmer, 36 bytes in 3 s; `0x94` is the same shape for authentication. There is no
   host-side RPMB frame builder and no key-read path in UFPI either — which is exactly the
   argument for issue #4, because the EasyJTAG *log* shows a key appearing from a metadata
   read. The open question is therefore not "what does 0x93 read", it is "which code path in
   the EasyJTAG firmware performs the metadata read".
4. **Two offline checks in our own images.** (a) `MTDRM_RPMBLoadMacKey` proves the host
   side reads the key through RPMB; following the caller chain in the boot loader would
   show *which* RPMB frames it expects. (b) Search the partition tables we already hold for
   the names the EasyJTAG logs expose: `rpmbak`, `keystorage`, `keyrefuge`, `keydata`,
   `keystore`, `keymaster`. A partition named **rpmbak** is an RPMB backup kept in the user
   area — if our boards carry one, there is a restore path that needs no key at all.
   Both are analysis of our own backup, offline, no risk.
5. **RPMB frame layer simulation.** Build the MAC over a synthetic key/nonce/counter and
   check our field packing against the JEDEC layout, so the frame code is proven before it
   ever meets a card.
6. **The USB stick test on the TV** (node I). Zero soldering, reversible, and it settles a
   question the programmer cannot answer at all.

Later, with the logic analyser: node B, plus recording what the FPGA does during an `.alg`
upload (Weg 3, step 4).

---

## 4. What we deliberately do not try

- No soldering, no probe needles on the die, no glitch coil (project rule, and node F is
  third-party work anyway).
- No destructive probe as a sonde: `CMD38` without an open read-RAM backdoor erases.
- No sub-opcode sweeps, no writes without a complete prior backup, no key material or
  serial numbers in any file here.
- No vendor firmware bytes redistributed; third-party code is linked, not copied.

---

## 5. If you are working through this as a contributor

Take one node, run the cheapest experiment named under it, report: card model, tool and
version, exact menu path or byte sequence, and the raw observation. A negative answer moves
a node to **closed** and is as valuable as a positive one. Please do not post key material,
full CIDs or dumps — derived facts are what we need.

Same document in [German](attack-tree.de.md) and [Chinese](attack-tree.zh.md).
