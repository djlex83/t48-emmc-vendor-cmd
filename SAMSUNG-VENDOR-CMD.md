# Samsung-eMMC-Vendor-Commands — Der Weg in den Controller

Stand 1.11.2026. Alle Kommandos sind aus **Quellcode** belegt, nicht aus Vermutung.
Quellen sind am Ende aufgeführt.

---

## 1. Warum das neu ist

Bisher galt: Der RPMB-Key ist write-only, liegt im Controller, kein Software-Lesepfad.
Das bleibt für den **normalen** Betrieb wahr. Was bisher fehlte, ist der Modus, in dem
der Controller seine normale Firmware **nicht** mehr ausführt — der **BootROM-Modus**.

Oran Avrahams `i9300_emmc_toolbox` (Samsung VTU00M, Galaxy S3, 2017) enthält die
komplette Kommando-API dorthin, als lesbaren C-Code:

| Funktion | Datei |
|---|---|
| `prepare_mmc(TRUE)` — BootROM-Modus | `shellcode/common.c` |
| `mmc_enter_read_ram()` — Controller-RAM lesen | `shellcode/common.c` |
| `dump_fw_bootrom.c` — kompletter 128-KB-Firmware-Dump | `shellcode/dump_fw_bootrom.c` |

Dieselben Magics funktionieren laut arXiv 2511.22340 (Fukami/Buurke, 2025) noch auf
**KLMAG2GE4A** (eMMC 4.51) und **KLM8G1WEMB** (eMMC 5.0) — also über acht Jahre und zwei
Generationen hinweg unverändert. Das ist der Grund, warum ein Versuch auf
KLMAG1JENB-B041 (eMMC 5.1, 2017) gerechtfertigt ist.

---

## 2. Die beiden Türen

### 2.1 CMD1 mit Knock-Code → BootROM-Recovery-Modus

```c
cmd.cmdidx    = 1;
cmd.resp_type = 1;
cmd.cmdarg    = 0x69FF87A9;   /* kein OCR! */
mmc_send_cmd(mmc_dev, &cmd, 0);
sleep(10);
```

Normalerweise sendet CMD1 (SEND_OP_COND) die Spannungsmaske
`0x40000000 | 0x300000` = `0x40300000`. Der Wert `0x69FF87A9` ist **kein gültiger
OCR-Wert** — er ist ein Hersteller-Knock. Die Karte antwortet nicht mit ihrem
Betriebszustand, sondern der Controller startet in die Recovery-Firmware (BootROM).

Danach läuft `mmc_send_op_cond()` normal weiter, d. h. der Host initialisiert die Karte
anschließend wie gewohnt. Der Controller ist aber im Recovery-Modus.

### 2.2 CMD60/CMD62 → Vendor-Modus und RAM-Backdoor

Alle Vendor-Kommandos sind **zweistufig**: erst eine Freischalt-Magic, dann der Nutzbefehl.
Ohne die Magic nimmt der Controller den zweiten Befehl nicht an.

**CMD62 (`0xEFAC62EC` = Freischaltung):**

| Zweites Argument | Wirkung |
|---|---|
| `0x10210002` | **Read-RAM-Backdoor öffnen** |
| `0x10210001` | **Write-RAM-Backdoor öffnen** |
| `0x10210003` | Read-DWORD-Backdoor öffnen |
| `0x10210000` | Write-DWORD-Backdoor öffnen |
| `0x00DECCEE` | CMD62 verlassen (Backdoor schließen) |
| `0x00CBAEA7` | Boot-Partition neu dimensionieren (nächster Schritt = Größe in MB) |

**CMD60 (`0xEFAC60FC` = Freischaltung):**

| Zweites Argument | Wirkung |
|---|---|
| `0xCBAD1160` | Firmware-Upgrade-Modus |
| `0xABCD1280 + type` | Firmware-Slot `type` aktivieren (0 und 1 = zwei Blöcke) |
| `0xABCD1240` | Timer starten; **Rückgabewert = Response[0]** |

Der Timer-Rückgabewert ist der einzige Vendor-Aufruf mit einem Ausgabewert auf
Kommandoseite — nützlich als Lebenszeichen-Test, ob der Vendor-Modus wirklich greift.

---

## 3. Wie man damit Controller-Speicher liest

Nach `CMD62 / 0x10210002` wird der **normale Blockpfad auf den Controller-RAM umgebogen**.
Man braucht danach keine weiteren Vendor-Kommandos — es laufen gewöhnliche MMC-Kommandos:

```
CMD62  arg=0xEFAC62EC          Freischaltung
CMD62  arg=0x10210002          Read-RAM-Backdoor
-----------------------------------------------  pro 512-Byte-Block:
CMD35  arg=<RAM-Adresse>       Startadresse setzen
CMD36  arg=512                 Länge
CMD38  arg=0                   RAM-Leseoperation ausführen
CMD17  arg=0                   einen 512-Byte-Block aus RAM holen
-----------------------------------------------
CMD62  arg=0xEFAC62EC          Freischaltung
CMD62  arg=0x00DECCEE          Backdoor schließen
```

Schreiben läuft analog über `0x10210001` mit CMD24/CMD25 statt CMD17.

**Adresslandkarte des Controllers (aus `shellcode/common.h`):**

| Konstante | Wert | Bedeutung |
|---|---|---|
| `BOOTROM_ADDR` | `0x00000` | BootROM |
| `FW_ADDR` | `0x40000` | Firmware-Image |
| `FW_SIZE` | `0x20000` | 128 KB Firmware |
| `LOAD_FW_ADDR` | `0x08020\|1` | Rücksprungadresse (Thumb-Bit gesetzt) |
| `MMC_HANDLERS_ADDR` | `0x60030` | Vektortabelle der Kommando-Handler |

Der Bereich `0x00000`–`0x7FFFF` (512 KB) deckt BootROM, Firmware und die
Handler-Tabelle ab. Genau diesen Bereich liest `dump_fw_bootrom.c` aus.

**Das ist der Kandidatenbereich für den RPMB-Key**, sollte er überhaupt im Controller-RAM
liegen: Der Key muss beim Boot irgendwohin geladen werden, damit der Hardware-HMAC
rechnen kann. Ob er dabei in lesbaren RAM gelangt oder in einem abgeschotteten
RPMB-Teil bleibt, ist **nicht belegt** — das ist die eine offene Frage, die nur
ein Leseversuch beantwortet.

---

## 4. Der weitere Weg, wenn man Lesen kann

Mit `0x10210001` (Write-RAM-Backdoor) und `CMD60 / 0xABCD1280` hat man Code-Execution im
Controller — das ist der Weg, den das arXiv-Paper (Abschnitt V-C) geht:

1. Payload in einen ungenutzten RAM-Bereich schreiben (Write-RAM-Backdoor).
2. In der Vektortabelle den Eintrag für CMD8 (`SEND_EXT_CSD`, liegt bei
   `MMC_HANDLERS_ADDR` `0x60030`) auf den Payload zeigen lassen.
3. CMD8 auslösen → eigener Code läuft im Controller.

Der Code im Paper ist ein reiner **Fault-Observer**: Zählschleife, Ergebnis in ein
ungenutztes Extended-CSD-Register schreiben, `CMD8` ausführen. Damit lässt sich messen,
ob ein EM-Puls den Controller getroffen hat.

**Wichtig für uns:** Für Code-Execution braucht man diesen Weg nicht. Für einen reinen
RAM-Leseversuch genügt Abschnitt 3 — und der braucht **keinen** Schlüssel, keine
RPMB-Authentifizierung und keine Signaturprüfung, weil der Controller im BootROM-Modus
seine eigene Firmware nicht mehr ausführt.

---

## 5. Was der T48 davon kann — und was nicht

| Kommando | T48 (`Xgpro.exe`) | Beleg |
|---|---|---|
| CMD1 mit Knock-Code | **nein** — Arg fest im Programmer | `T48-STATUS.md` §3 |
| CMD60 | **nein** — keine Vendor-Strings | `T48-STATUS.md` §4 |
| CMD62 | **nein** — dito | `T48-STATUS.md` §4 |
| CMD35/36/38 | **ja** — Erase-Deskriptor `0x0e` | `T48-STATUS.md` §3 |
| CMD17 | **ja** — Lese-Deskriptor `0x0d` | `T48-STATUS.md` §3 |
| CMD24/25 | **ja** — Schreib-Deskriptor `0x1f` | `T48-STATUS.md` §3 |

Der T48 hat also **3 von 6 nötigen Kommandos** — aber genau die drei fehlen, die die Tür
öffnen. Das ist kein Einstellungsproblem: Die eMMC-Abläufe liegen als `.alg`-Bytecode in
der Programmer-Firmware (`T48-STATUS.md` §4a), und Xgpro schickt keine Rohkommandos.

### 5.1 Sonde am Gerät (1.11.2026) — Ergebnis: kein beobachtbarer Kanal

