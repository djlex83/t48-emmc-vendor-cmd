#!/usr/bin/env python3
"""Weitergabe-Test: Erreichen CMD60/CMD62 die Karte?

Die EP1-Quittung des T48 ist argumentunabhaengig und deshalb als Beweis
untauglich. Beobachtet wird stattdessen die WIRKUNG an der Karte.

Werkzeug: CMD62 / 0x10210002 biegt den normalen Blockpfad auf das
Controller-RAM um (dump_fw_bootrom.c). Ein Massenread desselben Bereichs
liefert danach andere Daten als vorher — das ist das Signal.

    Basis  -> Bereich lesen
    Vendor -> 0x7E UNLOCK, 0x7E 0x10210002
    Probe  -> denselben Bereich lesen
    Exit   -> 0x7E UNLOCK, 0x7E 0x00DECCEE
    Rest   -> denselben Bereich lesen, mit Basis vergleichen

Nur lesende Blockzugriffe. Keine Schreib- oder Loeschdeskriptoren.
Aufruf: python3 vendor_forward_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t48_mmc

EP_CMD_IN = 0x81
SUB_CMD60 = 0x7C
SUB_CMD62 = 0x7E

CMD60_UNLOCK = 0xEFAC60FC
CMD62_UNLOCK = 0xEFAC62EC
CMD62_READ_RAM = 0x10210002
CMD62_EXIT = 0x00DECCEE

FRAMES = 1          # 16 KiB, die ersten 32 Blöcke ab LBA 0


def raw_sub(t48, sub_op, arg, timeout=5000):
    pkt = bytes([0x27, sub_op & 0xFF, 0x00, 0x00]) + \
          (arg & 0xFFFFFFFF).to_bytes(4, "little")
    t48.write(pkt, timeout=timeout)
    return t48.read(EP_CMD_IN, 8, timeout=timeout)


def read_region(t48, timeout=8000):
    return t48.read_area(0x00, frames=FRAMES, start_lba=0, timeout=timeout)


def summarise(data):
    head = data[:48].hex(" ")
    return (f"{len(data)} B, Anfang {head}…, "
            f"Nullbytes {data.count(0)}/{len(data)}")


def main():
    print("Weitergabe-Test CMD60/CMD62\n" + "=" * 60)
    t48 = t48_mmc.T48()
    try:
        info = t48.initialize()
        print(f"Karte: CID {info['cid'][:8].hex()}…")

        print("\n[1] Basis lesen")
        base = read_region(t48)
        print(f"    {summarise(base)}")

        print("\n[2] Vendor-Kommandos senden (hyp. Sub-Opcodes)")
        steps = [
            (SUB_CMD62, CMD62_UNLOCK, "CMD62 Freischaltung"),
            (SUB_CMD62, CMD62_READ_RAM, "CMD62 Read-RAM-Backdoor"),
        ]
        for sub, arg, label in steps:
            try:
                r = raw_sub(t48, sub, arg)
                print(f"    0x{sub:02X} 0x{arg:08X}  {label:<28} "
                      f"Antwort {r.hex(' ')}")
            except Exception as exc:
                print(f"    0x{sub:02X} 0x{arg:08X}  {label:<28} FEHLER {exc}")
                print("    Abbruch: Programmer antwortet nicht mehr.")
                return 1

        print("\n[3] Probe lesen (nach geöffneter Backdoor)")
        try:
            probe = read_region(t48)
            print(f"    {summarise(probe)}")
        except Exception as exc:
            print(f"    Fehler: {exc}")
            probe = None

        if probe is not None:
            if probe == base:
                print("    -> gleiche Daten: Backdoor NICHT geöffnet")
            else:
                n = sum(1 for a, b in zip(base, probe) if a != b)
                print(f"    -> {n} von {len(base)} Byte verschieden: "
                      "Backdoor GEÖFFNET, 0x7E erreicht die Karte")

        print("\n[4] Backdoor schließen")
        for sub, arg, label in [(SUB_CMD62, CMD62_UNLOCK, "CMD62 Freischaltung"),
                                (SUB_CMD62, CMD62_EXIT, "CMD62 Exit")]:
            try:
                r = raw_sub(t48, sub, arg)
                print(f"    0x{sub:02X} 0x{arg:08X}  {label:<28} "
                      f"Antwort {r.hex(' ')}")
            except Exception as exc:
                print(f"    FEHLER {exc}")

        print("\n[5] Kontrolllesung")
        try:
            rest = read_region(t48)
            print(f"    {summarise(rest)}")
            print("    -> " + ("wie Basis, Zustand wiederhergestellt"
                               if rest == base else "ABWEICHUNG zur Basis"))
        except Exception as exc:
            print(f"    Fehler: {exc}")
            print("    Karte neu erkennen: Kabel ziehen oder 'info' erneut")

        print("\n[6] extCSD nach dem Lauf")
        try:
            ext = t48.read_extcsd()
            print(f"    REV {ext[192]}, PART_CONFIG 0x{ext[179]:02X}, "
                  f"SEC_COUNT 0x{int.from_bytes(ext[212:216], 'little'):08X}")
        except Exception as exc:
            print(f"    Fehler: {exc}")
        return 0
    finally:
        t48.close()


if __name__ == "__main__":
    sys.exit(main())
