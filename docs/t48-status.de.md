[English](t48-status.md) · **Deutsch** · [中文](t48-status.zh.md)

# T48 / eMMC — Standaufzeichnung

Alles hier ist aus unseren eigenen USB-Mitschnitten und Kartenlesungen belegt, sofern
nicht ausdrücklich als Vermutung markiert. Geräte-Seriendaten (rohe CID) sind entfernt;
Kartenmodell und Die-Revision bleiben, weil sie für sich genommen nicht identifizierend
sind.

---

## 1. Karte

| Feld | Wert |
|---|---|
| Modell | Samsung **KLMAG1JENB-B041**, 16 GB, eMMC 5.1 |
| MID / PNM | 0x15 (Samsung) / **…JNB4R**, Produktionsdatum 5-2017 |
| EXT_CSD_REV | 8 (MMC 5.1) |
| USER | 14 910 MB, SEC_COUNT 0x01D1F000 = 30 535 680 Blöcke |
| BOOT1 / BOOT2 / RPMB | je 4 MB |
| RPMB | mit Authentifizierungs-Key geschützt, Writer-Counter 331 524 |
| PARTITION_CONFIG (EXT_CSD[179]) | 0x00 nach unserem Byte-Schreiben (vorher 0x78, von einem früheren Werkzeuglauf hinterlassen) |

`PARTITION_CONFIG` wurde während der Bereichsprobe per CMD6-Byte-Schreiben
(`27 46 00 00 00 00 b3 03`) auf `0x00` gesetzt (Zugriff USER, Boot-Enable aus). Dieser
Zustand ist für den Einbau korrekt. Andere später gelesene Karten zeigten `0x48` — die
Werte stammen von verschiedenen Karten zu verschiedenen Zeitpunkten, siehe
`rpmb-key-findings.de.md`.

## 2. Was mit der Karte passiert ist

* `BOOT1.BIN` und `BOOT2.BIN` (je 4 MB) wurden zurückgeschrieben, 2 × 4 MB, fehlerfrei,
  danach 8 MB Rückleseprüfung.
* **User-Bereich gesichert und leer:** vollständiger Read über den eigenen Treiber,
  15 634 268 160 Byte, ~11,8 MB/s. `find_metadata.py` fand **0 belegte 4-KiB-Blöcke**,
  keine CID-/VCT0-/RPMB-Treffer — der gesamte User-Bereich dieses Dies ist Null.
* Folge für den RPMB-Key: Auf **diesem** Die gibt es keinen Samsung-Metadatenblock und
  damit keinen Key im User-Bereich. Der Metadaten-Weg (andere Karte, KMDP6001DB-B425)
  ist hier nicht anwendbar.

### 2.1 Die zweite Karte im Sockel („JTD4R")

* Gleiche Kapazität und Revision, `PARTITION_CONFIG` 0x00.
* User-Bereich **mit echten Daten**: LBA 0 ist ein ARM-Bootvektor (`71 00 00 ea …`),
  Partitionen ab 0x40000, 0xFF-Füllung bei 0x100000, Code ab 0x800000. Im Image tauchen
  MediaTek-DRM-Strings wie `MTDRM_RPMBLoadMacKey` auf.
* Metadatensuche **negativ**: keine CID in irgendeiner Byte-Ordnung, kein
  „Boot Identification". Die `VCT0`- und `RPMB`-Treffer liegen in Nutzdaten
  (Base64-Strings, die MTK-DRM-Bibliothek).
* **Kein MBR / GPT / PGPT:** LBA 0 ist bereits ein Bootloader
  (`MTK/DTV/ROMCODE/MSDCBOOT`). Das Layout kommt aus dem Loader, nicht aus einer
  Partitionstabelle.
* Plattform: MediaTek DTV, Strings „Preloader T8032", „PH7M_EU_5596", Build-Datum
  8. November 2021.
* Die MTK-DRM-Bibliothek lädt den Key **über RPMB** (`MTDRM_RPMBLoadMacKey`); er ist
  nicht im Image gespeichert. Auch das Geräte-Image liefert also keinen Key.

## 3. T48-USB-Protokoll (aus den Mitschnitten)

