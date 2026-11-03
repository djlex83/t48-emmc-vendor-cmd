[English](attack-tree.md) · **Deutsch** · [中文](attack-tree.zh.md)

# Angriffsbaum: Woher könnte der RPMB-Key kommen?

Ein Analyseplan, sortiert nach Testkosten, mit je einer ehrlichen Statuszeile pro Knoten.
Das Dokument ist zugleich die Checkliste für Beitragende: jeder offene Knoten nennt den einen
billigsten Versuch, der ihn entscheidet.

Messungen und Daten: 10.–11.2026. Eigene Messungen sind mit **[wir]** markiert, fremde
Behauptungen, die wir nicht nachstellen können, mit **[3rd]**, und ein Knoten, den wir nur für
plausibel halten, mit **[offen]**.

Umfang: eigene Hardware, Gerätereparatur, keine DRM-Umgehung, keine Schlüsselmaterialien oder
Seriennummern in diesem Repository. Siehe [LEGAL.de.md](../LEGAL.de.md).

---

## 0. Das Ziel, ehrlich benannt

Wir wollen **Platinen reparieren**, und der RPMB-Key ist für genau ein Teilziel relevant:
authentifiziertes Schreiben in die RPMB-Partition. Alles andere auf diesen Boards funktioniert
ohne ihn — das ist der Befund in [sony-partitions.de.md](sony-partitions.de.md).

Der Baum hat also zwei Wurzeln, und es sind nicht dieselbe Frage:

| Wurzel | Frage | Stand |
|---|---|---|
| **R1** | Können wir den RPMB-Key einer bestimmten Karte beschaffen? | eine Karte ja **[3rd-belegt]**, unsere zwei 16-GB-Karten nein |
| **R2** | Brauchen wir ihn für die Reparatur? | **nein** für jeden Schritt, den wir bisher gemessen haben |

Zu R1 gibt es bereits einen positiven Datenpunkt: Der Key einer Karte wurde über eine
Kaufbox beschafft und kryptografisch verifiziert (abgeleiteter MAC stimmte). Das Ergebnis
hält, kam aber nicht vom T48, und diesen Weg können wir mit unserer Hardware nicht nachbauen.

---

## 1. Der Baum

