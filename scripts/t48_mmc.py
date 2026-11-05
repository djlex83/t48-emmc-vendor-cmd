#!/usr/bin/env python3
"""T48-eMMC-Treiber für macOS — rekonstruiert aus dem USB-Mitschnitt vom 30.10.2026.

Quelle: C:\\xgecu\\t48_usb_log.txt (Proxy-DLL, Xgpro.exe). Alle Bytefolgen unten
stammen aus diesem Mitschnitt, nicht aus Vermutungen.

Der T48 benutzt ZWEI Kanäle:
    0x01 OUT  Kommandos            0x81 IN  kurze Antworten
    0x02 OUT  512-Byte-Datenblöcke 0x82 IN  Datenantworten

Ablauf einer Sitzung (Reihenfolge und Längen wie im Mitschnitt):
    00                       -> 64 B   Geräte-Info
    24 f0 / 24 e0            -> 40 B   Session-Aufbau
    24 f1 / 3e               -> 16 B   Modus
    03 (64 Byte)             -> 32 B   BEGIN_TRANS (Achtung: ~270 ms)
    39                       -> 32 B   STATUS
    21                       ->  8 B   Fähigkeiten
    05 04                    -> 32 B   CID   (16 B ab Offset 8)
    06 04                    -> 24 B   CSD   (16 B ab Offset 8)
    08 48 00 02              -> 520 B  extCSD auf 0x82 (512 B ab Offset 8)
    04 00 b1 00              -> 32 B   END_TRANS

Befehle (alle Unterbefehle unter ``--help``):

    info                        Chip, CID/CSD, extCSD, Bereichsgrößen
    block [LBA]                 Einzelblock über den 14/15-Pfad (ein Read je Sitzung!)
    read  BEREICH DATEI [N] [START]     Bereich stromweise in eine Datei lesen
    dump  BEREICH DATEI N [START]       große Sicherung, mit --resume fortsetzbar
    verify BEREICH DATEI [START]        Datei gegen Karte vergleichen (nur lesend)
    write BEREICH DATEI [START]         schreiben (nur mit T48_ALLOW_WRITE=1)
    erase BEREICH BLÖCKE [START]        löschen   (nur mit T48_ALLOW_WRITE=1)
    meta                        Samsung-Metadatenblock bei LBA 0x100000 ansehen
    rpmb [counter|read|result]  RPMB-Anfragen über den 14/15-Pfad
    resetcfg [WERT]             PARTITION_CONFIG[179] setzen (nur mit Freigabe)
    recover                     USB-Reset ohne Umstecken versuchen
    selftest                    interne Prüfungen ohne Gerät

Bereiche: user (0), boot1 (1), boot2 (2), rpmb (3) — oder Zahlen 0..0xff.

Exit-Codes: 0 ok · 1 Fehler · 2 Aufruf/Eingabe · 3 kein Gerät · 4 Timeout
            5 Vergleich abweichend · 130 mit Strg-C abgebrochen.
"""
import argparse
import hashlib
import os
import shutil
import sys
import time

import usb.core
import usb.util

VERSION = "0.7"

VID, PID = 0xa466, 0x0a53

EP_CMD_OUT = 0x01
EP_DAT_OUT = 0x02
EP_CMD_IN = 0x81
EP_DAT_IN = 0x82

# Exit-Codes (siehe Docstring)
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NO_DEVICE = 3
EXIT_TIMEOUT = 4
EXIT_MISMATCH = 5

# BEGIN_TRANS: 64 Byte. Der Blob ist kein Xgpro-Mitschnitt, sondern das
# eMMC-Profil des Programmers; seine Bytes wurden gegen den Profil-Builder
# (emmc_probe.py) und gegen Xgpro (FUN_00444bc0) aufgeschlüsselt:
#
#   [1]        0x31              protocol_id eMMC
#   [2]        0x00              variant, niederes Byte (0x5100/0x5400 -> 0x00)
#   [0x0c]     0x54              variant, hohes Byte = Bitstream-Kennung
#   [0x3f]     0x54              dieselbe Kennung, gespiegelt am Blobende
#                               (0x54 = EMMC_54 = 4 Bit, 0x51 = 1 Bit)
#   [4] [5]    0x01 0x05         voltages-Wort LE: 0x0501 = 1,8 V, 0x0500 = 3,3 V
#   [0x15]     0x01              voltages & 0x0f — das VCCQ-Select-Nibble
#
# Die Spannung steht also an DREI Stellen (4, 5 und 0x15). Der frühere
# Kommentar "1 Bit / 1,8 V (variant=0x5100)" war falsch: der Blob fordert
# 4 Bit an, und 1,8 V war unsere eigene Einstellung, keine Messung.
# Am Gerät gemessen ist 3,3 V / 1 Bit (Bulk-Transfer), 1,8 V / 4 Bit
# funktioniert für Identify/CSD/extCSD ebenfalls; ob die VCCQ-Schiene
# wirklich schaltet, ist nicht gemessen. Beide Schalter: --voltage/--width.
BEGIN_TRANS = bytes([
    0x03, 0x31, 0x00, 0x00, 0x01, 0x05, 0xa1, 0x00,
    0x20, 0x00, 0x00, 0x00, 0x54, 0x00, 0x20, 0x00,
    0x00, 0x02, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00,
    0x03, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0xe5, 0x10, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x38, 0x08, 0x00, 0x00, 0x00, 0x00, 0x9e, 0x54,
])

# STATUS spiegelt BEGIN_TRANS[0:8], nur Byte 0 ist der Opcode 0x39. Abgeleitet
# statt fest eingetragen: die voltage-Bytes [4]/[5] liegen innerhalb dieses
# Fensters, eine Konstante würde nach --voltage 3.3 weiter 1,8 V behaupten.
def status_packet():
    return bytes([0x39]) + BEGIN_TRANS[1:8]

# Profilbyte-Positionen in BEGIN_TRANS.
BEGIN_OFF_VOLT_LOW = 0x04    # voltages-Niederbyte: 0x01 = 1,8 V, 0x00 = 3,3 V
BEGIN_OFF_VOLT_HI = 0x05     # voltages-Oberbyte: 0x05 in beiden Profilen
BEGIN_OFF_VCCQ = 0x15        # voltages-Nibble (v & 0x0f) — VCCQ-Select
BEGIN_OFF_WIDTH = (0x0c, 0x3f)   # variant-Hochbyte: 0x54 = 4 Bit, 0x51 = 1 Bit
VOLTAGES = {"1.8": 0x0501, "3.3": 0x0500}


def set_profile(voltage, width):
    """Schreibt VCCQ und Busbreite in BEGIN_TRANS.

    Standard ist der Blob oben (1,8 V / 4 Bit); mit "1.8" und 4 ändert sich
    nichts. Die Spannung sitzt an drei Stellen ([4] und [5] als voltages-Wort,
    [0x15] als Nibble) — wer nur [0x15] umschreibt, sendet ein halbes 3,3-V-
    Profil. Ein falsches Profil äußert sich als ausbleibende Antwort auf den
    extCSD-Read oder als wedge; nach einem wedge hilft nur Umstecken.
    """
    global BEGIN_TRANS
    b = bytearray(BEGIN_TRANS)
    v = VOLTAGES[voltage]
    b[BEGIN_OFF_VOLT_LOW] = v & 0xff
    b[BEGIN_OFF_VOLT_HI] = (v >> 8) & 0xff
    b[BEGIN_OFF_VCCQ] = v & 0x0f
    code = 0x54 if width == 4 else 0x51
    for off in BEGIN_OFF_WIDTH:
        b[off] = code
    BEGIN_TRANS = bytes(b)

END_TRANS = bytes([0x04, 0x01, 0x00, 0x00])

# Transaktionsmodus: im Mitschnitt mit zufälligem Nichtce versehen
MODE_TRANS = bytes([0x3e, 0x01, 0x73, 0x77, 0x50, 0x7f, 0x86, 0x01])

# Bereichsauswahl vor einem Massentransfer (aus dem Mitschnitt)
SETUP_STOP = bytes([0x27, 0x46, 0x00, 0x00, 0x00, 0x07, 0xb3, 0x02])
SETUP_SMALL = bytes([0x27, 0x46, 0x00, 0x00, 0x00, 0x03, 0xb3, 0x01])

MASS_FRAME_BYTES = 16400          # 16 Byte Kopf + 32 × 512 Byte
MASS_FRAME_DATA = 16384           # 32 × 512 Byte Nutzdaten je Rahmen
MASS_FRAMES = 256                 # 256 × 16 KiB = 4 MiB
MASS_BYTES = MASS_FRAMES * 32 * 512

# Opcodes der 40-Byte-Massendeskriptoren (RE: FUN_0049ba20 / FUN_004b19f0)
OP_READ = 0x0d
OP_WRITE = 0x1f
OP_ERASE = 0x0e                   # 16-Byte-Kommando, kein Deskriptor

# Schreibzugriffe sind gesperrt, solange diese Variable nicht gesetzt ist.
# Nutzerauflage: keine Schreibzugriffe auf die Karte ohne vollständige Sicherung.
WRITE_GUARD_ENV = "T48_ALLOW_WRITE"

AREA_NAMES = {
    0x00: "USER",
    0x01: "BOOT1",
    0x02: "BOOT2",
    0x03: "RPMB/Metadaten",
}

AREA_ALIASES = {
    "user": 0x00,
    "boot1": 0x01,
    "boot2": 0x02,
    "rpmb": 0x03,
}

TIMEOUT_HINT = ("Nach einem 14/15-Block-Read hilft meist nur: USB-Kabel kurz "
                "ziehen und wieder anstecken, Programm neu starten. "
                "'t48_mmc.py recover' versucht vorher einen USB-Reset.")


class T48Error(RuntimeError):
    """Fehler mit optionalem Handlungshinweis für die Ausgabe."""

    def __init__(self, message, hint=None):
        super().__init__(message)
        self.hint = hint


class T48NotFound(T48Error):
    """Kein T48 am USB-Bus gefunden."""


