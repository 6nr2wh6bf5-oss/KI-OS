---
name: brandschutz-bericht
description: Erstellt Zustandsanalysen, Brandschutzkonzepte und weitere technische Berichte aus Stichworten, Begehungsnotizen oder Diktat einen strukturierten Brandschutzbericht oder Konzeptentwurf. Verwenden, wenn Maximilian Notizen zu einem Objekt liefert und einen Bericht, ein Protokoll oder ein Konzept will.
---

# Brandschutz-Bericht

## Ablauf
1. Berichtsart klären: **Zustandsanalyse**, **Brandschutzkonzept** (Hauptfälle), Begehungsprotokoll, Mängelbericht oder Stellungnahme. Vorlage in `30_Vorlagen/` verwenden, falls vorhanden.
2. Objekt pseudonymisieren (keine Adressen/Namen im Repo).
3. Gliederung: die Vorlage der Berichtsart aus `30_Vorlagen/` hat Vorrang. Ohne Vorlage gilt der Standard:
   1. Ausgangslage und Auftrag
   2. Objektbeschrieb (Nutzung, Gebäudekategorie, Geschosse, Personenbelegung)
   3. Feststellungen (nummeriert, je mit Fundstelle der Anforderung)
   4. Beurteilung
   5. Massnahmen mit Priorität (sofort / kurzfristig / mittelfristig) und Verantwortlichkeit
   6. Offene Punkte
4. Jede Anforderung mit Fundstelle (siehe Skill `vkf-recherche`).
5. Ausgabe als Claude Doc; Kurzfassung als Markdown in `20_Projekte/<Projekt-ID>/`.

## Spezifisch Zustandsanalyse
- Bestand vs. heutige Anforderungen (geltende VKF-Vorschriften) gegenüberstellen; Abweichungen nummeriert.
- Je Abweichung: Risiko-Einschätzung, Verhältnismässigkeit (Bestandesschutz, VKF-BSN Art. 2 prüfen), Massnahme.

## Spezifisch Brandschutzkonzept
- QSS-Stufe angeben; Konzept nach Gebäudekategorie, Nutzung, Brandabschnitte, Flucht- und Rettungswege, Kennzeichnung, Löscheinrichtungen, technische Brandschutzmassnahmen, organisatorische Massnahmen.