Rahmen: Kommandos `OUT 0x01` → Antwort `IN 0x81`; Nutzdaten `OUT 0x02` / `IN 0x82`.

**Initialisierung:** `00` (Info, ×2) · `24 f0` / `24 e0` / `24 f1` (Session) · `3e 01` ·
`03` (64 B, BEGIN_TRANS) · `39` (Status) · `21` (Fähigkeiten) · `05` CID · `06` CSD ·
`08 48 00 02` extCSD · `04` END_TRANS.

**extCSD-Antwort:** 528 Byte = 8 Byte Kopf + 512 Byte extCSD + 8 Byte Status;
`extCSD[i] = buf[i+8]`, geprüft an EXT_CSD[162]=01, [179]=0x48, [192]=8,
[212..215]=0x01D1F000.

**Einzelblock lesen** (aus dem Mitschnitt verifiziert):

```
27 46 00 00 00 03 b3 01             Pipe-Setup
14 00 00 00 00 00 00 00 01 00 00 02 adressieren (Blockzahl 1)
OUT 512 B auf Pipe 0x02             Steuerpuffer: Nullen, Token bei 484–499,
                                    Byte 511 = 0x02
15 00 00 02 00 00 00 00 01 00 00 02 lesen
IN 0x82 (max 520) → 528 Byte        16 Byte Kopf + 512 Byte Rahmen
```

**Token-Kette:** Der Host erzeugt 16 Zufallsbytes pro Session und muss in jeder weiteren
Anfrage die 16 Bytes wiederholen, die der Programmer zuletzt zurückgegeben hat. Ohne
dieses Echo wartet die Programmer-Firmware und hängt; nur physisches Umstecken hilft.

**Massenstrom:** 40-Byte-Deskriptor, Opcode **`0d` = Lesen**, **`1f` = Schreiben**:

| Offset | Wert | Bedeutung |
|---|---|---|
| +0 | 0x0d | Opcode Lesen |
| +1 | 1 | Blockmodus (LBA in 512-B-Blöcken) |
| +4 | LBA | **Startadresse** (`(byte_adresse>>9) \| (hoch<<23)`) |
| +8 | 512 | Blockgröße |
| +12 | 32 | Blöcke je 16-KiB-Rahmen |
| +16 | Rahmenzahl | Anzahl der 16400-Byte-Rahmen im Strom |
| +20 | 32 | Adressschritt je Rahmen |
| +24 | 32 | Blöcke je Rahmen |
| +28 | 1 / 4 | Lesen / Schreiben |
| +32 | 1 | Konstante aus dem eMMC-Init-Pfad |

- Ein Dump liest **16400 Byte von Pipe 0x82**. Die 0x10040-Variante auf Pipe 0x81 ist
  der Blank-Check-Pfad, nicht der Dump.
- Ein Rahmen wird nur akzeptiert, wenn `frame[0] & 0x7FFFFFFF == 0`; sonst bricht das
  Herstellerwerkzeug mit „Error code / Status reg" ab.
- Unser früherer Eigenbau-Deskriptor setzte +4 immer auf 0. Das ist im Treiber korrigiert
  (`mass_descriptor(start_lba, frames)`).

**Schreibpfad** (aus dem Herstellerbinary rekonstruiert, am Gerät verifiziert):

- Deskriptor `1f 01 …`, +28 = 4, Felder sonst wie beim Lesen.
- Rahmen von 16400 Byte: Kopfbyte 0, +4 laufende LBA (Schritt 32 Blöcke), +8 = 512,
  +12 = 32, ab +16 die 16 KiB.
- Nach jedem vollen 1-MB-Block trägt der **erste Rahmen der nächsten Gruppe**
  (Rahmen 64, 128, …) Kopfbyte **2**; danach liest der Host 64 Byte von `0x81` und
  wertet Byte 0 als Fehlercode.
- Abschluss: STATUS `0x39` senden, 32 Byte von `0x81` lesen. Byte 0 = 0x02 bedeutet
  „EMMC Running TimeOut"; sonst bilden u16@+2 / u32@+4 den Fehlertext.
- Abbruch/Fehler: Rahmen mit Kopfbyte **1** senden, dann derselbe Abschluss.

