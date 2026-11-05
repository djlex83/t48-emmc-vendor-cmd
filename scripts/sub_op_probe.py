#!/usr/bin/env python3
"""Sub-Opcode-Sonde fuer den T48 (nur Kommandos, keine Datenbloecke).

Zweck: pruefen, ob der eMMC-Dispatcher des Programmers (Top-Opcode 0x27)
beliebige Sub-Opcodes durchreicht. Aus der Xgpro-RE ist bekannt, dass der
Host das Sub-Opcode-Byte frei setzen kann; offen ist, ob die Programmer-
Firmware/FPGA es annimmt.

Hintergrund der Hypothese — die belegten Sub-Opcodes folgen dem Muster
    sub_opcode = 0x40 + CMD-Nummer
    0x46 -> CMD6   0x4C -> CMD12   0x4D -> CMD13
    0x50 -> CMD16  0x57 -> CMD23   0x5C -> CMD28  0x5D -> CMD29
Daraus waeren CMD1 = 0x41, CMD60 = 0x7C, CMD62 = 0x7E.

Gesendet werden ausschliesslich Kommandos ohne Datenphase und ohne Vendor-
Magic. Keine Blockwrites, keine Loeschung, kein PARTITION_CONFIG.

Aufruf: python3 sub_op_probe.py   (ohne -I: pyusb liegt im User-Site)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t48_mmc

EP_CMD_IN = 0x81

# extCSD-Offsets (JEDEC). Nur zur lesbaren Ausgabe des Vorher-Zustands.
NAMES = {
    166: "BOOT_SIZE_MULT", 167: "RPMB_SIZE_MULT", 173: "PARTITION_SETTING_COMPLETED",
    175: "ERASE_GROUP_DEF", 176: "WR_REL_SET", 179: "PARTITION_CONFIG",
    182: "BOOT_WP", 183: "BOOT_WP_STATUS", 184: "RST_N_FUNCTION", 192: "EXT_CSD_REV",
}


def raw_sub(t48, sub_op, arg, timeout=5000):
    """Format A: [0x27, sub_op, 0,0, arg32 LE] -> 8 Byte Antwort."""
    pkt = bytes([0x27, sub_op & 0xFF, 0x00, 0x00]) + \
          (arg & 0xFFFFFFFF).to_bytes(4, "little")
    t48.write(pkt, timeout=timeout)
    return t48.read(EP_CMD_IN, 8, timeout=timeout)


def verdict(r):
    """Erfolgskriterium wie im Treiber (cmd6): Antwort beginnt mit 0x27."""
    if r[0] == 0x27:
        return "ANGENOMMEN (Echo 0x27)"
    return "ABGELEHNT (kein 0x27-Echo)"


def diff_ext(before, after):
    out = []
    for i in range(512):
        if before[i] != after[i]:
            tag = NAMES.get(i, "")
            out.append(f"  [{i:3d}] 0x{before[i]:02X} -> 0x{after[i]:02X}  {tag}")
    return out


def main():
    print("T48 Sub-Opcode-Sonde\n" + "=" * 52)
    t48 = t48_mmc.T48()
    try:
        info = t48.initialize()
        ext = info["extcsd"]
        print(f"CID roh        : {info['cid'].hex()}")
        print(f"EXT_CSD_REV    : {ext[192]}")
        print(f"SEC_COUNT      : 0x{int.from_bytes(ext[212:216], 'little'):08X}")

        print("\nVorher-Zustand (relevante extCSD-Bytes):")
        for i, name in sorted(NAMES.items()):
            print(f"  [{i:3d}] 0x{ext[i]:02X}  {name}")

        # [1] Kontrolle: belegter Sub-Opcode, Argument ohne Zustandswirkung.
        #     0x57 = CMD23 SET_BLOCK_COUNT, Arg 1.
        print("\n[1] Kontrolle sub=0x57 (CMD23) arg=1")
        r = raw_sub(t48, 0x57, 1)
        print(f"    Antwort {r.hex(' ')}  -> {verdict(r)}")
        if r[0] != 0x27:
            print("    Der bekannte Pfad antwortet nicht wie erwartet — Abbruch.")
            return 1

        # [2] Der eigentliche Test. 0x7E = hypothetisch CMD62, Arg 0.
        #     Ohne Magic ungueltig: erwartet wird Ablehnung, keine Wirkung.
        print("\n[2] Sonde     sub=0x7E (hyp. CMD62) arg=0")
        try:
            r = raw_sub(t48, 0x7E, 0)
            print(f"    Antwort {r.hex(' ')}  -> {verdict(r)}")
        except Exception as exc:
            print(f"    Fehler : {exc}")

        # [3] 0x41 = hypothetisch CMD1, Arg = normales OCR (harmlos).
        print("\n[3] Sonde     sub=0x41 (hyp. CMD1)  arg=0x40300000")
        try:
            r = raw_sub(t48, 0x41, 0x40300000)
            print(f"    Antwort {r.hex(' ')}  -> {verdict(r)}")
        except Exception as exc:
            print(f"    Fehler : {exc}")

        # Nachkontrolle: vollstaendiger extCSD-Vergleich.
        print("\nNachkontrolle")
        time.sleep(0.5)
        try:
            ext2 = t48.read_extcsd()
        except Exception as exc:
            print(f"  extCSD nicht lesbar: {exc}")
            print("  -> Programmer neu stecken und 't48_mmc.py recover' versuchen.")
            return 1
        d = diff_ext(ext, ext2)
        if d:
            print("  ACHTUNG, extCSD geaendert:")
            print("\n".join(d))
        else:
            print("  extCSD unveraendert (alle 512 Byte)")

        # Karte/Programmer antworten noch?
        r = raw_sub(t48, 0x57, 1)
        print(f"\nAbschluss-Kontrolle sub=0x57: {r.hex(' ')}")
        return 0
    finally:
        t48.close()


if __name__ == "__main__":
    sys.exit(main())
