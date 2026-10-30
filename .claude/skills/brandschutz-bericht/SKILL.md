---
name: brandschutz-bericht
description: Erstellt aus Stichworten, Begehungsnotizen oder Diktat einen strukturierten Brandschutzbericht oder Konzeptentwurf. Verwenden, wenn Maximilian Notizen zu einem Objekt liefert und einen Bericht, ein Protokoll oder ein Konzept will.
---

# Brandschutz-Bericht

## Ablauf
1. Berichtsart klären: Begehungsprotokoll, Mängelbericht, Brandschutzkonzept (Entwurf) oder Stellungnahme. Vorlage in `30_Vorlagen/` verwenden, falls vorhanden.
2. Objekt pseudonymisieren (keine Adressen/Namen im Repo).
3. Gliederung (Standard):
   1. Ausgangslage und Auftrag
   2. Objektbeschrieb (Nutzung, Gebäudekategorie, Geschosse, Personenbelegung)
   3. Feststellungen (nummeriert, je mit Fundstelle der Anforderung)
   4. Beurteilung
   5. Massnahmen mit Priorität (sofort / kurzfristig / mittelfristig) und Verantwortlichkeit
   6. Offene Punkte
4. Jede Anforderung mit Fundstelle (siehe Skill `vkf-recherche`).
5. Ausgabe als Claude Doc; Kurzfassung als Markdown in `20_Projekte/<Projekt-ID>/`.