class T48Timeout(T48Error):
    """Gerät hat innerhalb des Timeouts nicht geantwortet."""


def require_write_permission():
    """Sperre für alle destruktiven Pfade (Schreiben/Löschen).

    Die Karte darf erst beschrieben werden, wenn der USER-Bereich vollständig
    gesichert ist (siehe T48-STATUS.md). Freigabe bewusst über Umgebungsvariable,
    damit kein versehentlicher Aufruf aus Skripten durchkommt.
    """
    if os.environ.get(WRITE_GUARD_ENV) != "1":
        raise T48Error(
            "Schreibzugriff gesperrt: erst vollständige Sicherung des USER-"
            "Bereichs, dann %s=1 setzen (siehe T48-STATUS.md, Abschnitt 6)."
            % WRITE_GUARD_ENV)


def parse_area(text):
    """'user'/'boot1'/'boot2'/'rpmb' oder Zahl (auch 0x03) -> Bereichsnummer."""
    s = str(text).strip().lower()
    if s in AREA_ALIASES:
        return AREA_ALIASES[s]
    try:
        value = int(s, 0)
    except ValueError:
        raise ValueError("Bereich %r: erlaubt sind user, boot1, boot2, rpmb "
                         "oder Zahlen 0..255" % text)
    if not 0x00 <= value <= 0xff:
        raise ValueError("Bereich muss 0x00..0xff sein")
    return value


def area_name(area):
    return AREA_NAMES.get(area, "Bereich 0x%02x" % area)


def is_timeout(exc):
    """USB-Timeout plattformübergreifend erkennen."""
    t = getattr(usb.core, "USBTimeoutError", None)
    if t is not None and isinstance(exc, t):
        return True
    if getattr(exc, "errno", None) in (60, 110, 10060):   # macOS/Linux/Windows
        return True
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


