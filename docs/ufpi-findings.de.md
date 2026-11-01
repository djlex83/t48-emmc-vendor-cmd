[English](ufpi-findings.md) · **Deutsch** · [中文](ufpi-findings.zh.md)

# UFPI und EasyJTAG — Ansatzpunkte für die Analyse

Zusammengefasst aus unseren eigenen Reverse-Engineering-Notizen (`EASYJTAG-HANDOFF.md`
§9.11 und §9.12), 2026. Jede Zeile ist **eine zu prüfende Spur, keine zitierfähige
Tatsache**. Nichts davon wurde an unserer Hardware bestätigt — wir besitzen keines der
beiden Werkzeuge.

---

## 1. UFPI

### Architektur

UFPI wird über USB vom Host gesteuert: Der PC schickt ein kleines Opcode-Byte, die
Programmer-Firmware führt die entsprechende Operation auf der Karte aus. Mehrere
Abläufe auf Kartenebene erscheinen deshalb nie als Host-Kommandorahmen — sie laufen
vollständig im Programmer.

| Opcode (Host) | Bedeutung |
|---|---|
| `0x38` | hostseitiger CMD56-Helfer; verzweigt zu Code nahe `0xedf350` |
| `0x3E / 0x00DECCEE` | verlässt einen freigeschalteten Modus |
| `0x93` | RPMB-Key schreiben (innerhalb der Programmer-Firmware) |
| `0x94` | RPMB authentifizieren (innerhalb der Programmer-Firmware) |
| `0x1BE / 0xEFAC62EC` | erstes Element eines Freischalt-Triples |
| `0x1BE / 0x0FAC0070` | zweites Element — **Achtung: nicht** das Samsung `0x10210002` |

### Was die Triples bedeuten

```
0x1BE / 0xEFAC62EC      Samsung-CMD62-Freischaltung
0x1BE / 0x0FAC0070      ein zweites Magic, das wir nicht zugeordnet haben
0x3E  / 0x00DECCEE      CMD62 verlassen
```

Das erste und das dritte stimmen exakt mit der Samsung-Vendor-API überein. Das mittlere
nicht. Es kann ein UFPI-eigener Vendor-Code sein, eine andere Generation des Magic oder
das Argument eines anderen Kommandos — das ist der interessanteste offene Punkt im
UFPI-Binary.

### CMD56

Der hostseitige CMD56-Helfer existiert und wird für die Funktion **„Micron Health
Report"** benutzt (Code nahe der virtuellen Adresse `0xf48b40`, Argumente `0x11` und
`0x21`). CMD56 ist eine Vendor-Schnittstelle aus der Toshiba/Micron-Familie und **nicht**
der Samsung-Pfad CMD60/62. Nicht verwechseln.

### Was zuerst zu prüfen ist

1. Ist `0x1BE` ein festes Zwei-Byte-Host-Opcode, oder trägt das zweite Byte das
   MMC-Argument? Das Paarformat legt nahe, dass ein Kommandowort auf zwei Bytes
   aufgeteilt ist.
2. Was macht `0x0FAC0070` — welcher Zweig der Firmware behandelt es?
3. Baut irgendein Codepfad die Sequenz `CMD62 0xEFAC62EC` → `CMD62 0x10210002`?
   Suche nach `10210002` als Immediate. Taucht es nie auf, kann UFPI die
   Read-RAM-Backdoor nicht öffnen, und die Antwort auf A1 lautet „nein".

---

## 2. EasyJTAG

### Anzeige des RPMB-Keys

EasyJTAG zeigt Berichten zufolge auf **KMDP6001DB-B425** einen RPMB-Key an, gelesen aus
dem Boot-Identifikations-Metadatenbereich um **`0x20000000`**, 80 Seiten, wobei der Key
vor der Anzeige validiert wird. Das ist ein **Karten-Metadaten**-Pfad, kein
Controller-Pfad.

Wenn das stimmt, beantwortet es A2 für dieses Kartenmodell: Der Key liegt lesbar auf der
Karte und wird nicht aus dem Controller bergen.

### Warum das für unser Projekt zählt

Unser Ziel ist KLMAG1JENB-B041 (eMMC 5.1, 16 GB). Ob derselbe Metadatenbereich auf
diesem Modell existiert und einen Key enthält, ist unbekannt. Zwei Prüfungen, die ein
Beitragender laufen lassen kann:

1. Den USER-Bereich um LBA `0x100000` `dump`en (der Byte-Offset `0x20000000`, bei
   512-Byte-Sektoren) und nach einem strukturierten 80-Seiten-Block mit einem
   plausiblen 32-Byte-Key suchen.
2. Prüfen, ob EasyJTAG vor dem Anbieten des RPMB-Tabs nach Kartenmodell verzweigt.
   Wenn ja, existiert der Metadatenpfad vermutlich nur auf bestimmten Familien.

### Offener Widerspruch, der zu klären ist

Ein Tutorial-Video behauptet, der RPMB-Key erscheine im RPMB-Tab **nach einem
FFU-Rückschreiben und erneuter Erkennung** und bleibe über wiederholte Lesevorgänge
identisch. Das passt eher zu einer Controller-Zustandsänderung (CMD60-Firmware-Aktivierung)
als zu einem statischen Metadatenblock. Zwei Quellen, zwei Mechanismen. Genau dafür sind
die Issues A2 und Task C da.

---

## 3. Wie diese Notizen entstanden sind

Statische Analyse der Vendor-Binaries: Stringsuche, Rückgewinnung der Opcode-Tabelle,
Disassembly um den Kommando-Dispatcher herum und Verfolgen von Querverweisen. Es fand
keine dynamische Analyse statt, weil die Werkzeuge nie ausgeführt wurden.

Das ist die wesentliche Einschränkung: **Jeder Befund oben ist unbestätigt.** Eine
Bestätigung braucht entweder die Hardware (Task C) oder eine zweite unabhängige Analyse
desselben Binaries.
