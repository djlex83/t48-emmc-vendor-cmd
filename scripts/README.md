# scripts/

Diagnostic and repair tooling for the XGecu T48 on macOS. Python 3, `pyusb`.

## `t48_mmc.py` — the driver

Our own implementation of the T48 USB protocol (read, write, erase, extCSD, RPMB frames)
plus a CLI:

```
python3 t48_mmc.py info      # chip info and extCSD
python3 t48_mmc.py dump      # large, resumable backup
python3 t48_mmc.py verify    # compare a file against the card, read-only
python3 t48_mmc.py recover   # USB reset without unplugging
python3 t48_mmc.py selftest  # internal checks without a device
```

**It is read-only by default.** Every write and erase path is locked behind the
environment variable `T48_ALLOW_WRITE=1`. The author does not set it. `selftest` and
`info` need no device and no unlock.

The driver was written for repairing devices the author owns; see `../LEGAL.md`.

## Probe scripts

These exist to answer one question — whether the programmer forwards vendor commands to
the card — and they are published because their *negative* results matter.

| Script | What it does |
|---|---|
| `sub_op_probe.py` | first look at sub-opcodes `0x41`, `0x57`, `0x7E`, with before/after extCSD comparison |
| `sub_op_timing.py` | latency and packet-shape comparison; established that latency does not discriminate |
| `sub_op_capture.py` | every reply individually, with different arguments per sub-opcode |
| `sub_op_stability.py` | A/B alternation; proved that byte 6 is a settling artefact, not a status |
| `reply_width.py` | checked whether the reply is longer than 8 bytes; it is not |
| `vendor_forward_test.py` | read the same region before/after `CMD62 / 0x10210002` |

Only commands without a data phase are sent. No write or erase descriptor is ever used.

## Hazards of this protocol (measured, not guessed)

* **`0xFF` or any sub-opcode outside `0x40`–`0x7F`** gets no reply and wedges the
  programmer until the USB cable is physically replugged. Software recovery does not fix it.
* **`CMD38` without an open read-RAM backdoor erases.** Never use it as a probe.
* Under the `0x40 + CMD` mapping, `0x40` is CMD0 (reset), `0x4F` is CMD15 (GO_INACTIVE),
  `0x58` is CMD24 (**write**), `0x5C`/`0x5D` are CMD28/29 (**write protect**). Never sweep.
* One 14/15 block read per session; a second one hangs the device.

## Requirements

```
pip3 install --user pyusb
```

On macOS, `libusb` is bundled with pyusb's backend. The scripts insert their own directory
into `sys.path`, so `python3 -I` will not find `pyusb` in the user site-packages; run them
without `-I` from this directory.
