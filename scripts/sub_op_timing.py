#!/usr/bin/env python3
"""Diskriminator: Fuehrt der T48 den Sub-Opcode aus, oder quittiert er nur?

Vorlauf: sub_op_probe.py bekam fuer 0x57 (bekannt), 0x7E und 0x41 (unbekannt)
eine byte-identische Antwort. Die EP1-Quittung traegt also keine Information.
Zwei Erklaerungen bleiben:
  A) Der Programmer fuehrt das Kommando aus und quittiert pauschal.
  B) Der Programmer quittiert pauschal und verwirft Unbekanntes still.

Unterscheidung ueber zwei unabhaengige Signale:
  1. Latenz — ein ausgefuehrtes Kommando muss auf die Karte warten (ms-Bereich),
     ein verworfenes nicht (µs-Bereich).
  2. Form — ein Kommando, das die Programmer-Firmware zwingend ablehnen muss
     (falsche Paketlaenge), muss eine andere Antwort erzeugen als ein
     wohlgeformtes.

Nur Kommandos ohne Datenphase, ohne Vendor-Magic, ohne Blockzugriff.
Aufruf: python3 -I sub_op_timing.py   (hier ohne -I, siehe sub_op_probe.py)
"""
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t48_mmc

EP_CMD_IN = 0x81
REPS = 15


def pkt(sub_op, arg):
    return bytes([0x27, sub_op & 0xFF, 0x00, 0x00]) + \
           (arg & 0xFFFFFFFF).to_bytes(4, "little")


def timed(t48, data, timeout=5000):
    t0 = time.perf_counter()
    t48.write(data, timeout=timeout)
    r = t48.read(EP_CMD_IN, 8, timeout=timeout)
    return (time.perf_counter() - t0) * 1000.0, r   # ms


def series(t48, label, data):
    samples, replies = [], []
    for _ in range(REPS):
        ms, r = timed(t48, data)
        samples.append(ms)
        replies.append(r)
    uniq = {r.hex(" ") for r in replies}
    return label, statistics.median(samples), min(samples), max(samples), uniq


def main():
    print("T48 Diskriminator: Ausfuehrung vs. Pauschalquittung\n" + "=" * 58)
    t48 = t48_mmc.T48()
    try:
        info = t48.initialize()
        print(f"Karte erkannt, CID {info['cid'][:8].hex()}…\n")

        cases = [
            ("0x57 CMD23  arg=1      (bekannt)", pkt(0x57, 1)),
            ("0x4C CMD12             (bekannt)", pkt(0x4C, 0)),
            ("0x7E CMD62  arg=0      (unbekannt)", pkt(0x7E, 0)),
            ("0x41 CMD1   arg=0x40300000 (unbekannt)", pkt(0x41, 0x40300000)),
            ("0x7C CMD60  arg=0      (unbekannt)", pkt(0x7C, 0)),
            ("0xFF                    (ungueltig)", pkt(0xFF, 0)),
        ]

        print(f"{'Fall':<44} {'Median':>8} {'min':>7} {'max':>7}  Antwort")
        print("-" * 92)
        results = []
        for label, data in cases:
            lab, med, lo, hi, uniq = series(t48, label, data)
            results.append((lab, med))
            ant = uniq.pop() if len(uniq) == 1 else f"{len(uniq)} Varianten"
            print(f"{lab:<44} {med:8.3f} {lo:7.3f} {hi:7.3f}  {ant}")

        # Signal 2: Form. Pakete, die nicht ausgefuehrt werden duerfen.
        print("\nFormtest (erwartet: andere Antwort oder Zeitueberschreitung)")
        shape = [
            ("4-Byte-Paket 27 57 00 00", bytes([0x27, 0x57, 0x00, 0x00])),
            ("16-Byte-Paket 27 57 ...", pkt(0x57, 1) + bytes(8)),
            ("Top-Opcode 0x00, sub 0x57", bytes([0x00, 0x57]) + bytes(6)),
        ]
        for label, data in shape:
            try:
                ms, r = timed(t48, data)
                print(f"  {label:<34} {ms:8.3f} ms  {r.hex(' ')}")
            except Exception as exc:
                print(f"  {label:<34} Fehler: {exc}")

        # Kein Zustandsverlust? Ungueltige Kommandos koennen die Karte in den
        # Fehlerzustand bringen — deshalb erst CMD12 (Abbruch), dann lesen.
        print("\nKontrolle nach allen Versuchen")
        try:
            timed(t48, pkt(0x4C, 0))          # CMD12: Fehlerzustand verlassen
        except Exception:
            pass
        try:
            ext = t48.read_extcsd()
        except Exception as exc:
            print(f"  extCSD nicht lesbar ({exc}) — Sitzung neu aufbauen")
            info = t48.initialize()
            ext = info["extcsd"]
        print(f"  extCSD lesbar, REV {ext[192]}, "
              f"PARTITION_CONFIG 0x{ext[179]:02X}")
        ms, r = timed(t48, pkt(0x57, 1))
        print(f"  0x57 danach: {ms:.3f} ms  {r.hex(' ')}")

        print("\nLesart:")
        print("  Sind die Latenzen aller Faelle gleich, verwirft der Programmer")
        print("  unbekannte Sub-Opcodes, ohne sie an die Karte zu geben.")
        print("  Hebt sich 0x57/0x4C deutlich ab, wird ausgefuehrt.")
        print("  Andere Antworten im Formtest zeigen, dass die Firmware")
        print("  pruefen kann — dann ist die pauschale Quittung aussagekraeftig.")
        return 0
    finally:
        t48.close()


if __name__ == "__main__":
    sys.exit(main())
