# Sony DTV partition layout — findings

Summary of what we determined from a Sony DTV firmware package (`sony_dtv0FA60A0AA0AA_…pkg`)
and from card dumps. **Analysis only — no firmware bytes are published here.**

Confidence labels: *confirmed* = verified in our own parsing; *from notes* = recorded
during earlier sessions and not re-checked here.

---

## What the firmware package contains

* **Confirmed:** a container with 51 partitions, `p1` … `p51`. There is **no GPT and no MBR**
  on the device — the layout is defined by the firmware itself, not by a standard
  partition table on the card.
* **From notes:** the named mounts we mapped are

  | Partition | Mount | Filesystem |
  |---|---|---|
  | p4 | `/perm` | ext4 |
  | p13 | `/linux_rootfs` | — |
  | p17 | `/3rd` | SquashFS |
  | p44 | `/system` | — |

  Partition numbers and mount names are what our parser produced. Treat this table as a
  lead, not as a specification.

## Why this matters for repair

The USB updater writes in the **bootloader context**, where the SoC already has whatever
access it needs. That is why a repaired TV does **not** need an RPMB key: the update path
does not require us to authenticate anything from the outside.

The RPMB key only becomes relevant if one wants to write RPMB-authenticated data **from
outside the device** — a bench setup, not a repair.

## What we did not do

* We did not publish the package, any extracted partition image, or any card dump. Those
  are third-party copyrighted material. See `../LEGAL.md`.
* We did not attempt to alter or bypass the updater's integrity checks.

## Reproducing

The package can be scanned read-only with a container parser; our scripts live in the
project workspace but are not included here because they operate on the firmware package
itself.
