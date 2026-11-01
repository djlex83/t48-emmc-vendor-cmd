# Wege 2 und 3 — Logikanalysator und eigener Bitstream

Stand 1.11.2026. Fortsetzung von `SAMSUNG-VENDOR-CMD.md` §5.1.
Die T48-Sonde ist erschöpft: Der Programmer zeigt keine Kartenantwort. Also muss
entweder **am Bus** gemessen werden (Weg 2) oder der **Bitstream ersetzt werden**
(Weg 3). Beide brauchen dieselbe Hardware — einen Logikanalysator. Deshalb zuerst die
Beschaffungsfrage.

---

## Weg 2 — Logikanalysator am eMMC-Bus

### Die Frage, die er beantwortet

Sendet der T48 bei einem `0x27`-Paket mit Sub-Opcode `0x7E` irgendetwas auf den
eMMC-Bus? Das ist die einzige offene Frage aus §5.1, und sie ist binär.

### Was gemessen wird

| Signal | Zweck |
|---|---|
| CLK | Takt; ohne Flanken läuft gar kein Busverkehr |
| CMD | Kommando- und Antwortleitung, open-drain |
| DAT0 | Datenleitung; zeigt, ob ein Datenblock übertragen wird |
| RST_n (optional) | Controller-Reset, erklärt Zustandswechsel |

Ein 4-Kanal-Gerät genügt. Mehr Kanäle (DAT1–3, VCCQ) sind erst nötig, wenn zusätzlich
dekodiert werden soll.

### Der entscheidende Trick: es genügt „Aktivität ja/nein"

Für die Frage reicht **das Vorhandensein von Flanken**, nicht die Dekodierung.
Damit genügt ein billiger Analysator mit 24 MS/s — er sieht zwar keine Bitwerte,
aber sicher, ob der Bus überhaupt arbeitet.

**Messreihe:**

| Paket | Erwartung |
|---|---|
| `0x46` (CMD6, in `setup_area` benutzt) | **muss** Bustraffic zeigen — Positivkontrolle |
| `0x4C` (CMD12) | sollte Traffic zeigen |
| `0x57` (CMD23) | sollte Traffic zeigen |
| `0x7E` (hyp. CMD62) | fraglich |
| `0x7C` (hyp. CMD60) | fraglich |

Erzeugt die Positivkontrolle Traffic und `0x7E` keinen, ist §5.1 endgültig beantwortet:
Der vorhandene Bitstream reicht nicht, Weg 3 ist zwingend.

**Nicht wiederholen:** `0xFF` oder Werte außerhalb `0x40`–`0x7F` senden — sie verkeilen
den Programmer bis zum Replug (belegt in §5.1).

### Abgriff ohne Löten

Die Karte steckt in einem BGA-Sockeladapter. Drei Wege, in steigendem Aufwand:

1. **Messspitzen an den Sockelfedern** während die Karte steckt — riskant für
   Kurzschlüsse, nur mit sehr feinen Nadeln.
2. **Zwischenadapter mit Testpunkten** — ein zweiter Sockel, auf dem die vier
   interessanten Pins als Lötpads herausgeführt sind. Sauberste Lösung ohne Eingriff
   am Programmer.
3. **Direkt am Kartengehäuse** — bei BGA nicht möglich.

Empfehlung: Variante 2. Ein Adapter ist einmal gefertigt und dient auch Weg 3.

### Hardware

- Untergrenze für Aktivitätsnachweis: 8-Kanal-LA, 24 MS/s (Saleae-Klon, ~15 €).
- Für echte Dekodierung bei 26–52 MHz Takt: ≥ 200 MS/s pro Kanal (DSLogic U3Pro,
  Saleae Logic 8, oder ein Scope ≥ 100 MHz Bandbreite).
- Dekodier-Software: sigrok/PulseView hat einen SD/eMMC-Decoder (`sdcard_sd`);
  für die reine Ja/Nein-Frage nicht nötig.

---

## Weg 3 — eigener `.alg`-Bitstream

### Warum das nicht „nur Verilog" ist

Der T48 besteht aus einem USB-Controller (Cypress FX2) und einem Spartan-6 LX9. Die
eMMC-Abläufe liegen im FPGA-Bitstream, verpackt als `.alg`. Um einen eigenen Bitstream
einzuspielen, muss man drei Dinge kennen, die in keinem vorhandenen Dokument stehen:

1. **Wie spricht der FX2 mit dem FPGA?** Adress-/Datenbus, Handshake, Endpunkt-Zuordnung.
2. **Welche FPGA-Pins gehen auf den eMMC-Sockel?** Pinbelegung und IO-Standard (1,8 V / 3,3 V).
3. **Wie ist das `.alg` verpackt?** Das ist bekannt: JAMCRC ab `0x228`, zero-RLE,
   Xilinx-Sync `AA 99 55 66`, 340604 Byte dekomprimiert (`T48-STATUS.md` §4a,
   Werkzeuge `alg_tool.py`, `alg_unrle.py`).

Punkt 1 und 2 sind Platinen-Reverse-Engineering. Punkt 3 ist gelöst.

### Der Ausweg: Differenzbildung statt Bitstream-Dekodierung

Ein Spartan-6-Bitstream vollständig zu dekodieren ist aufwendig. Für die Pinbelegung
braucht man das auch nicht — **man kann bestehende Bitstreams gegeneinander diffen.**
Zwei Beobachtungen machen das möglich:

- Zu jeder Variante gibt es `_18` und `_33` (VCCQ 1,8 V / 3,3 V). Das ist derselbe
  Entwurf mit unterschiedlichem IO-Standard. Ein XOR beider Bitstreams zeigt genau
  die Bits, die den IO-Standard und damit IO-Sites kodieren.
- Zu jeder Chipfamilie (eMMC, NAND, SPI) gibt es eine eigene `.alg`. Ein XOR zwischen
  Familien zeigt, welche IO-Sites je Familie überhaupt benutzt werden — also die
  Aufteilung des Sockels.

Damit lässt sich die Pinbelegung **aus den vorhandenen Dateien** ableiten, ohne den
Bitstream zu verstehen. Das ist der gangbare Weg.

### Teilschritte

1. `.alg`-Dateien aller Varianten sammeln (`t48-mac/`, `ref-minipro/`).
2. Paare `_18`/`_33` dekomprimieren und XORen → IO-Standard-Bits lokalisieren.
3. Familien gegeneinander XORen → benutzte IO-Sites je Familie.
4. Platine fotografieren, FX2↔FPGA-Bus mit dem Analysator aus Weg 2 mitschneiden,
   während Xgpro ein `.alg` hochlädt → Übertragungsformat.
5. HDL für Spartan-6: eMMC-Kommandokern (CMD-Leitung, CRC7, R1/R2, CMD60/62,
   clock domain), Datenpfad.
6. Constraints aus Schritt 2/3, Synthese mit **ISE 14.7** (nicht auf macOS —
   Linux-VM oder Windows), `.alg` verpacken mit `alg_tool.py`.

### Aufwand, ehrlich

Schritte 1–3 sind Wochenende-Arbeit und liefern schon die Pinbelegung.
Schritt 4 hängt am Analysator. Schritt 5–6 sind mehrere Wochen und brauchen eine
ISE-Umgebung. Das ist ein Forschungsprojekt, kein Nachmittag.

---

## Gemeinsame Voraussetzung

**Der Logikanalysator wird für beide Wege gebraucht.** Weg 2 beantwortet die Frage
in Stunden; Weg 3 beginnt mit demselben Gerät. Deshalb ist die Beschaffung der erste
Schritt, unabhängig davon, welcher Weg am Ende trägt.

---

## Was parallel läuft: die öffentliche Ausschreibung

Leute mit UFPI oder EasyJTAG können die Frage möglicherweise beantworten, ohne dass
wir Hardware beschaffen. Der Text dafür liegt in `public-repo/README.md`.
Gesucht sind:

1. Ob UFPI/EasyJTAG `CMD62 / 0xEFAC62EC` senden können und was der eMMC antwortet.
2. Woher die RPMB-Key-Anzeige ihren Wert nimmt — Boot-Metadaten oder Controller-RAM.
3. USB-Mitschnitte (Wireshark + usbmon) des Vendor-Kommandopfads.

---

## Sicherheitsauflagen (unverändert)

- Keine Schreiboperation ohne vollständiges Backup, `T48_ALLOW_WRITE=1` bleibt gesperrt.
- Kein RPMB-Key im Klartext in Dateien oder ins öffentliche Repo.
- `CMD38` wird nicht als Test eingesetzt — ohne geöffnete Backdoor ist es ein Löschbefehl.
- Kein Sweep über `0x40`–`0x5F`: `0x40` = CMD0 (Reset), `0x4F` = CMD15 (inaktiv),
  `0x58` = CMD24 (Schreiben), `0x5C`/`0x5D` = CMD28/29 (Write-Protect).