Hypothese: Der Sub-Opcode im Top-Opcode `0x27` ist frei wählbar und der Programmer
reicht ihn womöglich an die Karte durch. Die belegten Sub-Opcodes folgen exakt dem Muster

```
sub_opcode = 0x40 + CMD-Nummer
0x46 → CMD6    0x4C → CMD12   0x4D → CMD13   0x50 → CMD16
0x57 → CMD23   0x5C → CMD28   0x5D → CMD29
```

daraus wären CMD1 = `0x41`, CMD60 = `0x7C`, CMD62 = `0x7E`.

Gemessen wurde auf KLMAG1JENB-B041 (eMMC 5.1, 16 GB, SEC_COUNT 0x01D1F000)
mit `t48-mac/sub_op_probe.py`, `sub_op_timing.py`, `sub_op_capture.py`,
`sub_op_stability.py`, `reply_width.py`, `vendor_forward_test.py`.

**Die Quittung auf EP1 ist inhaltsleer.** Jede `0x27`-Anfrage wird mit genau
8 Byte beantwortet, es folgt kein zweites Paket:

```
27 00 10 00 00 09 SS 00        SS = Byte 6
```

Byte 6 ist **weder argument- noch kommandoabhängig**:

| Versuch | Befund |
|---|---|
| `0x7E` mit Arg `0`, `0xFFFFFFFF`, `0xEFAC62EC`, `0x00DECCEE` | immer dasselbe Byte |
| `0x4C` mit Arg `0` gegen Arg `0xFFFFFFFF` | identisch |
| `0x41` mit demselben Arg in zwei Läufen | einmal `0x08`, einmal `0x00` |
| A/B-Alternation `0x57`↔`0x7E`, `0x57`↔`0x7C` | das **erste** Paket nach einem Wechsel trägt `0x08`, alle folgenden `0x00` |
| `0x57` mit 20 ms Wartezeit vor dem Lesen | `0x48` |

Die beobachteten Werte `0x00`, `0x08`, `0x40`, `0x48` sind Bits (Bit 3 und Bit 6),
die unabhängig ein- und ausgehen. Es ist ein Einschwing-/Restzustand des Programmers,
kein Kartenstatus.

**Damit ist die in `PROTOCOL.md` §19.3 notierte Regel `reply_buf[1] != 0` = Erfolg
doppelt widerlegt:** Byte 1 ist immer `0x00`, und die vermutete Ersatzstelle (Byte 6)
trägt keine Information. Ein Zwischenbefund aus dem ersten Lauf — `0x41` allein
zeigte `0x08` und sei damit „weitergereicht" — hat sich im zweiten Lauf als
Artefakt aufgelöst.

**Der Backdoor-Test war strukturell unfähig.** Nach `CMD62 / 0x10210002` wurde
derselbe Bereich erneut gelesen (Massenpfad `0x0d`), Ergebnis unverändert. Das
beweist aber nichts: Die Backdoor verlangt die Folge **CMD35 (Adresse) → CMD36
(Länge) → CMD38 (Operation ausführen) → CMD17 (Block holen)**. Ohne CMD38 wird
nichts in den Datenpuffer gestellt — eine Massenlesung über CMD18 kann die
Umleitung gar nicht sehen. CMD38 ist ohne geöffnete Backdoor aber ein
**Löschbefehl**; sie als Test einzusetzen verletzt die Regel „keine Schreib-
operation ohne vollständiges Backup" und unterbleibt.

**Was der Versuch trotzdem zeigt:**

1. `0xFF` erhält **keine Antwort** und verkeilt den Endpunkt bis zum physischen
   Replug. Die Firmware prüft den Sub-Opcode also gegen einen gültigen Bereich.
2. `0x7C` und `0x7E` antworten — sie liegen innerhalb dieses Bereichs, anders als
   `0xFF`. Der angenommene Bereich reicht mindestens bis `0x7E`, also über
   CMD31 hinaus.
3. Die Karte blieb in allen Läufen unberührt: vollständiger extCSD-Vergleich über
   alle 512 Byte vor/nach jedem Lauf ohne Änderung, `PART_CONFIG` konstant `0x48`.

**Schlussfolgerung.** Ein Sub-Opcode innerhalb des angenommenen Bereichs wird
quittiert, ohne dass sich daraus ablesen lässt, ob er die Karte erreicht. Zusammen
mit `T48-STATUS.md` §4 (keine Vendor-Strings in `Xgpro.exe`) spricht alles dafür,
dass der vorhandene `.alg`-Bitstream CMD60/CMD62 **nicht** trägt — bewiesen ist
das nicht, weil der T48 auf dieser Ebene keine Kartenantwort sichtbar macht.

