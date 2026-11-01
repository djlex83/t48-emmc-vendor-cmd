[English](rpmb-key-findings.md) · **Deutsch** · [中文](rpmb-key-findings.zh.md)

# RPMB-Key — was zwei Videos und das OP-TEE-Issue hergeben

**Status: Aussagen Dritter, nicht unsere eigenen Messungen.** Alles Folgende stammt aus
Tutorial-Videos oder einem öffentlichen Issue-Tracker, nicht von Hardware, die wir selbst
gefahren haben. Es steht hier, weil es unsere Suchstrategie bestimmt — nicht weil es
belegt ist.

---

## Video 1 — UFI eMMC ToolBox, Samsung moviNAND

* Der RPMB-Key **steckt im Controller-Firmware-Dump**. `Read eMMC Fw` liest ihn heraus,
  der angezeigte Wert wird dann als Key in `Enter RPMB Key` eingetragen. Das ist für
  Samsung der Weg zum Klartext-Key — mit dem User-Bereich hat er nichts zu tun.
* `Read eMMC Fw` ist **nur lesend** — keine Backup-Pflicht, kein Schreibrisiko.
* Der **Counter lässt sich nicht direkt setzen.** Er kommt nur über einen
  RPMB-Frame-Write gegen die alte RPMB-Partition zurück.
* Der Counter ist **nicht bootkritisch**: Das Video bootet mit Counter 0. Verloren gehen
  die alten verschlüsselten Daten, nicht das Gerät.
* Der Original-IC bleibt unangetastet, experimentiert wird auf einer zweiten Karte.
  Genau diese Regel gilt bei uns.

## Video 2 — eine zweite Box, Handy-Reparatur

* Die Box hat ein `Read RPMB Key`, das den Key **direkt aus der intakten Karte** liest
  (Samsung). Danach `Write RPMB Key` auf eine blanke Karte → Status
  `Legacy write protection mode`, Counter 0.
* Anschließend meldet die Karte trotzdem `Device not boot inbuilt` /
  `Partition configuration 0` / `User area invalid for boot`. Das ist ein vom Key
  **unabhängiger** Bootblocker und liegt allein in der extCSD-Partitionskonfiguration.
  Erst nach dieser Korrektur kommt sie in den EDL-Modus und flasht weiter.
* Konsequenz: Der Key allein genügt nicht — `PARTITION_CONFIG` muss zum Gerät passen,
  sonst bootet auch eine korrekt provisionierte Karte nicht.

## OP-TEE Issue #4019

* Der Key ist **pro eMMC eindeutig** und wird von der TEE erzeugt
  (`CFG_RPMB_WRITE_KEY=y` ist ein Factory-Build, der ihn einmal in die Karte schreibt).
  Danach erkennt `tee_rpmb_init()`, dass er bereits programmiert ist.
* Der Key wird **weder rückgelesen noch neu abgeleitet**; das Issue nennt weder Fuses
  noch OTP noch HUK noch Controller-Firmware als Quelle.
* Die einzige beschriebene Exposure: Die Normal World kann die Secure World zum
  Überschreiben bewegen — dann läuft der Key im Klartext über den Bus.
* „once you have the RPMB key the security of RPMB is gone."

## Was das für unser negatives Ergebnis bedeutet

Unsere eigenen Versuche fanden nichts: Der Key liegt weder im User-Dump noch ist er aus
CID/CSD ableitbar — **25.165.728 HMAC-Prüfungen ohne Treffer**. Die Quelle liegt
außerhalb beider. Bei Samsung im Controller-Firmware-Bereich; bei MediaTek vermutlich im
SoC/TEE, was aber **nicht** belegt ist.

Beide Quellen oben zeigen in dieselbe Richtung: Der Samsung-Key ist ein
controller-seitiges Geheimnis, und der Vendor-Weg dorthin ist ein Firmware-Read — keine
Struktur im User-Bereich.

## extCSD der vorliegenden Karten (gelesen, nie geschrieben)

| Feld | Wert | Bedeutung |
|---|---|---|
| EXT_CSD_REV | 0x08 | eMMC 5.1 |
| SEC_COUNT | 30535680 | 15,63 GB = 0x3A3E00000 (deckt den KD-Dump genau ab) |
| BOOT_SIZE_MULT | 0x14 (20) | 2560 KiB = 2,5 MiB je Boot-Partition |
| RPMB_SIZE_MULT | 0x1F (31) | 3968 KiB = 3,875 MiB RPMB |
| PART_SETTING_COMPLETED | 0x00 | Partitionierung **nicht** irreversibel gesperrt |
| PARTITION_CONFIG | 0x48 | BootEnable = **BOOT2**, Access = BOOT1 |
| BOOT_BUS_WIDTH | 0x00 | 1 Bit, kein High-Speed-Boot |
| BOOT_WP / WR_REL | 0x00 | keine Boot-Write-Protect-Flags |

Betroffen: beide Sony KD-49XD7005 und beide Philips 65PUS810212. Sie unterscheiden sich
nur in `0xFE` (Karten-Firmware-Version) und `0x10C`/`0x10D` — die Werkskonfiguration ist
über alle hinweg identisch.

**Konsequenz für den Schreibplan:** Das Gerät bootet von **BOOT2**. BOOT2 (2,5 MiB) muss
also geschrieben werden, sonst startet es unabhängig vom RPMB-Zustand nicht.
`PART_SETTING_COMPLETED` bleibt `0` — das Setzen auf `1` wäre **irreversibel** und laut
den Quellkarten nicht nötig.
