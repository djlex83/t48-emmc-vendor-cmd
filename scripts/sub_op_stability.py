#!/usr/bin/env python3
"""Ist das Statusbyte stabil oder ein Nachlauf-Effekt?

Beobachtung aus sub_op_capture.py: 0x7E liefert konstant 0x08, 0x7C konstant
0x00, waehrend 0x57/0x4C/0x4D konstant 0x00 liefern. Wenn Byte 6 den Status
des VORHERIGEN Pakets traegt, muesste eine Alternation A/B/A/B den Wert
hin- und herschalten. Bleibt er pro Sub-Opcode fest, ist er eine Eigenschaft
des Handlers.

Nur Kommandos ohne Datenphase, ohne Vendor-Magic.
Aufruf: python3 sub_op_stability.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t48_mmc

EP_CMD_IN = 0x81
ROUNDS = 6


def raw_sub(t48, sub_op, arg, timeout=5000):
    pkt = bytes([0x27, sub_op & 0xFF, 0x00, 0x00]) + \
          (arg & 0xFFFFFFFF).to_bytes(4, "little")
    t48.write(pkt, timeout=timeout)
    return t48.read(EP_CMD_IN, 8, timeout=timeout)


def main():
    print("Statusbyte-Stabilitaet\n" + "=" * 58)
    t48 = t48_mmc.T48()
    try:
        info = t48.initialize()
        print(f"Karte: CID {info['cid'][:8].hex()}\n")

        # A/B-Alternation: Kontrolle, Verdaechtiger, Kontrolle, Verdaechtiger
        pairs = [
            ("0x57 Kontrolle", 0x57, 1, "0x7E hyp. CMD62", 0x7E, 0),
            ("0x57 Kontrolle", 0x57, 1, "0x7C hyp. CMD60", 0x7C, 0),
        ]
        for lab_a, sub_a, arg_a, lab_b, sub_b, arg_b in pairs:
            print(f"Alternation {lab_b} gegen {lab_a}")
            states = []
            for i in range(ROUNDS):
                ra = raw_sub(t48, sub_a, arg_a)
                rb = raw_sub(t48, sub_b, arg_b)
                states.append((ra[6], rb[6]))
                print(f"    #{i + 1}  A {ra.hex(' ')} -> B {rb.hex(' ')}")
            a_vals = {s[0] for s in states}
            b_vals = {s[1] for s in states}
            print(f"    A-Status: {', '.join('0x%02X' % v for v in sorted(a_vals))}"
                  f"   B-Status: {', '.join('0x%02X' % v for v in sorted(b_vals))}")
            print()

        # Gegenprobe: Wiederholt derselbe Sub-Opcode ohne Wechsel.
        print("Wiederholung ohne Wechsel")
        for sub, label in [(0x7E, "0x7E"), (0x7C, "0x7C")]:
            vals = []
            for _ in range(ROUNDS):
                vals.append(raw_sub(t48, sub, 0)[6])
            print(f"    {label}: {', '.join('0x%02X' % v for v in vals)}")

        print("\nKontrolle am Ende")
        raw_sub(t48, 0x4C, 0)
        ext = t48.read_extcsd()
        print(f"    extCSD lesbar, REV {ext[192]}, PART_CONFIG 0x{ext[179]:02X}")
        return 0
    finally:
        t48.close()


if __name__ == "__main__":
    sys.exit(main())