```
R1  RPMB-Key einer bestimmten Karte beschaffen
│
├── A  Boot-Identifikations-Metadaten auf der Karte         [3rd] + [wir: negativ]
│      Behauptung: Metadatenbereich bei 0x20000000, 80 Pages, enthält CID,
│      Write-Counter und den 32-Byte-Key. Werkzeug-Log: "RPMB key is VALID".
│      Unser Test: beide 16-GB-Karten vollständig durchsucht — kein
│      Metadatenblock, keine CID in beliebiger Byte-Reihenfolge, kein
│      "Boot Identification". Der Weg existiert bei manchen Samsung-Dies,
│      bei unseren Karten ist er nicht vorhanden.
│      Ein zweites, viel größeres Negativ: In 694 bereits auf unserem Tisch
│      liegenden EasyJTAG-Protokollen (11 MB, v1.6.4–2.0.2) kommt
│      „identification" in null Zeilen vor, ein Key in null Zeilen —
│      siehe ufpi-findings.de.md.
│
├── B  Controller-RAM über die Vendor-Command-Schnittstelle [offen]  ← der lebende Zweig
│      BootROM-Knock (CMD1 0x69FF87A9), CMD60/CMD62-Freischaltung,
│      Read-RAM-Backdoor (CMD62 0x10210002), danach CMD35/36/38/17.
│      Für VTU00M von oranav dokumentiert (GPLv3, verlinkt, nicht kopiert).
│      Das Primitive existiert irgendwo: EasyJTAG exportiert
│      eMMC_SamsungBootTrickCMDInit/Finish — ein namentlich benannter,
│      zweistufiger Vendor-Trick.
│      Unser Blocker: wir sehen nicht, ob der T48-Bitstream CMD60/CMD62
│      überhaupt an die Karte weitergibt — der Programmer verbirgt die
│      Kartenantwort.
│      → das ist Issue #1 und die Logikanalysator-Messreihe.
│
├── C  Direkt aus der RPMB-Partition lesen                  [wir: geschlossen]
│      Rohlesen des RPMB-Bereichs liefert Result 0x0001 (general failure);
│      16384 B gelesen, 99,8 % Nullen, die einzigen Nicht-Null-Bytes sind
│      das Result-Feld. Am Gerät bewiesen, zweimal. Geschlossen.
│
├── D  Aus Host-Software oder Image rekonstruieren          [wir: geschlossen]
│      Vollständiges User-Backup offline ausgewertet: die
│      MediaTek-DRM-Bibliothek nennt MTDRM_RPMBLoadMacKey — der Key wird
│      *über* RPMB geladen, nie im Image gespeichert. Entropieprüfung des
│      Bereichs mit den DRM-Strings: kein 32-Byte-Zufallsblock irgendwo.
│      Geschlossen.
│
├── E  Brute Force / Suche                                  [wir: geschlossen]
│      25.165.728 Kandidaten gegen einen bekannt-guten Rahmen geprüft:
│      kein Treffer. HMAC-SHA-256 über einen 256-Bit-Key ist nicht
│      durchsuchbar. Geschlossen.
│
├── F  Prüfung umgehen statt Key beschaffen (EMFI)          [3rd]  für uns außer Scope
│      Publikation: Schreibvorgänge ohne Key (lesen und schreiben). Braucht
│      Glitch-Spule und Pulsgenerator. In diesem Projekt wird nicht gelötet,
│      und einen Key liefert es ohnehin nicht. Nicht unser Weg.
│
└── G  Leute mit der Ausrüstung fragen                       [offen]  ← der billige Zweig
       UFPI-/EasyJTAG-Besitzer: Issues #3 (erreichen Vendor-Kommandos die
       Karte?) und #4 (woher kommt der angezeigte Key?).
       Kostet uns nichts, und eine Antwort entscheidet mehr als unsere
       Woche Arbeit.
```

Die Reparatur-Wurzel, parallel dazu:

```
R2  Platine reparieren
│
├── H  Boot-Kette ohne RPMB                                 [wir: offen]
│      Verifiziert: Schreib- und Löschpfad byte-identisch, extCSD lesbar,
│      Partitionszugriff umschaltbar. Kein einziger gemessener Schritt
│      braucht den Key.
│
├── I  Provisionierung einer frischen Karte                  [offen]
│      Schreibt der TV den Key selbst, wenn der Counter 0 ist? Über die
│      Vendor-Schnittstelle am T48 nicht prüfbar — ein
│      USB-Stick-Update-Test am TV beantwortet es direkt.
│
├── J  "Write protection entfernen" als eigenes Problem      [3rd]
│      Gemeldeter Mechanismus: CSD umschreiben — Bits 12/13 in CSD-Byte 14
│      löschen, CRC7 neu berechnen, CMD16 16 → CMD27, vorher
│      Firmware-Entsperr-Opcodes, die unser T48 nicht kann. Eigener
│      Teilbaum, potenziell destruktiv: zuerst vollständiges Backup.
│
└── K  Firmware-Update der Karte selbst (FFU)               [wir: gemessen, hängt an B]
       Die *Karte* ist bereit: in einem lokalen Bestand von 587 extCSD-Dumps
       melden 531 EXT_CSD[308] = 1 (FFU_FEATURE_SUPPORT), und alle neun
       Dumps unserer AJTD4R-Variante tun das, FW_REV 02.00. Der Blocker ist
       der Transport, nicht das Ziel: der dokumentierte Ablauf beginnt mit
       CMD60 0xEFAC60FC, und die Antwort zu Knoten B entscheidet, ob
       überhaupt ein Programmer ihn erreichen kann.
       Und der Schritt zurück hat auf dem Fremdwerkzeug einen Namen:
       eMMC_SamsungDumpFirmware liest die Controller-Firmware von der Karte.
       Dem T48 fehlt er — das ist das ganze Hindernis, nicht die Karte.
```