**Löschen (Opcode 0x0e):** 16-Byte-Kommando, Byte 0 = `0e`, Bytes 4–7 = Start-LBA,
Bytes 8–11 = Ende-LBA **inklusiv**. Antwort: 8 Byte von `0x81`, Byte 1 = Fehlercode. Vor
jedem Block prüft das Werkzeug per CMD13 (`0x4c`) den Kartenstatus und pollt, bis der
Bereich nicht mehr beschäftigt ist.

Schreiben und Löschen wurden **am Gerät verifiziert** (BOOT1, blank):

| Test | Ergebnis |
|---|---|
| Schreiben 1 MB (64 Rahmen) | 1 048 576 Byte zurückgelesen, **0 Abweichungen** |
| Schreiben 4 MB (256 Rahmen, 3 × 1-MB-Quittung) | 4 194 304 Byte, **0 Abweichungen**, Rahmen 64 korrekt |
| Löschen 2048 Blöcke (1 MB) | Rückleseprobe: 0 Nicht-Null-Bytes |
| Löschen 8192 Blöcke (4 MB) | Rückleseprobe: 0 Nicht-Null-Bytes |

Weiterhin durch `T48_ALLOW_WRITE=1` gesperrt, damit kein Skript versehentlich schreibt.

### 3.2 Bereichsauswahl

Die Bereichsauswahl läuft über die PARTITION_ACCESS-Bits in EXT_CSD[179]:
`27 46 00 00 00 <value> <index> <access>`, access 1 = Bits setzen, 2 = löschen,
3 = Byte schreiben.

| Bereich | Kommandofolge |
|---|---|
| USER | `27 46 00 00 00 07 b3 02` (Bits 0..2 löschen) |
| BOOT1 | `… 07 b3 02`, dann `27 46 00 00 00 01 b3 01` |
| BOOT2 | `… 07 b3 02`, dann `27 46 00 00 00 02 b3 01` |
| RPMB | `… 07 b3 02`, dann `27 46 00 00 00 03 b3 01` |

**Korrektur:** Eine frühere Treiberversion setzte nur die Bits, ohne vorher zu löschen.
Bei aktiver Boot-Partition blieben die Zugriffsbits unverändert — ein „USER"-Read konnte
in Wahrheit BOOT1 lesen. `setup_area()` löscht jetzt zuerst.

### 3.3 Der RPMB-Bereich liefert Fehlerrahmen

Jeder 512-Byte-Block eines Bereich-3-Reads endet bei Offset 508 mit `00 01 00 00`. Das
ist das RPMB-Result-Feld **0x0001 = General Failure**: ohne Authentifizierung liefert die
Karte in jedem 16-KiB-Block denselben Fehlerrahmen, deshalb sehen alle Bereich-3-Dumps
gleich aus. Es ist kein Adressierungsfehler.

Gegenprobe im Herstellerwerkzeug: Beide RPMB-Lesepfade bauen dieselbe Anfrage — Typ 4
(authentifiziertes Lesen), Nonce gesetzt, aber **MAC-Bytes Null**. Das Werkzeug liest
RPMB also unauthentifiziert; auf einer Karte mit Key kommt zwangsläufig 0x0001 heraus.
Der einzige Pfad mit einem Key ist der „Key programmieren"-Pfad (Typ 1) — der **setzt**
einen Key, liest keinen. Ein Key-Read existiert in dieser Software nicht.

### 3.4 RPMB-Frame-Schicht im Treiber (am Gerät geprüft)

Der 528-Byte-Antwortrahmen des 14/15-Pfads ist **16 Byte Kopf + 512 Byte RPMB-Frame**.
Unsere frühere Notiz „500 Byte Daten + 16-Byte-Token" war falsch: Das beobachtete
„Token-Echo" bei Byte 500 ist das JEDEC-Nonce-Feld.

| Offset | Feld | Länge |
|---|---|---|
| 0–195 | Stuff (Nullen) | 196 |
| 196–227 | MAC | 32 |
| 228–483 | Daten | 256 |
| 484–499 | Nonce (wird zurückgegeben) | 16 |
| 500–503 | Schreibzähler (nur Antwort) | 4 |
| 504–505 | Adresse | 2 |
| 506–507 | Blockzahl | 2 |
| 508–509 | Result | 2 |
| 510–511 | Request/Response-Typ | 2 |

