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

### Die Exporttabelle ist das Einzige, was lesbar ist (gemessen 3.11.2026)

`EasyAPI.dll` (9 841 664 B, sha256 `b6c109ad…ba9c360d`, PE32/x86) und `EasyAPI2.dll`
(14 748 160 B) sind gepackt: Jede Sektionsangabe meldet Größe `0`, der Code liegt in einer
Sektion `.vmp0`. Ghidra 12.1.4 importiert die DLL und schließt die Autoanalyse nach 7 s ab,
löst aber **keine** Prozedur namentlich — eine Suche nach Prozeduren mit `Samsung` liefert
nichts. Die Körper sind uns verschlossen. Was die Packung intakt lässt, ist die
**Exporttabelle**, und ihre Namen sind selbst der Befund (106 Exporte in V1, 114 in V2):

| Export | Was der Name sagt |
|---|---|
| `eMMC_RPMB_Read`, `eMMC_RPMB_ReadCounter` | RPMB-Daten lesen und Zähler lesen |
| `eMMC_SamsungBootTrickCMDInit` / `…CMDFinish` | der Boot-Trick als **zweistufiger** Vorgang |
| `eMMC_SamsungBootRPMBChangeInit` / `…Finish` | Änderung der Boot-/RPMB-Zuordnung, ebenfalls zweistufig |
| `eMMC_SamsungDumpFirmware` | die Controller-Firmware von der Karte **lesen** |
| `eMMC_SamsungRemoveWriteProtection` | Schreibschutz-Aufhebung als ein Aufruf |
| `eMMC_SamsungVTU00MRepair` | ein Reparaturpfad, benannt nach genau dieser Controller-Familie |
| `eMMC_SamsungFactoryWriteCID`, `eMMC_SamsungFactoryWriteCSD`, `eMMC_WriteCSD`, `eMMC_extCSD_SingleItemWrite` | Identitäts- und Konfigurationsumschreiben |
| `eMMC_SamsungFactoryResetCMD`, `eMMC_FactoryResetCMD42`, `eMMC_OTPGetSize/GetStatus/Lock/Unlock`, `eMMC_JEDEC_HWPART_CONFIG`, `eMMC_Switch_Part`, `eMMC_LockUnlockPassword` | der Rest der Instandhaltungsfläche |
| `BoxSetDFUMode`, `BoxAESEncrypt`, `BoxAESDecrypt`, `BoxSECDecrypt`, `GetBoxFirmwareChar`, `SetBoxPinoutMode` | die Box selbst: DFU-Modus, Krypto, Pinout-Modi |

Zwei Schlüsse folgen allein aus den Namen.

1. **Es gibt keinen eMMC-Key-Export.** Die einzigen nach Key benannten Exporte in beiden DLLs
   sind `UFS_SetRPMBKey`, `UFS_ProgramRPMBKey`, `UFS_CheckRPMBKey` — das UFS- Namensgebiet,
   nicht eMMC. Diese API kann RPMB-Daten und den RPMB-Zähler lesen; sie zeigt keinen Weg,
   einen eMMC-Key zu programmieren oder auszulesen.
2. `eMMC_SamsungDumpFirmware` beweist, dass es auf dieser Box einen Lese-Pfad für die
   Controller-Firmware gibt. Das ist genau das Primitive, das unserem T48 fehlt, und es ist
   die Voraussetzung dafür, ein Firmware-Update der Karte überhaupt zu wagen
   (Angriffsbaum, Knoten K).

### Was 694 Protokolldateien dieses Werkzeugs enthalten (gemessen 3.11.2026)

Eine lokale Installation trägt ihre eigene Protokollgeschichte bei: `Logs/`, 694 Dateien,
11 MB, Werkzeugversionen 1.6.4.0 – 2.0.2.0, April 2021 – April 2023. Ausgezählt, mit
absichtlich entfernten Kennungen und Hex-Folgen:

| Beobachtung | Anzahl |
|---|---|
| RPMB-Urteilszeilen | 800 |
| … mit Counter = 0, Urteil `Clean` | 244 |
| … mit Counter = 0, Urteil `Maybe not clean` | 130 |
| … mit Counter > 0, Urteil `Not Clean` | 426, ohne Ausnahme |
| Zeilen mit `identification` | **0** |
| Zeilen, die einen Key melden | **0** — `valid` steht nur neben GPT-Headern |
| Zeilen mit `key` | ausnahmslos *Partitionsnamen aus Firmware-Paketen* |

Das Urteil ist also eine reine Funktion des **Written-Word-Counters**, den JEDEC ohne jeden
Key lesbar macht: `Response: Clean` heißt „Counter 0" und sonst nichts.

Die `key`-Zeilen haben mit RPMB nichts zu tun. Es sind Partitionen eines
Telefon-Firmware-Pakets (`*.tar.md5`, `*.pit`), aus lz4 ausgepackt und als ganz normale
User-Bereich-Daten nach ROM1 geschrieben: `keystorage` (512 KB, Raw), `keydata`, `keyrefuge`,
`keystore`, `keymaster`, `omekeystore` — und `rpmbak` (512 KB, Raw). Eine Partition mit dem
Namen **rpmbak** ist eine RPMB-Sicherung im User-Bereich. Das ist der erste Mechanismus in
diesem Projekt, mit dem ein Gerät RPMB-Inhalt wiederherstellen könnte, ohne jemals einen Key
zu besitzen, und er ist an unseren eigenen Platinen prüfbar: in den Partitionstabellen nach
diesen Namen suchen.

### Was das nicht erledigt

Ein Host-Protokoll schreibt auf, was der Host aufschreiben wollte. Die Box-Firmware ist für
uns nicht lesbar (`emmc.dat`, 65 536 B, hohe Entropie, keine Vektortabelle — verschlüsselt),
ein undokumentierter Pfad ist damit nicht ausgeschlossen. Was wir sagen können: In 11 MB der
Eigenprotokolle dieses Werkzeugs gibt es keinen Key-Lesevorgang, und die Formulierung
`RPMB key is VALID` kommt in keiner dieser Versionen vor. Issue #4 bleibt bestehen, jetzt
deutlich schärfer — nach `eMMC_RPMB_Read` und `eMMC_SamsungBootTrickCMDInit/Finish` fragen,
namentlich.

---

## 3. Wie diese Notizen entstanden sind

Statische Analyse der Vendor-Binaries: Stringsuche, Rückgewinnung der Opcode-Tabelle,
Disassembly um den Kommando-Dispatcher herum, Verfolgen von Querverweisen, Auslesen der
Exporttabellen und das Lesen eines Protokollbestands, den eine Installation hinterlassen hat.
Keine dynamische Analyse — die Werkzeuge wurden nie ausgeführt.

Das ist die wesentliche Einschränkung: **Jede Ableitung aus den Binaries ist unbestätigt.**
Eine Bestätigung braucht entweder die Hardware (Task C) oder eine zweite unabhängige Analyse
desselben Binaries. Die mit „gemessen" markierten Abschnitte sind Auszählungen über Dateien,
die auf unserem Tisch liegen — reproduzierbar, aber trotzdem kein Hardwarelauf.