---

## 2. Knoten im Detail, sortiert nach Entscheidungskosten

### B — Controller-RAM (der einzige Zweig, der bei unseren Karten noch zu einem Key führt)

Alles in diesem Zweig hängt an einer binären Tatsache: **Erzeugt ein `0x27`-Paket mit
Sub-Opcode `0x7E` eine Kurve auf dem eMMC-Bus?**

Billigster Beweis: Logikanalysator an CLK/CMD/DAT0 im BGA-Sockeladapter, vier Kanäle,
24 MS/s genügen, weil wir nur „Flanken ja/nein" brauchen. Zuerst `0x46` senden (ein
Kommando, das nachweislich funktioniert) als Positivkontrolle, dann `0x7E` — dieselbe
Sitzung, dieselbe Karte.

Ergebniszuordnung:

| Ergebnis | Bedeutung |
|---|---|
| `0x46` zeigt Traffic, `0x7E` keinen | Bitstream gibt Vendor-Kommandos nicht weiter → Zweig B am T48 tot, Weg 3 (eigener Bitstream) ist zwingend |
| `0x7E` zeigt Traffic | Weiterleitung funktioniert → die offene Frage wandert zur Kartenantwort, die wir weiter nicht sehen; nächster Schritt: die Antwort auf DAT0 dekodieren |
| keiner zeigt Traffic | unser Modell des Kommando-Gate ist falsch → vom Bus neu ableiten |

Bitte **nicht** per Sweep über Sub-Opcodes sondieren. `0xFF` verkeilt den Programmer bis zum
physischen Replug, und die Zuordnung `sub_op = 0x40 + CMD` legt CMD0, CMD15, CMD24 (Schreiben)
und CMD28/29 (Write Protect) genau in den Bereich, den ein Sweep durchquert.

### G — die Werkzeug-Fragen

Für uns kostenlos und der höchste Erwartungswert. Die konkreten Bitten stehen in README §4 und
in den Issues #3/#4. Was wir von UFPI-/EasyJTAG-Besitzern brauchen, in dieser Reihenfolge:

1. Ob das Werkzeug `CMD62 0xEFAC62EC` und danach `CMD62 0x10210002` sendet und was die Karte
   antwortet. „Das Werkzeug verweigert" ist eine echte Antwort.
2. Woher der Key im RPMB-Bildschirm kommt — Metadatenblock oder Controller — plus der
   genaue Menüpfad.
3. Ein USB-Mitschnitt dieser Funktion, gefiltert auf VID/PID des Programmers.

### A — die Metadaten-Behauptung

Offengehalten durch das fremde Log, für unsere zwei Karten durch direkte Suche widerlegt.
Was uns umstimmen würde: ein Dump einer Karte, bei der das Werkzeug einen Key zeigt, plus der
Byte-Offset, den es dafür gelesen hat. Dann lässt sich prüfen, ob dieser Offset am T48
überhaupt adressierbar ist.

### C, D, E — geschlossene Zweige

Durch Messung geschlossen, und hier aufgelistet, damit niemand Aufwand in ihre Wiedereröffnung
steckt. Sie bleiben geschlossen, außer es kommt ein anderes Kartenmodell auf den Tisch: Die
Befunde sind die-spezifisch.

### I — die Provisionierungs-Frage

Der billigste Versuch im ganzen Baum und der mit der größten Wirkung auf die Reparatur:
USB-Stick vorbereiten (FAT32, `.pkg` im Wurzelverzeichnis), den TV mit einer Karte davon
booten, deren Counter 0 ist, LED-Zustände protokollieren und prüfen, ob RPMB-Schreibvorgänge
erscheinen.
Provisioniert der TV die Karte selbst, ist die Key-Frage für die Reparatur erledigt.

