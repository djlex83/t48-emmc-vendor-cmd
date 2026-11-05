[English](README.md) · **Deutsch** · [中文](README.zh.md)

# Samsung-eMMC-Vendor-Commands über einen Programmer — Messungen und eine offene Frage

Wir reparieren eine Sony-Fernseher-Platine, indem wir das eMMC lesen und neu beschreiben.
Dabei haben wir versucht, die **Vendor-Command-Schnittstelle** des Samsung-eMMC zu erreichen
— den Weg in den BootROM-Modus des Controllers — und zwar von einem Consumer-Programmer
(XGecu T48) unter macOS aus, mit einem selbst geschriebenen Python-USB-Treiber.

Dieses Repository hält fest, was wir gemessen haben, was es **nicht** beweist und was uns
fehlt, um die Lücke zu schließen. Wer ein UFPI oder EasyJTAG besitzt, kann die Frage
vielleicht in zehn Minuten beantworten.

Umfang: Gerätereparatur und Datenrettung an eigener Hardware. Keine DRM-Umgehung.
Einzelheiten, Berechtigung und rechtliche Einordnung: **[LEGAL.de.md](LEGAL.de.md)**.

---

## 1. Warum das wichtig ist

Der RPMB-Key eines eMMC ist laut JEDEC nur schreibbar: Der Controller hält ihn, jeder
RPMB-Rahmen wird per HMAC-SHA-256 authentifiziert, und kein Standardkommando gibt ihn
zurück. Aktuelle Arbeiten ([arXiv 2511.22340](https://arxiv.org/abs/2511.22340)) umgehen
die HMAC-Prüfung mit elektromagnetischer Fehlerinjektion — das liefert aber
**Schreibvorgänge ohne Key**, niemals den Key selbst.

Die Vendor-Schnittstelle ist ein anderer Weg.
[Oran Avrahams `i9300_emmc_toolbox`](https://github.com/oranav/i9300_emmc_toolbox)
(Galaxy S3, Samsung VTU00M, 2017) dokumentiert sie in klarem C:

| Schritt | Kommando | Argument |
|---|---|---|
| BootROM-Recovery-Modus betreten | CMD1 (SEND_OP_COND) | `0x69FF87A9` (ein Knock, kein gültiger OCR-Wert) |
| CMD60 freischalten | CMD60 | `0xEFAC60FC` |
| Firmware-Slot aktivieren | CMD60 | `0xABCD1280` + type |
| Timer starten (liefert einen Wert) | CMD60 | `0xABCD1240` |
| CMD62 freischalten | CMD62 | `0xEFAC62EC` |
| Read-RAM-Backdoor öffnen | CMD62 | `0x10210002` |
| CMD62 verlassen | CMD62 | `0x00DECCEE` |

Ist die Read-RAM-Backdoor offen, wird der **normale Blockpfad auf das Controller-RAM
umgebogen**: CMD35 (Adresse) → CMD36 (Länge) → CMD38 (ausführen) → CMD17 (einen
512-Byte-Block holen). `dump_fw_bootrom.c` in jenem Repository liest so die kompletten
128 KB Controller-Firmware aus, ganz ohne Authentifizierung — weil der Controller seine
eigene Firmware nicht mehr ausführt.

Ob der RPMB-Key in diesem lesbaren RAM liegt, ist unbekannt. Wenn ja, ist der Key ein
Nebenprodukt des Dumps.

---

## 2. Was wir am T48 gemessen haben

Der T48 spricht ein eigenes USB-Protokoll. Für eMMC gibt es ein Kommando-Gate,
Top-Opcode `0x27`:

```
Host   -> 27 <sub_op> 00 00 <arg32 LE>           (8 Byte, EP1 OUT)
Gerät  -> 27 00 10 00 00 09 <flags> 00           (8 Byte, EP1 IN)
```

Jeder unterstützte Sub-Opcode folgt dem Muster `sub_op = 0x40 + CMD-Nummer`:

```
0x46 → CMD6    0x4C → CMD12   0x4D → CMD13   0x50 → CMD16
0x57 → CMD23   0x5C → CMD28   0x5D → CMD29
```

Damit wäre CMD1 = `0x41`, CMD60 = `0x7C`, CMD62 = `0x7E`.

Die Reverse-Engineering-Notizen behaupteten, `reply_buf[1] != 0` markiere Erfolg.
**Das ist auf dieser Firmware falsch**: Byte 1 ist in jeder Antwort `0x00`, auch bei
Kommandos, die nachweislich funktionieren. Byte 6 sah zunächst wie ein Statusbyte aus,
ist aber keines:

* `0x7E` antwortet identisch auf die Argumente `0`, `0xFFFFFFFF`, `0xEFAC62EC` und `0x00DECCEE`.
* `0x4C` antwortet identisch auf `0` und `0xFFFFFFFF`.
* `0x41` lieferte in einem Lauf `0x08`, in einem anderen `0x00` — bei gleichem Argument.
* In einer A/B-Alternation trug das **erste** Paket nach jedem Wechsel `0x08`, jedes
  folgende `0x00` — bei jedem Sub-Opcode gleich. `0x57` antwortete mit `0x48`, wenn man
  20 ms vor dem Lesen wartete.

Diese Werte (`0x00`, `0x08`, `0x40`, `0x48`) sind transiente Bits. **Die 8-Byte-Antwort
trägt keinen Kartenstatus.**

Zwei Dinge sind dennoch belastbar:

* `0xFF` erhält **gar keine Antwort** und verkeilt den Programmer bis zum physischen
  Replug. Die Firmware prüft den Sub-Opcode gegen einen Bereich.
* `0x7C` und `0x7E` antworten, liegen also innerhalb dieses Bereichs — der reicht damit
  über CMD31 hinaus. Nur Werte außerhalb werden abgewiesen.

Ein Read-RAM-Backdoor-Test (derselbe 16-KiB-Bereich vor und nach
`CMD62 / 0x10210002`) zeigte keine Änderung — das ist aber **kein Beweis**: Die Backdoor
braucht CMD38, um Daten bereitzustellen, und ein gewöhnlicher Massenread läuft über CMD18.
Wir haben CMD38 bewusst nicht gesendet — ohne offene Backdoor ist es ein
**Löschbefehl**.

Die Karte blieb durchgehend unberührt: ein vollständiger 512-Byte-extCSD-Vergleich vor
und nach jedem Lauf zeigte keinen Unterschied.

---

## 3. Die offene Frage

**Gibt der Bitstream des T48 die Kommandos CMD60/CMD62 überhaupt an die Karte weiter?**

* Alles deutet auf „nein": `Xgpro.exe` enthält keine Vendor-Command-Strings, und alle
  eMMC-Abläufe liegen als FPGA-Bitstream (`.alg`) in der Programmer-Firmware.
* Bewiesen ist es nicht, weil der Programmer auf dieser Ebene keine Kartenantwort
  sichtbar macht.

Der eine entscheidende Versuch ist ein Logikanalysator am eMMC-Bus: `0x46` (ein bekannt
funktionierendes Kommando) und `0x7E` senden und vergleichen, ob eines davon Verkehr auf
CLK/CMD/DAT0 erzeugt. Daran arbeiten wir.

---

## 4. Was wir von dir brauchen

Wer ein **UFPI** oder **EasyJTAG** besitzt — jede dieser Antworten hilft enorm:

1. **Kann dein Werkzeug CMD62 mit beliebigem Argument senden?**
   Sende `CMD62 0xEFAC62EC` und danach `CMD62 0x10210002` an einen Samsung-eMMC
   (KLMAG/KLMBG/KMDP, eMMC 5.x) und berichte, was die Karte antwortet — R1-Status,
   Fehler, Timeouts. Auch „das Werkzeug verweigert" ist eine nützliche Antwort.

2. **Woher stammt der RPMB-Key, den dein Werkzeug anzeigt?**
   EasyJTAG zeigt auf manchen Karten einen RPMB-Key. Wird er aus einem Boot- oder
   Identifikations-Metadatenblock auf der Karte gelesen, oder aus dem Controller nach
   einem Firmware-Schreibvorgang und erneuter Erkennung? Eine Beschreibung des Menüpfads
   genügt.

3. **USB-Mitschnitt des Vendor-Kommandopfads.**
   Wireshark + USBPcap (Windows) oder `usbmon` (Linux), gefiltert auf VID/PID des
   Programmers, während du die Funktion einmal ausführst. Das Rahmenformat ist genau
   das, was wir nicht raten können.

4. **Hat dein Werkzeug einen BootROM-/Recovery-/„eMMC entsperren"-Modus?**
   Was sendet er?

Bitte öffne ein Issue mit dem Ergebnis oder schick einen Mitschnitt. Kartenmodell,
Tool-Version und der genaue Menüpfad sind wichtiger als Prosa.

---

## 5. Sicherheitshinweise (für Nachbauer)

* **Keine** Sweeps über Sub-Opcodes. Nach der `0x40 + CMD`-Zuordnung ist `0x40` CMD0
  (GO_IDLE_STATE), `0x4F` CMD15 (GO_INACTIVE_STATE), `0x58` CMD24 (**Schreiben**),
  `0x5C`/`0x5D` CMD28/CMD29 (**Write Protect**).
* **Nicht** `0xFF` oder Werte außerhalb `0x40`–`0x7F` senden: Das verkeilt den Programmer
  bis zum Replug.
* `CMD38` ohne offene Read-RAM-Backdoor löscht. Nie als Sonde verwenden.
* Vor und nach jedem Experiment das komplette extCSD vergleichen — die billigste Art,
  zu bemerken, dass etwas geschrieben wurde.

---

## 6. Dateien

* `SAMSUNG-VENDOR-CMD.md` — die Ausarbeitung zur Vendor-Schnittstelle mit dem
  vollständigen Messprotokoll (§5.1) und der Liste, was der T48 kann und was nicht.
* `WEITERE-WEGE.md` — die beiden Wege, die wir verfolgen: Logikanalysator am eMMC-Bus
  und Ersatz des FPGA-Bitstreams.
* `AGENTS.md` — Arbeitsanleitung für KI-Agenten und Beitragende: welches Binary analysiert
  wird, wonach gesucht wird, wie ein Issue angelegt wird. Auch auf Chinesisch
  (`AGENTS.zh.md`).
* `docs/ufpi-findings.md` — was wir über die Kommandobehandlung von UFPI und EasyJTAG wissen.
  Auch auf [Deutsch](docs/ufpi-findings.de.md) und
  [Chinesisch](docs/ufpi-findings.zh.md).
* `docs/sony-partitions.md` — das Sony-DTV-Partitionslayout und warum eine Reparatur keinen
  RPMB-Key braucht. Auch auf [Deutsch](docs/sony-partitions.de.md) und
  [Chinesisch](docs/sony-partitions.zh.md).
* `docs/t48-status.de.md` — die vollständige Standaufzeichnung: Protokolldetails, die
  verifizierten Schreib-/Löschtests, die RPMB-Frame-Schicht und der entschlüsselte
  `.alg`-Container. Auch auf [Englisch](docs/t48-status.md) und
  [Chinesisch](docs/t48-status.zh.md).
* `docs/rpmb-key-findings.de.md` — alles, was wir dazu zusammengetragen haben, **woher der
  RPMB-Key kommt**: zwei Werkzeug-Videos und das OP-TEE-Issue, unser negatives Ergebnis und
  die extCSD-Werte, die den Schreibplan bestimmen. Auch auf
  [Englisch](docs/rpmb-key-findings.md) und [Chinesisch](docs/rpmb-key-findings.zh.md).
* `docs/attack-tree.de.md` — der Analyseplan als Baum: welche Zweige durch Messung
  geschlossen sind, welche offen bleiben, und welcher billigste Versuch jeden einzelnen
  entscheidet. Zugleich die Checkliste für Beitragende. Auch auf
  [Englisch](docs/attack-tree.md) und [Chinesisch](docs/attack-tree.zh.md).
* `scripts/` — unser Python-Treiber für das T48-USB-Protokoll und die Sonden-Skripte
  (`t48_mmc.py` ist der Treiber: identify, CSD/extCSD, Partitionen, Bulk-Lesen/-Schreiben,
  RPMB-Rahmen, Profilwahl mit `--voltage`/`--width`, `selftest`; dazu `sub_op_probe.py`,
  `sub_op_timing.py`, `sub_op_capture.py`, `sub_op_stability.py`, `reply_width.py`,
  `vendor_forward_test.py`).

Dieses Repository enthält kein RPMB-Schlüsselmaterial, keine Geräteseriennummern und
keine Zugangsdaten. Es ist nichts dergleichen darin zu finden.