def fmt_duration(seconds):
    seconds = int(seconds + 0.5)
    if seconds < 60:
        return "%d s" % seconds
    return "%d:%02d min" % (seconds // 60, seconds % 60)


def fmt_size(n):
    """Bytezahl lesbar machen (KB/MB/GB mit dezimalen Einheiten wie Xgpro)."""
    n = float(n)
    for limit, unit, scale in ((1e3, "B", 1), (1e6, "KB", 1e3),
                               (1e9, "MB", 1e6), (1e12, "GB", 1e9)):
        if n < limit:
            if unit == "B":
                return "%d B" % n
            return ("%.0f %s" if n / scale < 10 else "%.1f %s") % (n / scale, unit)
    return "%.2f TB" % (n / 1e12)


class Progress:
    """Fortschritt als Zeilen, höchstens alle zwei Sekunden."""

    def __init__(self, total, unit=16384, label=""):
        self.total = max(int(total), 1)
        self.unit = unit
        self.label = label
        self.t0 = time.time()
        self.last = self.t0

    def __call__(self, done, total=None):
        now = time.time()
        if done < self.total and now - self.last < 2.0:
            return
        self.last = now
        elapsed = max(now - self.t0, 1e-9)
        current = done * self.unit
        total_bytes = self.total * self.unit
        rate = current / elapsed
        tail = ""
        if rate and done < self.total:
            tail = "  ETA %s" % fmt_duration((total_bytes - current) / rate)
        print("  %s%s / %s  (%s/s)%s"
              % (self.label, fmt_size(current), fmt_size(total_bytes),
                 fmt_size(rate), tail))
        sys.stdout.flush()


def hash_file(path, blocksize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(blocksize), b""):
            h.update(block)
    return h.hexdigest()


def check_space(path, need):
    """Prüft Zielverzeichnis und freien Platz vor einem großen Read."""
    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        raise T48Error("Zielverzeichnis existiert nicht: %s" % directory)
    free = shutil.disk_usage(directory).free
    if need > free:
        raise T48Error(
            "Nicht genug Platz für %s: benötigt %s, frei %s"
            % (os.path.basename(path), fmt_size(need), fmt_size(free)))
    if need > free - 64 * 1024 * 1024:
        print("Warnung: nur noch %s Reserve auf %s."
              % (fmt_size(free - need), directory))
    return free


def area_limits(extcsd, area):
    """Kapazität eines Bereichs in 512-Byte-Blöcken laut extCSD."""
    if area == 0x00:
        return int.from_bytes(extcsd[212:216], "little")
    if area in (0x01, 0x02):
        return extcsd[226] * 128 * 1024 // 512
    if area == 0x03:
        return extcsd[168] * 128 * 1024 // 512
    return None


def area_warning(extcsd, area, start_lba, blocks):
    """Warntext, wenn ein Zugriff über die ermittelte Bereichsgrenze reicht."""
    limit = area_limits(extcsd, area)
    if limit is None or limit == 0:
        return None
    if start_lba + blocks > limit:
        return ("Zugriff bis Block %d reicht über %s hinaus (extCSD: %d Blöcke)"
                % (start_lba + blocks - 1, area_name(area), limit))
    return None


def describe_areas(extcsd):
    user = int.from_bytes(extcsd[212:216], "little")
    boot_bytes = extcsd[226] * 128 * 1024
    rpmb_bytes = extcsd[168] * 128 * 1024
    return ("USER %s (%d Blöcke), BOOT1 %s, BOOT2 %s, RPMB %s"
            % (fmt_size(user * 512), user,
              fmt_size(boot_bytes), fmt_size(boot_bytes),
              fmt_size(rpmb_bytes)))


# extCSD-Felder (0-basierte Offsets, durch Xgpros eigenes Projektfile bestätigt)
FIELDS = {
    155: "PARTITION_SETTING_COMPLETED",
    167: "WR_REL_SET",
    168: "RPMB_SIZE_MULT",
    169: "FW_CONFIG",
    171: "USER_WP",
    173: "BOOT_WP",
    178: "BOOT_CONFIG_PROT",
    179: "PART_CONFIG",
    192: "EXT_CSD_REV",
    221: "HC_WP_GRP_SIZE",
    224: "HC_ERASE_GRP_SIZE",
    226: "BOOT_SIZE_MULT",
}


class T48:
    def __init__(self):
        try:
            self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        except Exception as exc:            # libusb fehlt / keine Rechte
            raise T48Error("USB-Zugriff fehlgeschlagen: %s" % exc,
                           hint="libusb installieren (brew install libusb) und "
                                "USB-Berechtigungen prüfen.") from exc
        if self.dev is None:
            raise T48NotFound(
                "T48 nicht gefunden (VID/PID 0xa466:0x0a53)",
                hint="Gerät einstecken; mit 'ioreg -p IOUSB -l' oder "
                     "'system_profiler SPUSBDataType' prüfen.")
        try:
            for cfg in self.dev:
                for itf in cfg:
                    try:
                        self.dev.detach_kernel_driver(itf.bInterfaceNumber)
                    except Exception:
                        pass
            self.dev.set_configuration()
            usb.util.claim_interface(self.dev, 0)
        except usb.core.USBError as exc:
            raise T48Error(
                "Gerät lässt sich nicht öffnen: %s" % exc,
                hint="Andere Programme (Xgpro, VM) könnten das Gerät belegen; "
                     "Kabel prüfen und 't48_mmc.py recover' versuchen.") from exc
        self.token = None

    # -- USB-Grundlagen ----------------------------------------------------
    def _raise_usb(self, exc, what, timeout):
        """pyusb-Fehler in deutsche, handlungsfähige Fehler übersetzen."""
        if is_timeout(exc):
            raise T48Timeout(
                "%s: keine Antwort innerhalb von %g s" % (what, timeout / 1000.0),
                hint=TIMEOUT_HINT) from exc
        raise T48Error(
            "%s: USB-Fehler: %s" % (what, exc),
            hint="Kabel und Anschluss prüfen; 't48_mmc.py recover' versuchen."
        ) from exc

    def write(self, data, ep=EP_CMD_OUT, timeout=5000):
        try:
            self.dev.write(ep, data, timeout=timeout)
        except usb.core.USBError as exc:
            self._raise_usb(exc, "Schreiben auf EP 0x%02x (%d Byte)"
                            % (ep, len(data)), timeout)

    def read(self, ep, length, timeout=5000):
        try:
            return bytes(self.dev.read(ep, length, timeout=timeout))
        except usb.core.USBError as exc:
            self._raise_usb(exc, "Lesen von EP 0x%02x (%d Byte)" % (ep, length),
                            timeout)

    def request(self, data, ep_in, length, timeout=5000):
        """Kommando senden, Antwort lesen."""
        self.write(data, timeout=timeout)
        return self.read(ep_in, length, timeout)

    # -- Sitzung -----------------------------------------------------------
    def device_info(self):
        return self.request(bytes(8), EP_CMD_IN, 64)

    def open_session(self):
        self.write(bytes([0x24, 0xf0, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00]))
        self.write(bytes([0x24, 0xe0, 0x28, 0x00, 0x00, 0x00, 0x00, 0x00,
                          0x00, 0x00, 0x00, 0xe5]))
        self.read(EP_CMD_IN, 40)

        self.write(bytes([0x24, 0xf1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))
        self.write(MODE_TRANS)
        self.read(EP_CMD_IN, 16)

    def begin(self):
        self.write(BEGIN_TRANS)
        self.write(status_packet())
        # Chip-Initialisierung: im Mitschnitt vergingen hier 271 ms
        return self.read(EP_CMD_IN, 32, timeout=10000)

    def status(self):
        return self.request(status_packet(), EP_CMD_IN, 32)

    def capabilities(self):
        return self.request(bytes([0x21, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
                            EP_CMD_IN, 8)

    def read_cid(self):
        r = self.request(bytes([0x05, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
                         EP_CMD_IN, 32, timeout=10000)
        return r[8:24]

    def read_csd(self):
        r = self.request(bytes([0x06, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
                         EP_CMD_IN, 24, timeout=10000)
        return r[8:24]

    def read_extcsd(self):
        self.write(bytes([0x08, 0x48, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00]))
        r = self.read(EP_DAT_IN, 520, timeout=10000)
        return r[8:520]

    def initialize(self):
        """Vollständige Xgpro-Initialisierungssequenz (am Gerät verifiziert).

        Reihenfolge ist zwingend: Info zweimal, Session, BEGIN_TRANS, dann
        Capabilities/CID/CSD/extCSD. Ohne 0x21/0x05/0x06 antwortet der
        Programmer auf den extCSD-Read nicht.
        """
        info = self.device_info()
        self.device_info()
        self.open_session()
        st = self.begin()
        if st and st[0] != 0:
            raise T48Error("BEGIN_TRANS fehlgeschlagen: Status 0x%02x" % st[0],
                           hint="Chip im Sockel prüfen (Kontakt, 1,8 V) und "
                                "Sitzung mit 'recover' neu aufbauen.")
        time.sleep(0.30)          # im Mitschnitt 271 ms

        caps = self.capabilities()
        cid = self.read_cid()
        csd = self.read_csd()
        ext = self.read_extcsd()
        if len(ext) != 512:
            raise T48Error("extCSD unvollständig: %d Byte" % len(ext))
        return {"info": info, "caps": caps, "cid": cid, "csd": csd,
                "extcsd": ext}

    def end(self):
        self.write(END_TRANS)

    def close(self):
        """Sitzung beenden und USB-Ressourcen freigeben (nie eine Ausnahme)."""
        if getattr(self, "dev", None) is None:
            return
        try:
            self.end()
        except Exception:
            pass
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass

    def usb_reset(self):
        """USB-Reset ohne Umstecken (best effort; nach hängendem Gerät)."""
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass
        try:
            self.dev.reset()
        except usb.core.USBError as exc:
            raise T48Error(
                "USB-Reset fehlgeschlagen: %s" % exc,
                hint="Kabel kurz ziehen und wieder anstecken, dann Programm "
                     "neu starten.") from exc
        time.sleep(2.0)
        try:
            self.dev.set_configuration()
            usb.util.claim_interface(self.dev, 0)
        except usb.core.USBError as exc:
            raise T48Error(
                "Gerät nach Reset nicht nutzbar: %s" % exc,
                hint="Kabel ziehen/anstecken.") from exc

    # -- Massentransfer (aus Xgpro RE: FUN_0049ba20 / FUN_004b19f0) --------
    @staticmethod
    def mass_descriptor(start_lba=0, frames=MASS_FRAMES):
        """40-Byte-Deskriptor für einen Lesestrom (Opcode 0x0d).

        Feldbelegung aus der RE von Xgpro (Lesepfad FUN_0049ba20, Schreib-
        pfad FUN_004b19f0):

            +0   Opcode 0x0d (Lesen) / 0x1f (Schreiben)
            +1   Blockmodus-Flag (1 = LBA in Blöcken)
            +4   Startadresse (LBA; byte_mode: Adresse >> 9)
            +8   Blockgröße (512)
            +12  Blöcke je 16-KiB-Rahmen (0x4000 / 512 = 32)
            +16  Anzahl Rahmen im Strom
            +20  Adressschritt je Rahmen in Blöcken (32 = 16 KiB)
            +24  Blöcke je Rahmen (32)
            +28  1
            +32  1
        """
        if not 1 <= frames <= 0xffff:
            raise ValueError("frames muss 1..65535 sein")
        if not 0 <= start_lba <= 0xffffffff:
            raise ValueError("start_lba muss 0..0xffffffff sein")
        d = bytearray(40)
        d[0] = OP_READ
        d[1] = 0x01
        d[4:8] = int(start_lba).to_bytes(4, "little")
        d[8:12] = (512).to_bytes(4, "little")
        d[12:16] = (32).to_bytes(4, "little")
        d[16:20] = frames.to_bytes(4, "little")
        d[20:24] = (32).to_bytes(4, "little")
        d[24:28] = (32).to_bytes(4, "little")
        d[28:32] = (1).to_bytes(4, "little")       # Lesen
        d[32:36] = (1).to_bytes(4, "little")
        return bytes(d)

    def cmd6(self, value, access, index=0xb3):
        """EXT_CSD-Byte per SWITCH (CMD6) ändern.

        Rahmen (aus dem Mitschnitt und aus Xgpro `FUN_0049e010`, das den
        Helfer `FUN_00492f30(handle, 0x46, arg, buf)` mit gepacktem Argument
        aufruft): `27 46 00 00 00 <value> <index> <access>`.

        access: 1 = Bits setzen, 2 = Bits löschen, 3 = Byte schreiben.
        Beweis aus dem Mitschnitt: `… 01 b3 01` = Bit 0 setzen (Boot1),
        `… 07 b3 02` = Bits 0..2 löschen (zurück auf USER),
        `… 03 b3 01` = Bits 0+1 setzen (RPMB).
        """
        cmd = bytes([0x27, 0x46, 0x00, 0x00, 0x00, value & 0xff,
                     index & 0xff, access & 0x03])
        self.write(cmd)
        return self.read(EP_CMD_IN, 8)

    def setup_area(self, area):
        """Bereich wählen. 0x00 USER, 0x01 BOOT1, 0x02 BOOT2, 0x03 RPMB.

        Wichtig: Bereichsauswahl läuft über die PARTITION_ACCESS-Bits in
        EXT_CSD[179]. Ein bloßes Setzen der Bits (wie früher hier) lässt den
        Bereich unverändert, wenn schon eine Boot-Partition aktiv ist — ein
        „USER"-Read konnte so in Wahrheit BOOT1 lesen. Deshalb: erst Bits
        0..2 löschen (Zugriff auf USER), dann gewünschte Bits setzen.
        """
        if not 0x00 <= area <= 0xff:
            raise ValueError("Bereich muss 0x00..0xff sein")
        r = self.cmd6(0x07, 0x02)
        if r[0] != 0x27:
            raise T48Error("Bereichsauswahl fehlgeschlagen: %s" % r.hex(" "))
        if area:
            r = self.cmd6(area, 0x01)
            if r[0] != 0x27:
                raise T48Error("Bereichsauswahl fehlgeschlagen: %s" % r.hex(" "))
        return r

    def setup_small(self):
        self.write(SETUP_SMALL)
        return self.read(EP_CMD_IN, 8)

    def setup_stop(self):
        self.write(SETUP_STOP)
        return self.read(EP_CMD_IN, 8)

    def write_extcsd_byte(self, index, value):
        """Ein einzelnes extCSD-Byte schreiben (SWITCH access 3 = write byte).

        Gedacht für PARTITION_CONFIG[179] (Werkzeug: `resetcfg`). Gesperrt
        ohne `T48_ALLOW_WRITE=1` — das Register ist persistent im Chip.
        """
        require_write_permission()
        r = self.cmd6(value, 0x03, index)
        if r[0] != 0x27:
            raise T48Error("EXT_CSD-Schreiben fehlgeschlagen: %s" % r.hex(" "))
        return r

    def read_area(self, area, frames=MASS_FRAMES, start_lba=0, timeout=10000,
                  progress=None):
        """Liest frames × 16 KiB ab start_lba (LBA, 512 Byte) aus einem Bereich.

        Jeder 16400-Byte-Rahmen besteht aus 16 Byte Kopf und 32 × 512 Byte
        Nutzdaten. Rückgabe sind die reinen Nutzdaten.

        Die Startadresse steht in Byte 4 des Deskriptors (RE: FUN_0049ba20);
        jeder Rahmen adressiert intern 32 Blöcke weiter (Feld +20).
        """
        if not 1 <= frames <= 0xffff:
            raise ValueError("frames muss 1..65535 sein")
        self.setup_area(area)
        self.write(self.mass_descriptor(start_lba, frames))
        out = []
        for i in range(frames):
            r = self.read(EP_DAT_IN, MASS_FRAME_BYTES, timeout=timeout)
            if len(r) != MASS_FRAME_BYTES:
                raise T48Error("Rahmen %d unvollständig: %d Byte" %
                               (i, len(r)))
            out.append(r[16:])
            if progress:
                progress(i + 1, frames)
        return b"".join(out)

    def dump(self, area, path, frames_total, start_lba=0, chunk=MASS_FRAMES,
             progress=None, timeout=10000, skip_frames=0):
        """Schreibt frames_total × 16 KiB ab start_lba fortlaufend in eine Datei.

        Arbeitet in 4-MiB-Deskriptoren wie Xgpro (256 Rahmen je Deskriptor,
        Startadresse jeweils in Feld +4). Read-only.

        skip_frames > 0 setzt eine vorhandene Sicherung fort: die Datei wird
        angehängt, ab Rahmen skip_frames weitergelesen. Die Datei muss dann
        bereits ein ganzes Vielfaches von 16 KiB enthalten (der Aufrufer
        prüft das).
        """
        if not 1 <= chunk <= 0xffff:
            raise ValueError("chunk muss 1..65535 sein")
        if skip_frames < 0:
            raise ValueError("skip_frames muss >= 0 sein")
        if skip_frames > frames_total:
            raise ValueError("skip_frames (%d) > frames_total (%d)"
                             % (skip_frames, frames_total))
        mode = "ab" if skip_frames else "wb"
        done = skip_frames
        with open(path, mode) as f:
            while done < frames_total:
                n = min(chunk, frames_total - done)
                f.write(self.read_area(area, frames=n,
                                       start_lba=start_lba + done * 32,
                                       timeout=timeout))
                done += n
                if progress:
                    progress(done, frames_total)
                f.flush()
        return done * 16384

    def compare_area(self, area, path, start_lba=0, frames=None,
                     chunk=MASS_FRAMES, max_examples=12, timeout=10000,
                     progress=None):
        """Vergleicht eine Datei mit dem Karteninhalt, ohne zu schreiben.

        Liest genau wie `dump` in 4-MiB-Blöcken und vergleicht Rahmenweise;
        nur abweichende Rahmen werden blockweise aufgeschlüsselt. Ist die
        Datei kürzer als der angeforderte Bereich, gilt der Rest als Nullen
        (wie der Schreibpfad ihn auffüllt). Read-only.
        """
        if not 1 <= chunk <= 0xffff:
            raise ValueError("chunk muss 1..65535 sein")
        file_size = os.path.getsize(path)
        file_frames = (file_size + MASS_FRAME_DATA - 1) // MASS_FRAME_DATA
        if frames is None:
            frames = file_frames
        if not 1 <= frames <= 0xffffffff:
            raise ValueError("frames muss 1..0xffffffff sein")

        bad_blocks = 0
        first_bad = None
        examples = []
        done = 0
        with open(path, "rb") as f:
            while done < frames:
                n = min(chunk, frames - done)
                got = self.read_area(area, frames=n,
                                     start_lba=start_lba + done * 32,
                                     timeout=timeout)
                want = f.read(n * MASS_FRAME_DATA)
                if len(want) < n * MASS_FRAME_DATA:
                    want += bytes(n * MASS_FRAME_DATA - len(want))
                for fi in range(n):
                    g = got[fi * MASS_FRAME_DATA:(fi + 1) * MASS_FRAME_DATA]
                    w = want[fi * MASS_FRAME_DATA:(fi + 1) * MASS_FRAME_DATA]
                    if g == w:
                        continue
                    base = start_lba + (done + fi) * 32
                    for bi in range(32):
                        a = g[bi * 512:(bi + 1) * 512]
                        b = w[bi * 512:(bi + 1) * 512]
                        if a == b:
                            continue
                        bad_blocks += 1
                        if first_bad is None:
                            first_bad = base + bi
                        if len(examples) < max_examples:
                            k = next(x for x in range(512) if a[x] != b[x])
                            examples.append({
                                "lba": base + bi,
                                "offset": k,
                                "file": b[k],
                                "card": a[k],
                            })
                done += n
                if progress:
                    progress(done, frames)
        return {
            "frames": frames,
            "bytes": frames * MASS_FRAME_DATA,
            "file_bytes": file_size,
            "bad_blocks": bad_blocks,
            "first_bad_lba": first_bad,
            "examples": examples,
        }

    def compare_zeros(self, area, start_lba, blocks, chunk=MASS_FRAMES,
                      timeout=10000, progress=None):
        """Prüft, ob ein Bereich nach dem Löschen vollständig Nullen liefert."""
        if blocks <= 0:
            raise ValueError("blocks muss > 0 sein")
        frames = (blocks + 31) // 32
        bad_blocks = 0
        first_bad = None
        done = 0
        while done < frames:
            n = min(chunk, frames - done)
            data = self.read_area(area, frames=n,
                                  start_lba=start_lba + done * 32,
                                  timeout=timeout)
            limit = min(len(data), (blocks - done * 32) * 512)
            seg = data[:limit]
            if seg.count(0) != len(seg):
                for off in range(0, limit, 512):
                    if seg[off:off + 512].count(0) == 512:
                        continue
                    bad_blocks += 1
                    if first_bad is None:
                        first_bad = start_lba + done * 32 + off // 512
            done += n
            if progress:
                progress(done, frames)
        return {"blocks": blocks, "bad_blocks": bad_blocks,
                "first_bad_lba": first_bad}

    # -- Schreibpfad (RE: FUN_004b19f0 / FUN_004afb50) ---------------------
    @staticmethod
    def write_descriptor(start_lba=0, frames=MASS_FRAMES):
        """40-Byte-Deskriptor für einen Schreibstrom (Opcode 0x1f).

        Gleiches Raster wie beim Lesen, nur +28 = 4 (Schreiben). In Xgpro
        werden die Felder zur Laufzeit aus DAT_007476xx gesetzt; die Werte
        sind aus FUN_004b19f0 belegt:

            +0  0x1f · +1 1 · +4 Start-LBA · +8 512 · +12 32
            +16 Rahmenzahl · +20 32 · +24 32 · +28 4 · +32 1
        """
        if not 1 <= frames <= 0xffff:
            raise ValueError("frames muss 1..65535 sein")
        if not 0 <= start_lba <= 0xffffffff:
            raise ValueError("start_lba muss 0..0xffffffff sein")
        d = bytearray(40)
        d[0] = OP_WRITE
        d[1] = 0x01
        d[4:8] = int(start_lba).to_bytes(4, "little")
        d[8:12] = (512).to_bytes(4, "little")
        d[12:16] = (32).to_bytes(4, "little")
        d[16:20] = frames.to_bytes(4, "little")
        d[20:24] = (32).to_bytes(4, "little")
        d[24:28] = (32).to_bytes(4, "little")
        d[28:32] = (4).to_bytes(4, "little")       # Schreiben
        d[32:36] = (1).to_bytes(4, "little")
        return bytes(d)

    @staticmethod
    def mass_frame(lba, payload=b"", marker=0):
        """Ein 16400-Byte-Datenrahmen (Kopf wie in FUN_004b19f0).

        +0 Fehler-/Markerbyte, +4 LBA, +8 Blockgröße, +12 Blöcke je Rahmen,
        ab +16 die 16 KiB Nutzdaten (fehlende Bytes werden mit 0 aufgefüllt).
        """
        if len(payload) > 0x4000:
            raise ValueError("Rahmen darf höchstens 16 KiB Nutzdaten tragen")
        f = bytearray(MASS_FRAME_BYTES)
        f[0] = marker
        f[4:8] = int(lba).to_bytes(4, "little")
        f[8:12] = (512).to_bytes(4, "little")
        f[12:16] = (32).to_bytes(4, "little")
        f[16:16 + len(payload)] = payload
        return bytes(f)

    def finish_write(self, timeout=15000):
        """Abschluss eines Schreibstroms: STATUS 0x39 senden, 32 Byte lesen.

        Aus FUN_004afb50: Antwortbyte 0 == 0x02 bedeutet „EMMC Running
        TimeOut" (Programmierung noch nicht fertig), sonst gelten Code (u16
        bei +2) und Statusregister (u32 bei +4).
        """
        self.write(status_packet())
        r = self.read(EP_CMD_IN, 32, timeout=timeout)
        if r[0] == 0x02:
            raise T48Error("EMMC Running TimeOut (Programmierung läuft noch)",
                           hint="Chip nach dem Schreiben kurz ruhen lassen "
                                "und mit 'verify' erneut prüfen.")
        if r[0] != 0:
            raise T48Error("Abschluss-Status 0x%02x, Register 0x%08x" %
                           (r[0], int.from_bytes(r[4:8], "little")))
        return r

    def abort_write(self, last_lba, timeout=10000):
        """Abbruchrahmen (Kopfbyte 1) senden und Status abholen."""
        self.write(self.mass_frame(last_lba, marker=1), EP_DAT_OUT, timeout)
        return self.finish_write(timeout)

    def write_area(self, area, data, start_lba=0, timeout=15000, progress=None):
        """Schreibt data (Vielfaches von 512 B) ab start_lba in einen Bereich.

        Protokoll aus FUN_004b19f0: Deskriptor 0x1f, dann 16400-Byte-Rahmen
        mit fortlaufender LBA (+32 Blöcke je Rahmen). Jeder Rahmen trägt
        16 KiB Nutzdaten; der letzte wird mit Nullen aufgefüllt. Nach jedem
        vollen 1-MB-Block bekommt der Folge-Rahmen Kopfbyte 2, danach wird
        ein 64-Byte-Status von 0x81 gelesen. Abschluss über finish_write().
        Gesperrt, solange WRITE_GUARD_ENV nicht gesetzt ist.
        """
        require_write_permission()
        if len(data) % 512:
            raise ValueError("Datenlänge muss ein Vielfaches von 512 sein")
        if not data:
            return 0
        total_blocks = len(data) // 512
        self.setup_area(area)
        done = 0
        while done < total_blocks:
            n_blocks = min(total_blocks - done, MASS_FRAMES * 32)
            n_frames = (n_blocks + 31) // 32
            self.write(self.write_descriptor(start_lba + done, n_frames))
            for i in range(n_frames):
                off = (done + i * 32) * 512
                payload = data[off:off + 0x4000]
                marker = 2 if (i % 64 == 0 and i != 0) else 0
                self.write(self.mass_frame(start_lba + done + i * 32,
                                           payload, marker),
                           EP_DAT_OUT, timeout=timeout)
                if marker:
                    st = self.read(EP_CMD_IN, 64, timeout=timeout)
                    if st[0] != 0:
                        raise T48Error(
                            "Statusfehler nach Rahmen %d: Code %d, "
                            "Register 0x%08x" %
                            (i, st[0], int.from_bytes(st[8:12], "little")))
                if progress:
                    progress(done + i * 32, total_blocks)
            done += n_blocks
        self.finish_write(timeout)
        return len(data)

    def write_file(self, area, path, start_lba=0, timeout=15000, progress=None):
        with open(path, "rb") as f:
            data = f.read()
        return self.write_area(area, data, start_lba=start_lba,
                               timeout=timeout, progress=progress)

    # -- Löschen (RE: FUN_004acee0; nicht am Gerät getestet) ---------------
    def erase_range(self, area, start_lba, end_lba, timeout=15000):
        """Löscht [start_lba, end_lba] (LBA, 512 Byte) in einem Kommando.

        Kommando aus FUN_004acee0: 16 Byte, Byte 0 = 0x0e, Bytes 4–7 Start-
        LBA, Bytes 8–11 Ende-LBA (inklusive). Antwort: 8 Byte von 0x81,
        Byte 1 ist der Fehlercode. Xgpro zerlegt große Bereiche in Blöcke
        und pollt dazwischen per CMD13 (0x4c) — hier ein Bereich pro Aufruf.
        """
        require_write_permission()
        if not 0 <= start_lba <= end_lba <= 0xffffffff:
            raise ValueError("Bereich muss start <= ende <= 0xffffffff erfüllen")
        self.setup_area(area)
        cmd = bytearray(16)
        cmd[0] = OP_ERASE
        cmd[4:8] = int(start_lba).to_bytes(4, "little")
        cmd[8:12] = int(end_lba).to_bytes(4, "little")
        self.write(bytes(cmd))
        r = self.read(EP_CMD_IN, 8, timeout=timeout)
        if r[1] != 0:
            raise T48Error("Erase-Fehler: Code %d, Register 0x%08x" %
                           (r[1], int.from_bytes(r[4:8], "little")))
        return r

    def erase_area(self, area, blocks, start_lba=0, timeout=15000):
        """Löscht blocks × 512 Byte ab start_lba."""
        if blocks <= 0:
            raise ValueError("blocks muss > 0 sein")
        return self.erase_range(area, start_lba, start_lba + blocks - 1,
                                timeout=timeout)

    # -- Einzelblock (verifiziert für genau einen Read pro Sitzung) --------
    @staticmethod
    def cmd_14(lba):
        """Adressbefehl; LBA 0 -> 00 .. 01, LBA 1 -> 01 .. 02."""
        return bytes([0x14, lba & 0xff, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                      (lba + 1) & 0xff, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00,
                      0x00])

    @staticmethod
    def cmd_15(count):
        """Länge in Blöcken (512 Byte)."""
        return bytes([0x15, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00,
                      count & 0xff, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00])

    def read_block(self, lba=0, token=None, timeout=10000):
        """Liest genau einen 512-Byte-Block nach dem 14/15-Protokoll.

        Der 512-Byte-Steuerblock ist ein RPMB-Rahmen: 16-Byte-Nonce bei
        Offset 484 (hier „Token") und Request-Typ 0x0002 bei Offset 510/511
        — also eine Typ-2-Counter-Anfrage. Der Programmer gibt die Nonce im
        Antwortrahmen bei Offset 500 (absolut) zurück. Nach einem Block-Read
        darf in derselben Sitzung kein weiterer 14-Read folgen (Gerät hängt
        sonst).
        """
        if lba < 0:
            raise ValueError("LBA muss >= 0 sein")
        token = token or os.urandom(16)
        self.setup_small()
        self.write(self.cmd_14(lba))
        ctl = bytearray(512)
        ctl[484:500] = token
        ctl[511] = 0x02
        self.write(bytes(ctl), EP_DAT_OUT)
        self.write(self.cmd_15(1))
        try:
            r = self.read(EP_DAT_IN, 528, timeout=timeout)
        except T48Timeout as exc:
            raise T48Timeout(
                "Einzelblock-Read (LBA %d): keine Antwort innerhalb von %g s"
                % (lba, timeout / 1000.0),
                hint="Ein 14/15-Read je Sitzung. Kabel ziehen/anstecken, "
                     "Programm neu starten; für größere Bereiche 'read' "
                     "oder 'dump' (Massentransfer) benutzen.") from exc
        self.token = r[500:516]
        return r

    # -- RPMB-Rahmen (JEDEC, über den Einzelblockpfad) --------------------
    # Der Programmer transportiert genau einen 512-Byte-RPMB-Rahmen im
    # 512-Byte-Steuerblock des 14/15-Protokolls und liefert ihn zusammen mit
    # einem 16-Byte-Kopf als 528-Byte-Antwort zurück.
    RPMB_PROGRAM_KEY = 0x0001       # irreversibel, nur bei Zähler 0
    RPMB_READ_COUNTER = 0x0002
    RPMB_WRITE_DATA = 0x0003        # nur mit Key; hier bewusst nicht gebaut
    RPMB_READ_DATA = 0x0004
    RPMB_RESULT = 0x0005

    @staticmethod
    def rpmb_frame(req_type, address=0, block_count=0, nonce=None,
                   data=b"", mac=None):
        """Baut einen 512-Byte-RPMB-Rahmen.

        Layout (Rahmen-relativ, JEDEC): MAC 196-227, Daten 228-483,
        Nonce 484-499, Zähler 500-503 (nur Antwort), Adresse 504-505,
        Blockzahl 506-507, Result 508-509, Typ 510-511; alles big-endian.
        """
        nonce = os.urandom(16) if nonce is None else nonce
        mac = b"\x00" * 32 if mac is None else mac
        if len(nonce) != 16:
            raise ValueError("Nonce muss 16 Byte sein")
        if len(mac) != 32:
            raise ValueError("MAC muss 32 Byte sein")
        if len(data) > 256:
            raise ValueError("Daten dürfen höchstens 256 Byte sein")
        if not 0 <= address <= 0xffff:
            raise ValueError("Adresse muss 0..0xffff sein")
        if not 0 <= block_count <= 0xffff:
            raise ValueError("Blockzahl muss 0..0xffff sein")
        f = bytearray(512)
        f[196:228] = mac
        f[228:228 + len(data)] = data
        f[484:500] = nonce
        f[504:506] = address.to_bytes(2, "big")
        f[506:508] = block_count.to_bytes(2, "big")
        f[510:512] = req_type.to_bytes(2, "big")
        return bytes(f)

    @staticmethod
    def rpmb_parse(answer):
        """Zerlegt die 528-Byte-Antwort (16-Byte-Kopf + 512-Byte-Rahmen)."""
        if len(answer) < 528:
            raise ValueError("Antwort muss 528 Byte sein")
        f = answer[16:528]
        return {
            "raw": answer,
            "mac": f[196:228],
            "data": f[228:484],
            "nonce": f[484:500],
            "counter": int.from_bytes(f[500:504], "big"),
            "address": int.from_bytes(f[504:506], "big"),
            "block_count": int.from_bytes(f[506:508], "big"),
            "result": int.from_bytes(f[508:510], "big"),
            # Beobachtung am T48: das Typfeld kommt byte-verdreht zurück
            # (Typ 2 -> 02 00), alle anderen Mehrbyte-Felder sind big-endian.
            "type": int.from_bytes(f[510:512], "little"),
            "type_be": int.from_bytes(f[510:512], "big"),
        }

    def rpmb_request(self, frame, address=0, timeout=10000):
        """Sendet einen RPMB-Rahmen im RPMB-Bereich und liest 528 Byte.

        Achtung: Ein 14-Read pro Sitzung; ein zweiter hängt das Gerät.
        """
        if len(frame) != 512:
            raise ValueError("Rahmen muss 512 Byte sein")
        self.setup_area(0x03)
        self.write(self.cmd_14(address))
        self.write(frame, EP_DAT_OUT)
        self.write(self.cmd_15(1))
        try:
            return self.read(EP_DAT_IN, 528, timeout=timeout)
        except T48Timeout as exc:
            raise T48Timeout(
                "RPMB-Anfrage (Typ 0x%04x, Adresse %d): keine Antwort "
                "innerhalb von %g s" % (int.from_bytes(frame[510:512], "big"),
                                        address, timeout / 1000.0),
                hint="Ein 14/15-Read je Sitzung. Kabel ziehen/anstecken, "
                     "dann Programm neu starten.") from exc

    def rpmb_read_counter(self, timeout=10000):
        """Typ 2: Schreibzähler lesen — ohne Authentifizierung möglich."""
        nonce = os.urandom(16)
        frame = self.rpmb_frame(self.RPMB_READ_COUNTER, nonce=nonce)
        r = self.rpmb_parse(self.rpmb_request(frame, timeout=timeout))
        r["nonce_ok"] = r["nonce"] == nonce
        return r

    def rpmb_program_key(self, key, timeout=10000):
        """Typ 1: RPMB-Key dauerhaft programmieren.

        Der Key steht im MAC-Feld (Bytes 196-227) des Rahmens, sonst ist
        alles leer. Laut JEDEC nimmt der Controller den Befehl nur an, wenn
        der Schreibzähler 0 ist; danach ist der Key fix und nie lesbar.
        Ein falscher Key blockiert die Karte dauerhaft (Vendor-Unlock nötig).
        """
        if len(key) != 32:
            raise ValueError("RPMB-Key muss 32 Byte sein")
        nonce = os.urandom(16)
        frame = self.rpmb_frame(self.RPMB_PROGRAM_KEY, mac=key, nonce=nonce)
        r = self.rpmb_parse(self.rpmb_request(frame, timeout=timeout))
        r["nonce_ok"] = r["nonce"] == nonce
        return r

    def rpmb_read_data(self, address, block_count=1, nonce=None,
                       timeout=10000):
        """Typ 4: liefert keine RPMB-Daten über den T48.

        Mit block_count >= 1 antwortet der Programmer immer 0x0001 — auch bei
        korrektem MAC, der CMD18-Datenpfad bricht hier ab. Das ist also kein
        Beleg für "Auth nötig". Mit block_count = 0 kommt 0x0000 samt echter
        MAC. Eine Key-Prüfung gehört deshalb in rpmb_read_counter (Typ 2).
        """
        nonce = os.urandom(16) if nonce is None else nonce
        frame = self.rpmb_frame(self.RPMB_READ_DATA, address=address,
                                block_count=block_count, nonce=nonce)
        r = self.rpmb_parse(self.rpmb_request(frame, address=address,
                                              timeout=timeout))
        r["nonce_ok"] = r["nonce"] == nonce
        return r

    def rpmb_result(self, timeout=10000):
        """Typ 5: Ergebnis der letzten Anfrage abholen."""
        nonce = os.urandom(16)
        frame = self.rpmb_frame(self.RPMB_RESULT, nonce=nonce)
        r = self.rpmb_parse(self.rpmb_request(frame, timeout=timeout))
        r["nonce_ok"] = r["nonce"] == nonce
        return r


# -- Ausgabe und Prüfungen ------------------------------------------------
def decode_extcsd(b):
    out = []
    for idx in sorted(FIELDS):
        out.append("  [%3d] %-28s = 0x%02x" % (idx, FIELDS[idx], b[idx]))
    sec = int.from_bytes(b[212:216], "little")
    out.append("  [212] %-28s = %d Sektoren = %.2f GB" %
               ("SEC_COUNT", sec, sec * 512 / 1e9))
    return "\n".join(out)


def print_device_info(info):
    print("Geräte-Info : %s" % info[:60].hex(" "))
    print("              Fertigungsdatum %s, Device-Code %s" %
          (info[8:23].decode("ascii", "replace"),
           info[24:32].decode("ascii", "replace")))


def print_verify_result(result):
    print("Geprüft    : %s (%d Rahmen)"
          % (fmt_size(result["bytes"]), result["frames"]))
    if result["file_bytes"] < result["bytes"]:
        print("Hinweis    : Datei ist kürzer (%d Byte); Rest als Nullen verglichen."
              % result["file_bytes"])
    if not result["bad_blocks"]:
        print("Ergebnis   : 0 abweichende Blöcke — Datei und Karte stimmen überein.")
        return
    print("Ergebnis   : %d abweichende Blöcke, ab LBA 0x%x"
          % (result["bad_blocks"], result["first_bad_lba"]))
    for ex in result["examples"]:
        print("   LBA 0x%08x  Byte +%3d: Datei 0x%02x, Karte 0x%02x"
              % (ex["lba"], ex["offset"], ex["file"], ex["card"]))


def err(message, hint=None):
    print("Fehler: %s" % message, file=sys.stderr)
    if hint:
        print("Hinweis: %s" % hint, file=sys.stderr)


def selftest():
    """Interne Prüfungen ohne Gerät; Rückgabe = Exit-Code."""
    failures = []
    count = {"n": 0}

    def check(name, cond):
        count["n"] += 1
        if not cond:
            failures.append(name)

    # Massendeskriptor Lesen
    d = T48.mass_descriptor(0x1234, 5)
    check("Lesedeskriptor Länge", len(d) == 40)
    check("Lesedeskriptor Opcode", d[0] == 0x0d and d[1] == 1)
    check("Lesedeskriptor Start-LBA",
          int.from_bytes(d[4:8], "little") == 0x1234)
    check("Lesedeskriptor Blockgröße", int.from_bytes(d[8:12], "little") == 512)
    check("Lesedeskriptor 32 Blöcke/Rahmen",
          int.from_bytes(d[12:16], "little") == 32
          and int.from_bytes(d[20:24], "little") == 32
          and int.from_bytes(d[24:28], "little") == 32)
    check("Lesedeskriptor Rahmenzahl", int.from_bytes(d[16:20], "little") == 5)
    check("Lesedeskriptor Richtung",
          int.from_bytes(d[28:32], "little") == 1
          and int.from_bytes(d[32:36], "little") == 1)

    # Massendeskriptor Schreiben
    w = T48.write_descriptor(0x200, 2)
    check("Schreibdeskriptor Opcode", w[0] == 0x1f)
    check("Schreibdeskriptor Richtung", int.from_bytes(w[28:32], "little") == 4)
    check("Schreibdeskriptor LBA", int.from_bytes(w[4:8], "little") == 0x200)

    # Grenzen der Deskriptoren
    try:
        T48.mass_descriptor(0, 0)
        check("Deskriptor-Grenze 0", False)
    except ValueError:
        pass
    try:
        T48.mass_descriptor(0, 0x10000)
        check("Deskriptor-Grenze 65536", False)
    except ValueError:
        pass

    # Einzelblockbefehle
    check("cmd_14 LBA 0", T48.cmd_14(0)[0] == 0x14
          and T48.cmd_14(0)[8] == 1)
    check("cmd_14 LBA 1", T48.cmd_14(1)[1] == 1 and T48.cmd_14(1)[8] == 2)
    check("cmd_15 1", T48.cmd_15(1)[8] == 1)

    # RPMB-Rahmen
    nonce = bytes(range(16))
    frame = T48.rpmb_frame(T48.RPMB_READ_COUNTER, nonce=nonce)
    check("RPMB-Rahmen Länge", len(frame) == 512)
    check("RPMB-Rahmen Typ", int.from_bytes(frame[510:512], "big") == 2)
    check("RPMB-Rahmen Nonce", frame[484:500] == nonce)
    answer = bytes(16) + frame
    parsed = T48.rpmb_parse(answer)
    check("RPMB-Parse Typ", parsed["type_be"] == 2 and parsed["type"] == 0x0200)
    check("RPMB-Parse Nonce", parsed["nonce"] == nonce)

    # Bereichsnamen und -grenzen
    check("Bereich user", parse_area("user") == 0)
    check("Bereich boot1", parse_area("BOOT1") == 1)
    check("Bereich 0x03", parse_area("0x03") == 3)
    try:
        parse_area("quatsch")
        check("Bereich ungültig", False)
    except ValueError:
        pass
    ext = bytearray(512)
    ext[212:216] = (0x01D1F000).to_bytes(4, "little")
    ext[226] = 32
    ext[168] = 32
    check("USER-Grenze", area_limits(ext, 0) == 0x01D1F000)
    check("BOOT-Grenze", area_limits(ext, 1) == 8192)
    check("RPMB-Grenze", area_limits(ext, 3) == 8192)
    check("Bereichswarnung",
          area_warning(ext, 0, 0x01D1F000, 1) is not None
          and area_warning(ext, 0, 0, 1) is None)

    # Profilbytes im BEGIN_TRANS: der Blob oben ist unverändert die Referenz
    check("BEGIN_TRANS Länge", len(BEGIN_TRANS) == 64)
    check("BEGIN_TRANS eMMC-Protokoll", BEGIN_TRANS[1] == 0x31
          and BEGIN_TRANS[2:4] == b"\x00\x00")
    check("BEGIN_TRANS Standardprofil 1,8 V / 4 Bit",
          BEGIN_TRANS[BEGIN_OFF_VOLT_LOW] == 0x01
          and BEGIN_TRANS[BEGIN_OFF_VOLT_HI] == 0x05
          and BEGIN_TRANS[BEGIN_OFF_VCCQ] == 0x01
          and BEGIN_TRANS[0x0c] == 0x54 and BEGIN_TRANS[0x3f] == 0x54)
    check("STATUS spiegelt BEGIN_TRANS[0:8]",
          status_packet() == bytes([0x39]) + BEGIN_TRANS[1:8])
    check("STATUS Standardprofil wie im Mitschnitt",
          status_packet() == bytes([0x39, 0x31, 0x00, 0x00, 0x01, 0x05, 0xa1, 0x00]))
    try:
        set_profile("3.3", 1)
        check("set_profile 3,3 V / 1 Bit (beide Spannungsbytes)",
              BEGIN_TRANS[BEGIN_OFF_VOLT_LOW] == 0x00
              and BEGIN_TRANS[BEGIN_OFF_VOLT_HI] == 0x05
              and BEGIN_TRANS[BEGIN_OFF_VCCQ] == 0x00
              and BEGIN_TRANS[0x0c] == 0x51 and BEGIN_TRANS[0x3f] == 0x51)
        check("STATUS folgt dem Spannungswechsel (Byte 4 = 0x00)",
              status_packet()[4] == 0x00 and status_packet()[5] == 0x05)
    finally:
        set_profile("1.8", 4)
    check("set_profile zurückgesetzt", BEGIN_TRANS == bytes([
        0x03, 0x31, 0x00, 0x00, 0x01, 0x05, 0xa1, 0x00,
        0x20, 0x00, 0x00, 0x00, 0x54, 0x00, 0x20, 0x00,
        0x00, 0x02, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00,
        0x03, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0xe5, 0x10, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x38, 0x08, 0x00, 0x00, 0x00, 0x00, 0x9e, 0x54,
    ]))

    total = count["n"]
    if failures:
        for name in failures:
            print("  FEHLER: %s" % name)
        print("%d Prüfungen, %d Fehler" % (total, len(failures)))
        return EXIT_ERROR
    print("%d Prüfungen, 0 Fehler" % total)
    return EXIT_OK


# -- Kommandozeile --------------------------------------------------------
def area_arg(text):
    try:
        return parse_area(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc))


def int_arg(text):
    try:
        return int(text, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "%r ist keine Zahl (dezimal oder 0x…)" % text)


def build_parser():
    p = argparse.ArgumentParser(
        prog="t48_mmc.py",
        description="XGecu-T48 als eMMC-Leser/Schreiber (macOS, pyusb).",
        epilog="Exit-Codes: 0 ok, 1 Fehler, 2 Aufruf, 3 kein Gerät, "
               "4 Timeout, 5 Vergleich abweichend, 130 abgebrochen.")
    p.add_argument("--version", action="version",
                   version="t48_mmc %s" % VERSION)
    p.add_argument("--timeout", type=float, default=10.0, metavar="SEK",
                   help="USB-Timeout je Rahmen/Kommando (Standard 10 s)")
    p.add_argument("--voltage", choices=("1.8", "3.3"), default="1.8",
                   help="VCCQ-Wahl im BEGIN-Paket; schreibt [0x04]/[0x05] und "
                        "[0x15] zusammen (Standard 1,8 V)")
    p.add_argument("--width", type=int, choices=(1, 4), default=4,
                   help="Busbreite im BEGIN-Paket (0x0c/0x3f = 0x51/0x54); "
                        "Standard 4 Bit")
    sub = p.add_subparsers(dest="cmd", metavar="<befehl>")

    s = sub.add_parser("info", help="Chip-Info und extCSD anzeigen")
    s.add_argument("--raw", action="store_true",
                   help="CID/CSD/extCSD zusätzlich roh ausgeben")

    s = sub.add_parser("block", help="einen 512-Byte-Block lesen "
                                     "(nur ein Read je Sitzung!)")
    s.add_argument("lba", nargs="?", type=int_arg, default=0)

    s = sub.add_parser("read", help="Bereich in eine Datei lesen")
    s.add_argument("area", type=area_arg)
    s.add_argument("path")
    s.add_argument("frames", nargs="?", type=int_arg, default=MASS_FRAMES)
    s.add_argument("start_lba", nargs="?", type=int_arg, default=0)

    s = sub.add_parser("dump", help="große Sicherung schreiben (fortsetzbar)")
    s.add_argument("area", type=area_arg)
    s.add_argument("path")
    s.add_argument("frames", type=int_arg)
    s.add_argument("start_lba", nargs="?", type=int_arg, default=0)
    s.add_argument("--chunk", type=int_arg, default=MASS_FRAMES,
                   help="Rahmen je Deskriptor (1..65535, Standard 256)")
    s.add_argument("--resume", action="store_true",
                   help="vorhandene Datei fortsetzen (Vielfaches von 16 KiB)")

    s = sub.add_parser("verify", help="Datei gegen Karte vergleichen (nur lesend)")
    s.add_argument("area", type=area_arg)
    s.add_argument("path")
    s.add_argument("start_lba", nargs="?", type=int_arg, default=0)
    s.add_argument("--frames", type=int_arg, default=None,
                   help="Rahmen (Standard: aus der Dateigröße)")
    s.add_argument("--chunk", type=int_arg, default=MASS_FRAMES)
    s.add_argument("--examples", type=int_arg, default=12,
                   help="höchstens so viele Abweichungen im Einzelnen zeigen")

    s = sub.add_parser("write", help="Datei schreiben (gesperrt)")
    s.add_argument("area", type=area_arg)
    s.add_argument("path")
    s.add_argument("start_lba", nargs="?", type=int_arg, default=0)
    s.add_argument("--verify", action="store_true",
                   help="nach dem Schreiben rücklesen und vergleichen")

    s = sub.add_parser("erase", help="Blöcke löschen (gesperrt)")
    s.add_argument("area", type=area_arg)
    s.add_argument("blocks", type=int_arg)
    s.add_argument("start_lba", nargs="?", type=int_arg, default=0)
    s.add_argument("--verify", action="store_true",
                   help="danach prüfen, ob der Bereich Nullen liefert")

    s = sub.add_parser("meta", help="Samsung-Metadaten bei LBA 0x100000 ansehen")

    s = sub.add_parser("rpmb",
                       help="RPMB-Anfragen (counter|read|result|key-program)")
    s.add_argument("what", nargs="?", default="counter",
                   choices=("counter", "read", "result", "key-program"))
    s.add_argument("value", nargs="?", type=int_arg, default=0)
    s.add_argument("blocks", nargs="?", type=int_arg, default=1)
    s.add_argument("--key", metavar="HEX", default=None,
                   help="32-Byte-Key als 64 Hex-Zeichen (nur key-program; "
                        "steht dann in Shell-History und Prozessliste)")
    s.add_argument("--key-file", metavar="PFAD", default=None,
                   help="Datei mit dem Key (bevorzugt: nicht in der History)")
    s.add_argument("--key-offset", type=int_arg, default=0,
                   help="Byte-Offset des 32-Byte-Keys in --key-file (Standard 0)")
    s.add_argument("--confirm-irreversible", action="store_true",
                   help="zusätzliche Freigabe für den dauerhaften Key (Typ 1)")

    s = sub.add_parser("resetcfg", help="PARTITION_CONFIG[179] setzen (gesperrt)")
    s.add_argument("value", nargs="?", type=int_arg, default=0x00)

    sub.add_parser("recover", help="USB-Reset ohne Umstecken versuchen")
    sub.add_parser("selftest", help="interne Prüfungen ohne Gerät")
    return p


def run_info(t, args, res):
    ext = res["extcsd"]
    print("T48-eMMC-Treiber %s" % VERSION)
    print_device_info(res["info"])
    print("Fähigkeiten : %s" % res["caps"].hex(" "))
    print("CID         : %s" % res["cid"].hex(" "))
    print("CSD         : %s" % res["csd"].hex(" "))
    print("Bereiche    : %s" % describe_areas(ext))
    print(decode_extcsd(ext))
    if ext[179] != 0x00:
        print("Warnung: PARTITION_CONFIG[179] = 0x%02x (erwartet 0x00). "
              "Vor Geräteeinbau mit 'resetcfg 0' korrigieren." % ext[179])
    if args.raw:
        print("extCSD roh  : %s" % ext.hex(" "))
    return EXIT_OK


def run_block(t, args, res):
    r = t.read_block(args.lba, timeout=int(args.timeout * 1000))
    print("Block 0x%x   : %d Byte, Nonce-Antwort %s"
          % (args.lba, len(r), r[500:516].hex(" ")))
    return EXIT_OK


def run_read(t, args, res):
    frames = args.frames
    if not 1 <= frames <= 0xffffffff:
        raise ValueError("frames muss >= 1 sein")
    warn = area_warning(res["extcsd"], args.area, args.start_lba, frames * 32)
    if warn:
        print("Warnung    : %s" % warn)
    need = frames * MASS_FRAME_DATA
    check_space(args.path, need)
    print("Bereich %02x (%s) ab LBA 0x%x: %s -> %s"
          % (args.area, area_name(args.area), args.start_lba,
             fmt_size(need), args.path))
    t0 = time.time()
    progress = Progress(frames, MASS_FRAME_DATA)
    written = t.dump(args.area, args.path, frames,
                     start_lba=args.start_lba,
                     timeout=int(args.timeout * 1000), progress=progress)
    elapsed = time.time() - t0
    print("Fertig      : %d Byte in %.2f s (%s/s)"
          % (written, elapsed, fmt_size(written / max(elapsed, 1e-9))))
    print("sha256      : %s" % hash_file(args.path))
    return EXIT_OK


def run_dump(t, args, res):
    frames = args.frames
    if frames < 1:
        raise ValueError("frames muss >= 1 sein")
    skip = 0
    if args.resume:
        if not os.path.exists(args.path):
            raise T48Error("Fortsetzen nicht möglich: %s existiert nicht"
                           % args.path)
        size = os.path.getsize(args.path)
        skip = size // MASS_FRAME_DATA
        rest = size % MASS_FRAME_DATA
        if rest:
            print("Hinweis    : Datei endet mitten im Rahmen; kürze um %d Byte."
                  % rest)
            os.truncate(args.path, skip * MASS_FRAME_DATA)
        if skip > frames:
            print("Hinweis    : Datei ist schon vollständig (%d Rahmen); "
                  "nichts zu tun." % skip)
            return EXIT_OK
    warn = area_warning(res["extcsd"], args.area, args.start_lba,
                        frames * 32)
    if warn:
        print("Warnung    : %s" % warn)
    need = (frames - skip) * MASS_FRAME_DATA
    check_space(args.path, need)
    print("Bereich %02x (%s) ab LBA 0x%x: %s -> %s%s"
          % (args.area, area_name(args.area), args.start_lba,
             fmt_size(frames * MASS_FRAME_DATA), args.path,
             (" (ab Rahmen %d)" % skip) if skip else ""))
    t0 = time.time()
    progress = Progress(frames, MASS_FRAME_DATA)
    written = t.dump(args.area, args.path, frames,
                     start_lba=args.start_lba, chunk=args.chunk,
                     timeout=int(args.timeout * 1000), progress=progress,
                     skip_frames=skip)
    elapsed = time.time() - t0
    fresh = (frames - skip) * MASS_FRAME_DATA
    print("Fertig      : %d Byte gesamt, %d Byte neu in %.1f s (%s/s)"
          % (written, fresh, elapsed, fmt_size(fresh / max(elapsed, 1e-9))))
    return EXIT_OK


def run_verify(t, args, res):
    if not os.path.exists(args.path):
        raise T48Error("Datei nicht gefunden: %s" % args.path)
    frames = args.frames
    if frames is not None and frames < 1:
        raise ValueError("--frames muss >= 1 sein")
    plan = (frames if frames is not None
            else (os.path.getsize(args.path) + MASS_FRAME_DATA - 1)
            // MASS_FRAME_DATA)
    warn = area_warning(res["extcsd"], args.area, args.start_lba, plan * 32)
    if warn:
        print("Warnung    : %s" % warn)
    print("Vergleich %02x (%s) ab LBA 0x%x: %s <- %s"
          % (args.area, area_name(args.area), args.start_lba,
             fmt_size(plan * MASS_FRAME_DATA), args.path))
    t0 = time.time()
    progress = Progress(plan, MASS_FRAME_DATA)
    result = t.compare_area(args.area, args.path, start_lba=args.start_lba,
                            frames=frames, chunk=args.chunk,
                            max_examples=args.examples,
                            timeout=int(args.timeout * 1000),
                            progress=progress)
    elapsed = time.time() - t0
    print("Dauer      : %.1f s (%s/s)"
          % (elapsed, fmt_size(result["bytes"] / max(elapsed, 1e-9))))
    print_verify_result(result)
    return EXIT_OK if not result["bad_blocks"] else EXIT_MISMATCH


def run_write(t, args, res):
    require_write_permission()
    if not os.path.exists(args.path):
        raise T48Error("Datei nicht gefunden: %s" % args.path)
    size = os.path.getsize(args.path)
    if size == 0 or size % 512:
        raise ValueError("Dateigröße muss ein positives Vielfaches von 512 sein "
                         "(%d Byte)" % size)
    blocks = size // 512
    warn = area_warning(res["extcsd"], args.area, args.start_lba, blocks)
    if warn:
        print("Warnung    : %s" % warn)
    print("ACHTUNG    : Schreiben in Bereich %02x (%s) ab LBA 0x%x: %s "
          "-> %s" % (args.area, area_name(args.area), args.start_lba,
                     fmt_size(size), args.path))
    t0 = time.time()
    progress = Progress(blocks, 512)
    # Programmieren braucht mehr Luft als Lesen: 1,5× das Kommando-Timeout.
    write_timeout = int(args.timeout * 1500)
    n = t.write_file(args.area, args.path, start_lba=args.start_lba,
                     timeout=write_timeout, progress=progress)
    print("Fertig      : %d Byte in %.1f s" % (n, time.time() - t0))
    if not args.verify:
        print("Hinweis    : Rückleseprüfung mit '--verify' oder mit dem "
              "Befehl 'verify' möglich.")
        return EXIT_OK
    frames = (blocks + 31) // 32
    print("Rücklesen und vergleichen …")
    result = t.compare_area(args.area, args.path, start_lba=args.start_lba,
                            frames=frames,
                            timeout=int(args.timeout * 1000),
                            progress=Progress(frames, MASS_FRAME_DATA))
    print_verify_result(result)
    return EXIT_OK if not result["bad_blocks"] else EXIT_MISMATCH


def run_erase(t, args, res):
    require_write_permission()
    blocks = args.blocks
    if blocks <= 0:
        raise ValueError("blocks muss > 0 sein")
    warn = area_warning(res["extcsd"], args.area, args.start_lba, blocks)
    if warn:
        print("Warnung    : %s" % warn)
    print("Lösche Bereich %02x (%s): %d Blöcke ab LBA 0x%x"
          % (args.area, area_name(args.area), blocks, args.start_lba))
    t.erase_area(args.area, blocks, start_lba=args.start_lba,
                 timeout=int(args.timeout * 1500))
    print("Fertig      : Bereich gelöscht.")
    if not args.verify:
        return EXIT_OK
    print("Prüfe auf Nullen …")
    frames = (blocks + 31) // 32
    result = t.compare_zeros(args.area, args.start_lba, blocks,
                             timeout=int(args.timeout * 1000),
                             progress=Progress(frames, MASS_FRAME_DATA))
    if not result["bad_blocks"]:
        print("Ergebnis   : alle %d Blöcke sind Nullen." % blocks)
        return EXIT_OK
    print("Ergebnis   : %d Blöcke ohne Nullen, ab LBA 0x%x"
          % (result["bad_blocks"], result["first_bad_lba"]))
    return EXIT_MISMATCH


def run_meta(t, args, res):
    # Samsung-Boot-Metadaten @ 0x20000000 = LBA 0x100000 (read-only)
    data = t.read_area(0x00, frames=4, start_lba=0x100000,
                       timeout=int(args.timeout * 1000))
    nz = [i for i, x in enumerate(data) if x][:8]
    print("USER @ LBA 0x100000: %d Byte, nonzero=%d, erste %s"
          % (len(data), sum(1 for x in data if x), nz))
    print(data[:64].hex(" "))
    return EXIT_OK


RPMB_RESULT_TEXT = {
    0x0000: "OK",
    0x0001: "allgemeiner Fehler (z. B. Zähler nicht 0 oder Auth fehlgeschlagen)",
    0x0002: "Authentifizierungsfehler (MAC falsch)",
    0x0003: "Zählerfehler",
    0x0004: "Adressfehler",
    0x0005: "Schreibfehler",
    0x0006: "Lesefehler",
    0x0007: "Key noch nicht programmiert",
    0x0008: "nicht unterstützt / Hardwarefehler",
}


def rpmb_result_text(code):
    return RPMB_RESULT_TEXT.get(code, "unbekannter Code")


def run_rpmb_key_program(t, args, res=None):
    # Drei Sperren: Schreibfreigabe, eigene Bestätigung, und der Controller
    # selbst nimmt Typ 1 nur bei Schreibzähler 0 an.
    require_write_permission()
    if not args.confirm_irreversible:
        raise T48Error(
            "Typ 1 ist unwiderruflich: --confirm-irreversible angeben. "
            "Vorher in einer eigenen Sitzung 'rpmb counter' prüfen "
            "(der Zähler muss 0 sein; hier läuft nur EIN 14/15-Read je Sitzung).")
    if args.key_file:
        with open(args.key_file, "rb") as f:
            raw = f.read()
        off = args.key_offset
        key = raw[off:off + 32]
        quelle = "%s[%d..%d]" % (args.key_file, off, off + 32)
    elif args.key is not None:
        key = bytes.fromhex(args.key.replace(":", "").replace(" ", ""))
        quelle = "--key"
    else:
        raise T48Error("Kein Key angegeben: --key <64 Hex> oder --key-file <Pfad>")
    if len(key) != 32:
        raise T48Error("Key muss 32 Byte haben, gefunden %d" % len(key))

    print("RPMB Typ 1 (Key programmieren) — unwiderruflich")
    print("  Quelle    : %s" % quelle)
    print("  Key-Hash  : %s… (SHA-256; der Key selbst wird nicht ausgegeben)"
          % hashlib.sha256(key).hexdigest()[:12])
    r = t.rpmb_program_key(key, timeout=int(args.timeout * 1000))
    print("  Result    : 0x%04x (%s)" % (r["result"],
                                        rpmb_result_text(r["result"])))
    print("  Nonce ok  : %s" % r["nonce_ok"])
    print("  Rahmenende: %s" % r["raw"][500:512].hex(" "))
    if r["result"] == 0x0000:
        print("Status      : angenommen. Der Zähler bleibt zunächst 0 (Typ 1")
        print("              zählt nicht). Sichtprüfung in einem NEUEN Aufruf:")
        print("              'rpmb counter' muss jetzt Result 0x0000 und eine")
        print("              echte MAC liefern statt 0x0007. 'rpmb read 0 1' taugt")
        print("              als Prüfung nicht: 0x0001 kommt dort immer, auch mit")
        print("              korrektem Key (block_count >= 1 = CMD18-Pfad).")
        return EXIT_OK
    if r["result"] == 0x0001:
        print("Status      : abgelehnt. Typische Ursache: Zähler ist nicht 0,")
        print("              also Key bereits gesetzt — dann ist hier nichts zu tun.")
    else:
        print("Status      : abgelehnt, siehe Result.")
    return EXIT_MISMATCH


def run_rpmb(t, args, res):
    if args.what == "counter":
        r = t.rpmb_read_counter(timeout=int(args.timeout * 1000))
        print("RPMB Typ 2 (Zähler)")
        print("  Result    : 0x%04x (%s)" % (r["result"],
                                            rpmb_result_text(r["result"])))
        print("  Zähler    : %d (0x%08x)" % (r["counter"], r["counter"]))
        print("  Nonce ok  : %s" % r["nonce_ok"])
        print("  MAC       : %s" % r["mac"].hex(" "))
        if r["mac"] == bytes(32):
            print("              ohne MAC — mit dieser Karte ist kein Key-Test")
            print("              möglich (0x0007 = Key nie programmiert).")
        elif r["result"] == 0x0000:
            print("              echte MAC — dieser Rahmen ist das Orakel: Key-"
                  "Kandidat mit HMAC über frame[228:512] prüfen, offline.")
        print("  Antwort   : SHA-256 %s… (über alle 528 Byte, zum Wiederfinden "
              "eines gespeicherten Rahmens)"
              % hashlib.sha256(r["raw"]).hexdigest()[:16])
    elif args.what == "read":
        r = t.rpmb_read_data(args.value, args.blocks,
                             timeout=int(args.timeout * 1000))
        print("RPMB Typ 4 (Lesen ohne MAC), Adresse %d, %d Blöcke"
              % (args.value, args.blocks))
        print("  Result    : 0x%04x (%s)" % (r["result"],
                                            rpmb_result_text(r["result"])))
        if args.blocks >= 1 and r["result"] == 0x0001:
            print("  Hinweis   : 0x0001 heißt hier NICHT 'Auth nötig' — mit")
            print("              block_count >= 1 scheitert der CMD18-Datenpfad am")
            print("              Programmer immer, auch bei korrekter MAC.")
            print("              Key-Prüfung geht nur über 'rpmb counter'.")
        print("  Nonce ok  : %s" % r["nonce_ok"])
        print("  Daten     : %s" % r["data"][:64].hex(" "))
    elif args.what == "key-program":
        return run_rpmb_key_program(t, args)
    else:
        r = t.rpmb_result(timeout=int(args.timeout * 1000))
        print("RPMB Typ 5 (Ergebnis)")
        print("  Result    : 0x%04x" % r["result"])
        print("  Nonce ok  : %s" % r["nonce_ok"])
    return EXIT_OK


def run_resetcfg(t, args, res):
    require_write_permission()
    print("Setze PARTITION_CONFIG[179] = 0x%02x …" % args.value)
    t.write_extcsd_byte(179, args.value)
    ext = t.read_extcsd()
    print("Neuer Wert  : PARTITION_CONFIG=0x%02x" % ext[179])
    return EXIT_OK


def run_recover(t, args, res):
    print("USB-Reset ausgeführt; Gerät antwortet wieder.")
    return run_info(t, argparse.Namespace(raw=False), res)


def dispatch(t, args, res):
    handlers = {
        "info": run_info,
        "block": run_block,
        "read": run_read,
        "dump": run_dump,
        "verify": run_verify,
        "write": run_write,
        "erase": run_erase,
        "meta": run_meta,
        "rpmb": run_rpmb,
        "resetcfg": run_resetcfg,
        "recover": run_recover,
    }
    return handlers[args.cmd](t, args, res)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return EXIT_USAGE
    if args.cmd == "selftest":
        return selftest()
    if args.timeout <= 0:
        err("--timeout muss > 0 sein")
        return EXIT_USAGE
    if args.voltage != "1.8" or args.width != 4:
        set_profile(args.voltage, args.width)
        print("Profil: VCCQ %s V (BEGIN[0x04]=0x%02x, [0x15]=0x%02x), Bus %d Bit "
              "(0x0c/0x3f=0x%02x)"
              % (args.voltage, BEGIN_TRANS[BEGIN_OFF_VOLT_LOW],
                 BEGIN_TRANS[BEGIN_OFF_VCCQ], args.width,
                 BEGIN_TRANS[BEGIN_OFF_WIDTH[0]]))

    t = None
    try:
        t = T48()
        if args.cmd == "recover":
            print("Versuche USB-Reset …")
            t.usb_reset()
        res = t.initialize()
        return dispatch(t, args, res)
    except T48NotFound as exc:
        err(exc, exc.hint)
        return EXIT_NO_DEVICE
    except T48Timeout as exc:
        err(exc, exc.hint)
        return EXIT_TIMEOUT
    except T48Error as exc:
        err(exc, exc.hint)
        return EXIT_ERROR
    except ValueError as exc:
        err("Ungültige Eingabe: %s" % exc)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\nAbgebrochen. Eine unvollständige Sicherung lässt sich mit "
              "'dump … --resume' fortsetzen.", file=sys.stderr)
        return 130
    finally:
        if t is not None:
            t.close()


if __name__ == "__main__":
    sys.exit(main())