### K — die Firmware-Update-Frage

Die Karte ist nicht das Hindernis. Über 587 extCSD-Dumps auf unserem Tisch melden 531
`FFU_FEATURE_SUPPORT` (`EXT_CSD[308] = 1`), und alle neun Dumps unserer AJTD4R-Variante tun
das, FW_REV 02.00. Ein Firmware-Update ist bei diesem Die eine echte Funktion.

Zwei Dinge hindern uns trotzdem daran, einen zu fahren — beide handeln von Umkehrbarkeit:

| Blocker | Warum |
|---|---|
| Transport | der dokumentierte Ablauf beginnt mit `CMD60 / 0xEFAC60FC`; ob überhaupt ein Programmer das auf den Bus bringt, ist exakt Knoten B |
| kein Zurück | für die Controller-Firmware gibt es am T48 keinen Sicherungsweg — ihr Dump braucht dieselbe Read-RAM-Backdoor, die noch unbewiesen ist. Ein falsches Bild schlägt nicht sicher fehl: es ersetzt den Code, den der Controller bootet. |

Bei den Bildern ist teilweise gesorgt: der Vendor-Firmware-Bestand ist nicht
kapazitätsspezifisch, und für eine unserer zwei Karten existiert ein exaktes Match (gleiches
PNM, gleiche Controller-Familie), für die andere keins in ihrer Kapazität — dort ist die
nächste Datei das 32-GB-Geschwistermodell. Ein Match sollte vor jedem Versuch trotzdem gegen
`EXT_CSD[254..255]` geprüft werden.

Die ehrliche Antwort auf „können wir FFU an unserer eigenen Karte ausprobieren" lautet also:
**noch nicht, und nicht an der Karte mit dem echten Image.** Es ist der einzige Vorgang in
diesem Projekt, der nicht rückgängig zu machen ist, sein Gate ist unbeantwortet, und eine
Antwort auf Knoten B kostet einen Nachmittag mit dem Logikanalysator. Falls die positiv
ausfällt, gehört das erste FFU auf die leere Musterkarte — und bleibt eine ausdrückliche
Entscheidung, kein Experiment.

---

## 3. Was wir selbst tun können, nach Kosten sortiert

Für nichts davon brauchen wir neue Hardware. Sortiert nach Wert pro Stunde.

1. **Bitstream-Diff — durchgeführt, negativ.** Die `.alg`-Sammlung ist vollständig am
   Tisch: 354 Container, fünf eMMC-Familien, jede als `_18`- und `_33`-Variante. Wir haben
   sie wie geplant über den entpackten Strömen gegeneinander XOR (340 604 B = 170 302
   16-Bit-Wörter pro Datei) — und die Methode liefert nicht, was wir erhofft haben. Das Paar,
   das sich nur im IO-Standard unterscheiden sollte (`GEN_18`/`GEN_33`), differiert in
   9,19 % der Bytes; ein Familien-XOR (`EMMC_41_18` gegen `NAND_15`) in 10,80 % — es gibt
   keinen Kontrast, und die Differenzen liegen gleichmäßig über allen Bitpositionen und dem
   ganzen Strom. Grund: jede Variante ist ein eigenständig gelegter und gerouteter Entwurf,
   kein parametrisierter Ableger, ein XOR zweier gerouteter Spartan-6-Ströme zeigt also
   Routing, nicht IO-Attribute. **Die Pinbelegung lässt sich so nicht ableiten.** Was für
   diesen Zweig bleibt: direkte Frame-Adress-Decodierung, oder die Platine selbst. Zahlen
   und die vollständige Tabelle: [../WEITERE-WEGE.de.md](../WEITERE-WEGE.md).
2. **Neuere Xgpro-Version, statischer Diff.** Wir haben zwei Installer-Versionen. Ein
   String- und Import-Diff beider Versionen zeigt, ob die Vendor-Command-Fläche gewachsen
   ist — ohne die Hardware anzufassen. Dieselbe Methode wie beim Bitstream-Diff: vergleichen
   statt raten.
