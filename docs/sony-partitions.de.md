[English](sony-partitions.md) · **Deutsch** · [中文](sony-partitions.zh.md)

# Sony-DTV-Partitionslayout — Befunde

Zusammenfassung dessen, was wir aus einem Sony-DTV-Firmware-Paket
(`sony_dtv0FA60A0AA0AA_…pkg`) und aus Karten-Dumps bestimmt haben.
**Nur Analyse — es werden hier keine Firmware-Bytes veröffentlicht.**

Konfidenz-Labels: *bestätigt* = in unserem eigenen Parsing verifiziert;
*aus Notizen* = in früheren Sitzungen festgehalten und hier nicht erneut geprüft.

---

## Was das Firmware-Paket enthält

* **Bestätigt:** ein Container mit 51 Partitionen, `p1` … `p51`. Auf dem Gerät gibt es
  **kein GPT und kein MBR** — das Layout ist von der Firmware selbst definiert, nicht
  durch eine Standard-Partitionstabelle auf der Karte.
* **Aus Notizen:** die benannten Mounts, die wir zugeordnet haben, sind

  | Partition | Mount | Dateisystem |
  |---|---|---|
  | p4 | `/perm` | ext4 |
  | p13 | `/linux_rootfs` | — |
  | p17 | `/3rd` | SquashFS |
  | p44 | `/system` | — |

  Partitionsnummern und Mount-Namen sind das, was unser Parser ausgegeben hat. Diese
  Tabelle ist eine Spur, keine Spezifikation.

## Warum das für die Reparatur zählt

Der USB-Updater schreibt im **Bootloader-Kontext**, wo der SoC bereits über alle
Zugriffe verfügt, die er braucht. Deshalb braucht ein reparierter Fernseher **keinen**
RPMB-Key: Der Update-Pfad verlangt von uns keine Authentifizierung von außen.

Der RPMB-Key wird erst relevant, wenn man RPMB-authentifizierte Daten **von außerhalb
des Geräts** schreiben will — ein Bankplatz-Szenario, keine Reparatur.

## Was wir nicht getan haben

* Wir haben weder das Paket noch ein extrahiertes Partitions-Image noch einen Karten-Dump
  veröffentlicht. Das ist urheberrechtlich geschütztes Material Dritter. Siehe
  `../LEGAL.de.md`.
* Wir haben nicht versucht, die Integritätsprüfungen des Updaters zu verändern oder zu
  umgehen.

## Reproduktion

Das Paket lässt sich mit einem Container-Parser nur lesend scannen; unsere Skripte liegen
im Projektarbeitsverzeichnis, sind hier aber nicht enthalten, weil sie direkt auf dem
Firmware-Paket arbeiten.
