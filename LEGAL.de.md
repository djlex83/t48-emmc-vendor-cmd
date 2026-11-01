[English](LEGAL.md) · **Deutsch** · [中文](LEGAL.zh.md)

# Umfang, Berechtigung und rechtliche Einordnung

Dieses Repository dokumentiert Forschungs- und Reparaturarbeit an Hardware, die **dem
Autor gehört**.

*Keine Rechtsberatung. Siehe „Grenzen" am Ende.*

---

## Was dieses Repository ist

* **Reparatur und Datenrettung** an eigenen Geräten — Lesen und Neuschreiben des eMMC einer
  Sony-Fernseher-Platine, die dem Autor gehört.
* **Interoperabilitätsforschung**: zu verstehen, wie sich dokumentierte und herstellerspezifische
  Schnittstellen eines Speichermediums verhalten, damit ein defektes Gerät repariert werden
  kann.
* **Messprotokoll**: was wir gesendet haben, was zurückkam, was es beweist und was nicht.
  Negative Ergebnisse werden genauso deutlich veröffentlicht wie positive.

## Was dieses Repository nicht ist

* Kein Werkzeug und keine Anleitung für den Zugriff auf Geräte, die dem Autor nicht gehören.
  Jeder beschriebene Hardwareschritt wurde an Hardware im Besitz des Autors ausgeführt.
* Keine DRM-Umgehung. Die Extraktion von Widevine-L1-Keyboxen liegt ausdrücklich außerhalb
  des Umfangs und kommt in diesem Repository nicht vor. Zu geschützten Medieninhalten
  findet sich hier nichts.
* Kein Vertriebsweg. **Keine Fremdbinaries, keine Hersteller-Installer, keine
  Firmware-Abbilder, keine Karten-Dumps.** Wo ein Herstellerwerkzeug beschrieben wird,
  halten wir Fakten fest (Opcodes, Adressen, Kontrollfluss) — niemals Code oder Dateien.
* Keine Quelle für Geheimnisse. Kein RPMB-Schlüsselmaterial, keine Zugangsdaten, keine
  Geräteseriennummern.

## Rechtliche Grundlage der Analyse (EU / Deutschland)

* Reverse Engineering zum Zweck der **Interoperabilität** ist in Artikel 6 der Richtlinie
  2009/24/EG geregelt, in Deutschland umgesetzt als § 69e UrhG. Die Analyse hier zielt auf
  die Schnittstellen, die zum Lesen und Neuschreiben eines Speichermediums für die Reparatur
  nötig sind; sie ist nicht auf das Kopieren oder Verbreiten der analysierten Software
  gerichtet.
* Das Material zu den Vendor-Kommandos ist überwiegend **öffentlicher Stand der Technik** —
  `oranav/i9300_emmc_toolbox` (GPLv3, 2017) und arXiv 2511.22340 (2025). Wir zitieren diese
  Arbeiten; wir geben ihren Quellcode hier nicht wieder.
* Jeder Befund ist zugeordnet. Wo eine Aussage aus unseren eigenen, unbestätigten Notizen
  stammt, ist sie als solche gekennzeichnet.

## Zu den Werkzeugen in `scripts/`

Der T48-Treiber ist ein **Diagnose- und Reparaturtreiber**. Er ist standardmäßig nur lesend:
Jeder Schreib- oder Löschpfad ist hinter der Umgebungsvariablen `T48_ALLOW_WRITE=1` gesperrt,
die der Autor nicht setzt. Die Sonden-Skripte senden ausschließlich Kommandos.

Bekannte Gefahren des Protokolls sind in den Skripten selbst dokumentiert, denn eine
umsichtige Reproduktion ist der Sinn ihrer Veröffentlichung.

## Was trotzdem riskant wäre und deshalb nicht veröffentlicht wurde

* **Sony-Firmware-Abbilder und Karten-Dumps** — urheberrechtlich geschütztes Material Dritter.
  Wir veröffentlichen die Analyse des Partitionslayouts und der Update-Mechanik, nicht die Bytes.
* **Vollständige Reverse-Engineering-Protokolle von Herstellerbinaries** — wir veröffentlichen
  die für Interoperabilität nötigen Befunde (`docs/ufpi-findings.md`), nicht das Binary.
* **Schlüsselmaterial jeder Art** — per Richtlinie ausgeschlossen.

## Grenzen

Diese Notiz reduziert die offensichtlichen Risiken; sie garantiert nichts.

* Sie ist von einem Ingenieur geschrieben, nicht von einem Juristen, und ist **keine
  Rechtsberatung**.
* Haftungsregeln unterscheiden sich je nach Rechtsordnung. Wenn Rechtssicherheit zählt —
  etwa vor einer kommerziellen Veröffentlichung oder vor dem Vertrieb der Werkzeuge als
  Produkt — sollte ein zugelassener Anwalt sie prüfen.
* Urheber- und Umgehungsschutzregeln unterscheiden sich zwischen EU, USA und anderen
  Rechtsordnungen. Dieses Repository ist aus EU-/deutscher Sicht geschrieben.

Wer meint, etwas hier sollte nicht öffentlich sein, möge ein Issue öffnen; wir handeln dann.