3. **UFPI-Opcodes-Pfad — schon entschieden, kein Versuch mehr offen.** Unsere eigene
   statische Analyse der entpackten UFPI-Binary zeigt: die RPMB-Worker sind je 0x89 Byte lang
   und enthalten keinen Read. Der `0x93`-Worker nimmt den 32-Byte-Key aus einem
   Host-Eingabefeld (`"Enter RPMB Auth Key (32 bytes)"`, geprüft auf 64 Hex-Zeichen) und
   übergibt `req[0..3] = 0x93` plus diese 32 Bytes an den Programmer — 36 Bytes in 3 s;
   `0x94` ist baugleich für die Authentifizierung. Auch in UFPI existiert kein Host-seitiger
   RPMB-Frame-Builder und kein Key-Read. Das ist gleichzeitig das Argument für Issue #4: Das
   EasyJTAG-Log zeigt einen Key aus einem Metadaten-Read. Die offene Frage ist also nicht
   „was liest 0x93", sondern „welcher Codepfad in der EasyJTAG-Firmware macht diesen
   Metadaten-Read".
4. **Zwei Offline-Prüfungen in unseren eigenen Images.** (a) `MTDRM_RPMBLoadMacKey` belegt,
   dass die Host-Seite den Key über RPMB liest; folgt man der Aufruferkette im Bootloader,
   sieht man, *welche* RPMB-Rahmen sie erwartet. (b) In den Partitionstabellen, die wir
   schon haben, nach den Namen suchen, die die EasyJTAG-Protokolle zeigen: `rpmbak`,
   `keystorage`, `keyrefuge`, `keydata`, `keystore`, `keymaster`. Eine Partition namens
   **rpmbak** ist eine RPMB-Sicherung im User-Bereich — haben unsere Platinen so etwas,
   gibt es einen Wiederherstellungsweg, der gar keinen Key braucht. Beides ist Analyse
   unseres eigenen Backups, offline, ohne Risiko.
5. **RPMB-Frame-Schicht simulieren.** MAC über synthetischem Key/Nonce/Counter bauen und
   unsere Feld-Packing-Regel gegen das JEDEC-Layout prüfen, damit der Code bewiesen ist,
   bevor er eine Karte sieht.
6. **Der USB-Stick-Test am TV** (Knoten I). Kein Löten, umkehrbar, und er entscheidet eine
   Frage, die der Programmer gar nicht beantworten kann.

Später, mit dem Logikanalysator: Knoten B, dazu das Protokoll eines `.alg`-Uploads mitschneiden
(Weg 3, Schritt 4).

---

## 4. Was wir bewusst nicht versuchen

- Kein Löten, keine Messnadeln am Die, keine Glitch-Spule (Projektregel; Knoten F ist
  ohnehin fremde Arbeit).
- Kein destruktives Kommando als Sonde: `CMD38` ohne offene Read-RAM-Backdoor löscht.
- Keine Sub-Opcode-Sweeps, keine Schreibvorgänge ohne vorheriges vollständiges Backup,
  kein Schlüsselmaterial und keine Seriennummern in irgendeiner Datei hier.
- Keine Firmware-Bytes der Hersteller weiterverbreitet; Fremdcode wird verlinkt, nicht kopiert.

---

## 5. Falls du das als Beitragender durcharbeitest

Nimm einen Knoten, mache den billigsten dort genannten Versuch, melde: Kartenmodell, Werkzeug
und Version, genauen Menüpfad oder Byte-Folge und die rohe Beobachtung. Eine negative Antwort
setzt einen Knoten auf **geschlossen** und ist so viel wert wie eine positive. Bitte kein
Schlüsselmaterial, keine vollständigen CIDs und keine Dumps posten — wir brauchen abgeleitete
Fakten.

Gleicher Text auf [Englisch](attack-tree.md) und [Chinesisch](attack-tree.zh.md).
