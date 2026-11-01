#!/usr/bin/env python3
"""Einzelauswertung der 0x27-Antworten.

Frage: Haengt das Statusbyte (Byte 6) vom ARGUMENT ab, oder ist es vom
Sub-Opcode unabhaengig? Erst wenn ein GESICHERTER Sub-Opcode (0x4C = CMD12)
auf unterschiedliche Argumente unterschiedlich antwortet, ist das Statusbyte
ein Kartenstatus. Antwortet er nicht, ist es ein Programmer-Status und taugt
nicht als Beweis fuer Weitergabe.

Jede Antwort wird einzeln ausgegeben — nicht als Mengen-Zusammenfassung.

Aufruf: python3 sub_op_capture.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t48_mmc

EP_CMD_IN = 0x81
REPS = 5

CASES = [
    # (Beschriftung, sub_op, arg)
    ("Kontrolle  0x57 CMD23 arg=1",       0x57, 1),
    ("Kontrolle  0x4C CMD12 arg=0",       0x4C, 0x00000000),
    ("Kontrolle  0x4C CMD12 arg=max",     0x4C, 0xFFFFFFFF),
    ("Kontrolle  0x4D CMD13 arg=0",       0x4D, 0x00000000),
    ("Kontrolle  0x41 CMD1  arg=OCR",     0x41, 0x40300000),
    ("Kontrolle  0x41 CMD1  arg=0",       0x41, 0x00000000),
    ("Sonde      0x7E CMD62 arg=0",       0x7E, 0x00000000),
    ("Sonde      0x7E CMD62 arg=0xFFFFFFFF", 0x7E, 0xFFFFFFFF),
    ("Sonde      0x7E CMD62 arg=UNLOCK",  0x7E, 0xEFAC62EC),
    ("Sonde      0x7E CMD62 arg=EXIT",    0x7E, 0x00DECCEE),
    ("Sonde      0x7C CMD60 arg=0",       0x7C, 0x00000000),
    ("Sonde      0x7C CMD60 arg=UNLOCK",  0x7C, 0xEFAC60FC),
]


def raw_sub(t48, sub_op, arg, timeout=5000):
    pkt = bytes([0x27, sub_op & 0xFF, 0x00, 0x00]) + \
          (arg & 0xFFFFFFFF).to_bytes(4, "little")
    t0 = time.perf_counter()
    t48.write(pkt, timeout=timeout)
    r = t48.read(EP_CMD_IN, 8, timeout=timeout)
    return (time.perf_counter() - t0) * 1000.0, r


def main():
    print("Einzelauswertung der 0x27-Antworten\n" + "=" * 62)
    t48 = t48_mmc.T48()
    try:
        info = t48.initialize()
        ext = info["extcsd"]
        print(f"Karte: CID {info['cid'][:8].hex()}…\n")

        for label, sub, arg in CASES:
            print(f"{label}   (arg 0x{arg:08X})")
            seen = []
            for i in range(REPS):
                try:
                    ms, r = raw_sub(t48, sub, arg)
                    seen.append(r)
                    print(f"    #{i + 1}  {ms:7.3f} ms  {r.hex(' ')}")
                except Exception as exc:
                    seen.append(None)
                    print(f"    #{i + 1}  FEHLER: {exc}")
            byte6 = {r[6] for r in seen if r}
            print(f"    -> Statusbyte 6: "
                  f"{', '.join('0x%02X' % b for b in sorted(byte6)) or '—'}")
            print()

        # Zustandsverlust ausschliessen.
        print("Nachkontrolle (vollstaendiger extCSD-Vergleich)")
        try:
            raw_sub(t48, 0x4C, 0)          # CMD12: Fehlerzustand verlassen
        except Exception:
            pass
        ext2 = t48.read_extcsd()
        diffs = [i for i in range(512) if ext[i] != ext2[i]]
        if diffs:
            for i in diffs:
                print(f"  [{i:3d}] 0x{ext[i]:02X} -> 0x{ext2[i]:02X}")
        else:
            print("  extCSD unveraendert (alle 512 Byte)")
        return 0
    finally:
        t48.close()


if __name__ == "__main__":
    sys.exit(main())