Big-endian — **mit einer am T48 gemessenen Ausnahme**: das Typfeld kommt byte-verdreht
zurück (Typ 2 → `02 00`), deshalb liefert `rpmb_parse()` sowohl `type` als auch `type_be`.

Gemessen:

| Anfrage | Ergebnis |
|---|---|
| Typ 2 Counter | Result 0x0000, Zähler **33 638** (0x00008366), Nonce korrekt zurück |
| Typ 4 Lesen, Adresse 0, MAC = 0 | Result **0x0001**, restlicher Rahmen leer, Nonce **nicht** zurückgegeben |
| Kopffeld | Byte 5 des 16-Byte-Kopfes = 0x09; Bedeutung noch unklar |

CLI: `t48_mmc.py rpmb counter` · `rpmb read <adresse> [blöcke]` · `rpmb result`. Wegen
der Ein-Read-pro-Sitzung-Regel gilt: **eine RPMB-Anfrage pro Prozessaufruf**. Ein
Typ-3-Schreibpfad ist bewusst nicht implementiert — er braucht den Key, den wir nicht
haben.

## 4. Firmware-Update (FFU) — für den T48 ausgeschlossen

* Das Herstellerwerkzeug enthält **keine** Strings zu FFU, `EFAC60FC`/`CBAD1160`,
  CMD60/CMD62 oder Vendor-Commands. „Reflash firmware" betrifft nur die
  Programmer-Firmware.
* Der `cmp r12b, 8`-Pfad und das CMD60-Magic existieren ausschließlich im
  UFPI-Dongle-Code.
* **Der T48 kann kein eMMC-Firmware-Update.** Ein passendes Image existiert, lässt sich
  über diesen Programmer aber nicht einspielen.

### 4.1 Der Referenzablauf für FFU (aus EasyJTAG/UFPI, für ein späteres Herstellerwerkzeug)

Vorbedingungen: `EXT_CSD_REV` (Byte 192) = 8 und ein **Controller-Firmware-Image** einer
baugleichen Karte (nicht das Geräte-ROM).

1. **Freischalten:** CMD60 `0xEFAC60FC`, dann CMD60 `0xCBAD1160`.
2. **Optionales Löschen:** CMD35 Arg 0 → CMD36 Arg 0 → CMD38, Timeout 120 s.
3. **Schreiben:** CMD23 mit der Größe in Sektoren → CMD25 über den gesamten Bereich;
   danach warten.
4. **Prüfen:** CMD23 → CMD18 liest alles zurück, blockweiser `memcmp`.
5. **Reset:** CMD0 mit dem gespeicherten Argument, 15 s warten, dann Reinit mit 1 Bit.

**Risiko — vor jedem Versuch lesen:**

* Schritt 2 löscht mit **Gruppenindex 0**. Greift die Freischaltung (Schritt 1) nicht,
  landet das im **User-Bereich** — der riskanteste Eingriff in diesem ganzen Projekt.
  Nur mit vollständiger Sicherung und nur auf einer entbehrlichen Karte.
* Ein FFU braucht Controller-Firmware **einer baugleichen Karte**, nicht das
  Android-/Tizen-ROM. Für unsere 16-GB-Karte gibt es **keinen exakten Treffer** in der
  verfügbaren Datenbank, nur eine 32-GB-Variante. Nicht ungeprüft verwenden.

**Verhältnis zum RPMB-Key:** Ein FFU schreibt Controller-Firmware; es **liest keinen
Key**. „Neuen Key programmieren" funktioniert nur, solange RPMB **noch unprogrammiert**
ist (Counter 0). Unsere Karte steht auf 33 638, RPMB ist also programmiert; ein neuer
Key lässt sich dort nicht frei wählen, und „Reset RPMB" würde den RPMB-Inhalt zerstören.
Ob ein FFU den RPMB-Zustand selbst zurücksetzt, ist **nicht belegt** — nicht darauf
verlassen.

## 4a. Algorithmusdateien (`.alg`) — Container entschlüsselt

Bestand: 354 Dateien, Familien `EMMC_41_18` … `EMMC_54_33`, `NAND_xx`, `SPI25Fxx`,
`28F32Pxx`, `TTL1` und weitere. **Es wird hier keine `.alg`-Datei veröffentlicht.**

