**English** · [Deutsch](LEGAL.de.md) · [中文](LEGAL.zh.md)

# Scope, authorization, and legal posture

This repository documents research and repair work on hardware **the author owns**.

*Not legal advice. See "Limits" at the end.*

---

## What this repository is

* **Repair and data recovery** on the author's own devices — reading and rewriting the eMMC
  of a Sony TV mainboard that belongs to the author.
* **Interoperability research**: understanding how a storage device's documented and
  vendor-specific interfaces behave, so that a broken device can be repaired.
* **Measurement records**: what we sent, what came back, what it proves and what it does
  not. Negative results are published as prominently as positive ones.

## What this repository is not

* Not a tool or guide for accessing devices the author does not own. Every hardware step
  described was performed on hardware in the author's possession, with ownership known.
* Not DRM circumvention. Widevine L1 keybox extraction is explicitly out of scope and is
  absent from this repository. There is nothing here about protected media content.
* Not a distribution channel. **No third-party binaries, no vendor installers, no firmware
  images, no card dumps** are included. Where we describe a vendor tool, we record facts
  (opcodes, addresses, control flow), never code or files.
* Not a source of secrets. No RPMB key material, no credentials, no device serial numbers.

## Legal basis for the analysis (EU / Germany)

* Reverse engineering for **interoperability** is addressed by Article 6 of Directive
  2009/24/EC, implemented in Germany as § 69e UrhG. The analysis here targets the
  interfaces needed to read and rewrite a storage device for repair; it is not aimed at
  copying or distributing the analysed software.
* The vendor-command material is largely **public prior art** — `oranav/i9300_emmc_toolbox`
  (GPLv3, 2017) and arXiv 2511.22340 (2025). We cite these works; we do not reproduce their
  source code in this repository.
* Every finding is attributed. Where a claim comes from our own notes and is unverified,
  it is labelled as such.

## About the tooling in `scripts/`

The T48 driver is a **diagnostic and repair driver**. It is read-only by default:
every write or erase path is locked behind the environment variable `T48_ALLOW_WRITE=1`,
which the author keeps unset. The probe scripts send commands only.

Known hazards of the protocol are documented in the scripts themselves, because a
cautious reproduction is the point of publishing them.

## What would still carry risk, and why we did not publish it

* **Sony firmware images and card dumps** — third-party copyrighted material. We publish
  the analysis of the partition layout and the update mechanics, not the bytes.
* **Full reverse-engineering logs of vendor binaries** — we publish the operational
  findings needed for interoperability (`docs/ufpi-findings.md`), not the binary.
* **Key material of any kind** — excluded by policy.

## Limits

This note reduces the obvious risks; it does not guarantee anything.

* It is written by an engineer, not a lawyer, and is **not legal advice**.
* Liability rules differ by jurisdiction. If legal certainty matters — for example before
  publishing commercially, or before distributing the tooling as a product — have a
  qualified lawyer review it.
* Copyright and anti-circumvention rules vary between the EU, the US and other
  jurisdictions. This repository is written from an EU/German perspective.

If you believe something here should not be public, open an issue; we will act on it.
