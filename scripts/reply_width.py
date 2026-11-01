#!/usr/bin/env python3
"""Traegt die EP1-Antwort mehr als 8 Byte?

Xgpro prueft laut RE `reply_buf[1] != 0` als Erfolg — bei uns ist Byte 1 immer
0x00. Entweder ist die Regel falsch ueberliefert, oder die Antwort ist laenger
als die 8 Byte, die der Treiber liest, und die gemeinte Stelle liegt woanders.

Test: nach einem 0x27-Paket mehr Bytes anfordern und anschliessend ein zweites
Mal lesen, um Folgepakete zu erkennen. Nur Kommandos ohne Datenphase.
Aufruf: python3 reply_width.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t48_mmc

EP_CMD_IN = 0x81


def send(t48, sub_op, arg):
    pkt = bytes([0x27, sub_op & 0xFF, 0x00, 0x00]) + \
          (arg & 0xFFFFFFFF).to_bytes(4, "little")
    t48.write(pkt, timeout=5000)


def main():
    print("Breite der EP1-Antwort\n" + "=" * 58)
    t48 = t48_mmc.T48()
    try:
        info = t48.initialize()
        print(f"Karte: CID {info['cid'][:8].hex()}\n")

        for sub, arg, label in [(0x57, 1, "0x57 Kontrolle"),
                                (0x7E, 0, "0x7E hyp. CMD62"),
                                (0x4C, 0, "0x4C Kontrolle")]:
            print(f"{label}")
            send(t48, sub, arg)
            try:
                r = t48.read(EP_CMD_IN, 64, timeout=3000)
                print(f"    Read(64)  -> {len(r)} Byte: {r.hex(' ')}")
            except Exception as exc:
                print(f"    Read(64)  -> Fehler: {exc}")

            # Folgt noch etwas im Endpunkt?
            try:
                r2 = t48.read(EP_CMD_IN, 64, timeout=600)
                print(f"    2. Read   -> {len(r2)} Byte: {r2.hex(' ')}")
            except Exception:
                print("    2. Read   -> nichts mehr (Timeout)")
            print()

        # Alternative: kurze Wartezeit, dann lesen (falls Antwort verzoegert)
        print("Mit Wartezeit 20 ms vor dem Lesen")
        for sub, arg, label in [(0x57, 1, "0x57"), (0x7E, 0, "0x7E")]:
            send(t48, sub, arg)
            time.sleep(0.02)
            try:
                r = t48.read(EP_CMD_IN, 64, timeout=3000)
                print(f"    {label} -> {len(r)} Byte: {r.hex(' ')}")
            except Exception as exc:
                print(f"    {label} -> Fehler: {exc}")

        print("\nKontrolle am Ende")
        send(t48, 0x4C, 0)
        try:
            t48.read(EP_CMD_IN, 8, timeout=3000)
        except Exception:
            pass
        ext = t48.read_extcsd()
        print(f"    extCSD lesbar, REV {ext[192]}, PART_CONFIG 0x{ext[179]:02X}")
        return 0
    finally:
        t48.close()


if __name__ == "__main__":
    sys.exit(main())