**Der eine Versuch, der es entscheiden würde:** die CMD- und CLK-Leitung am
eMMC-Sockel mitlesen (Logikanalysator oder Scope) und ein `0x7E`-Paket gegen ein
`0x57`-Paket vergleichen. Erzeugt `0x57` Bustraffic und `0x7E` keinen, ist die
Frage endgültig beantwortet. Dieser Weg verlangt eine Messsonde am Sockel und
wurde bisher ausgeschlossen.

**Gefahrenhinweis für jede Fortsetzung:** Ein Durchsweepsen von `0x40`–`0x5F` ist
**nicht** zulässig. Nach derselben Zuordnung wären das CMD0 (GO_IDLE_STATE,
Karte zurücksetzen), CMD15 (`0x4F`, GO_INACTIVE_STATE), CMD24 (`0x58`,
**Schreiben**), CMD28/CMD29 (`0x5C`/`0x5D`, **Write-Protect setzen/löschen**).
Nur gezielte Sub-Opcodes mit gewähltem Argument testen — und `0xFF` oder andere
Werte außerhalb des Bereichs gar nicht erst senden.

**UFPI kann mehr:** ein host-seitiger CMD56-Helfer (`0x38` → `0xedf350`) existiert, und
die Entsperrfolge `0x1BE / 0xEFAC62EC`, `0x1BE / 0x0FAC0070`, `0x3E / 0x00DECCEE` steht
im Binary (`EASYJTAG-HANDOFF.md` §9.11.1/9.11.2). Ob UFPI den vollen CMD62-Backdoor-Weg
durchreicht, ist nicht belegt — seine RPMB-Funktionen laufen jedenfalls in der
Programmer-Firmware, nicht als Host-Frames (§9.11.4).

---

## 6. Was der Weg für unser eigentliches Ziel bedeutet

Der reparierte TV braucht **keinen** Key. Der USB-Updater schreibt im Bootloader-Kontext,
dort steht der Key dem SoC ohnehin zur Verfügung. Der Key ist nur nötig, wenn man
RPMB-authentifizierte Daten **von außen** schreiben will — also für eine Vorrichtung
abseits des Geräts.

Damit ist die Key-Frage keine Reparaturfrage mehr, sondern eine Werkzeugfrage: Kann man
den Controller-RAM lesbar machen? Wenn ja, ist der Key ein Nebenprodukt des Dumps, falls
er dort liegt.

---

## 7. Offene Fragen

1. Reagiert KLMAG1JENB-B041 auf den CMD1-Knock `0x69FF87A9`? (Generation 5.1, ungeprüft)
2. Liegt der RPMB-Key im lesbaren Controller-RAM, oder in einem abgeschotteten Bereich?
3. Welcher Host-Kanal steht zur Verfügung: RPi Pico mit eigenem SDIO/PIO-Programm,
   EasyJTAG unter Windows, oder ein Board mit direktem MMC-Bus?

Nur Frage 3 ist eine Beschaffungsfrage — 1 und 2 beantwortet der erste Leseversuch.

---

## Quellen

- `oranav/i9300_emmc_toolbox` — GitHub, GPLv3, Oran Avraham 2017. Lokale Kopie:
  `~/rea-work/samsung_ref/` (`common.c`, `common.h`, `dump_fw_bootrom.c`,
  `change_boot_partition_size.c`, `shellcode.h`).
- Fukami, Buurke: *Keyless Entry: Breaking and Entering eMMC RPMB with EMFI*,
  arXiv 2511.22340 v1, 27.11.2025 — https://arxiv.org/abs/2511.22340
  (Abschnitt IV-B verweist auf Avraham als Vorarbeit; Abschnitt V-C nutzt exakt die
  CMD62-Write-RAM-Backdoor plus CMD8-Vektor-Hijack.)
- `oscardagrach/toshiba_emmc_vendor_cmd_fuzzer` — Gegenbeispiel: Toshiba benutzt CMD56
  mit einem 512-B-Frame `{op, pad[3], pw, buf[504]}`, Status `0xA0`/`0xE0`.
  Für Samsung **nicht** anwendbar; die Familien sind verschiedene Schnittstellen.
- Lokal: `T48-STATUS.md`, `EASYJTAG-HANDOFF.md` §9.11.