| Offset | Inhalt |
|---|---|
| 0x000 | 32 Byte ASCII-Name („EMMC211210", „EMMC", …) |
| 0x020 | 256 Byte Beschreibung (bei allen vorliegenden leer) |
| 0x120 | 4 DWORD Kopfwerte (hier alle 0) |
| 0x130–0x21F | Nullfüllung |
| 0x220 | DWORD **0x0005327C**, in allen 354 Dateien identisch |
| 0x224 | DWORD **Prüfsumme**, Little-Endian |
| 0x228 | 16 Byte `FF` |
| 0x238 | Magic `99 55 66 AA`, danach Payload |

**Prüfsumme (geknackt, 354/354 Dateien stimmen):** CRC-32 reflektiert, Poly `0xEDB88320`,
Init `0xFFFFFFFF`, **ohne Final-XOR** („JAMCRC") über alle Bytes **ab 0x228 bis
Dateiende**. In Python: `(zlib.crc32(d[0x228:]) ^ 0xFFFFFFFF) & 0xFFFFFFFF`.

**Laden und Upload:** Der Loader akzeptiert bis **98 336 Byte** Payload, liest ab 0x220 in
einen statischen Puffer und sendet dann 8 Byte `{0x26, 0x00, 0x00, 0x00, <Länge>}` auf
**EP 0x01 OUT**, wartet 100 ms und schickt den Puffer ab 0x220. Das `.alg` wird also
**unverändert an den Programmer übertragen und dort ausgeführt**. Der Dateiname ist ein
Familienpräfix (`EMMC_`, `NAND_`, `VGA_`, …) + Chipindex hex + `_33`/`_18` bei eMMC.

**Payload:** ein 16-Bit-Wortstrom, Little-Endian, ~22 % Nullwörter; die ersten 32 Bytes
sind über **alle** Familien identisch (gemeinsamer Prolog). Wir haben alle 354 Dateien
nach den Byte-Mustern der FFU-Konstanten durchsucht: **0 Treffer**. Die eMMC-`.alg`
sind Programmer-Code, kein MMC-Kommandostrom.

**Für unseren Treiber nicht nötig:** Lesen/Schreiben/Löschen laufen über die eingebauten
Firmware-Deskriptoren (`0d`/`1f`/`0e`). Das Herstellerwerkzeug lädt das `.alg` zusätzlich,
weil der Programmer die chip-spezifischen Abläufe daraus ausführt.

## 5. Nächste Schritte

Am Gerät erledigt: Adressfeld geprüft; vollständige User-Sicherung (alles Nullen);
`PARTITION_CONFIG` zurückgesetzt; Schreiben und Löschen byte-identisch verifiziert;
zweite Karte gesichert und offline ausgewertet; RPMB-Frame-Schicht gebaut und gemessen;
`.alg`-Container entschlüsselt.

Treiber-Testserie: `py_compile` sauber, `selftest` 25 Prüfungen / 0 Fehler; `read`
1 Rahmen; `dump --resume` ergänzt nur den fehlenden Rahmen; `verify` meldet 0 abweichende
Blöcke und bei einem gekippten Byte rc 5 mit der genauen Fundstelle; Schreiben/Löschen
verweigern ohne `T48_ALLOW_WRITE=1`; Argumentfehler liefern rc 2.

**Offen:**

1. **RPMB-Key:** auf diesem Die nicht über den User-Bereich zu bekommen. Verbleibend nur
   die Herstellerseite — eine EasyJTAG-Box mit dem Samsung-BootTrick oder UFPI (`0x93`),
   beides Windows plus Hardware, die wir nicht besitzen. Der T48 kann ihn nachweislich
   nicht lesen.
2. **FFU:** Der Referenzablauf ist dokumentiert (§4.1). Die Ausführung braucht
   EasyJTAG/UFPI und ein passendes Controller-Firmware-Image; für unsere 16-GB-Karte
   fehlt ein exakter Treffer.
3. **Weiterleitung:** Ob der T48-Bitstream CMD60/CMD62 überhaupt durchreicht, ist
   weiterhin unbewiesen — siehe `../WEITERE-WEGE.md` und Issue #1.
