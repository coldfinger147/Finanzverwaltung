"""Startbestand: Mandanten, Kategorien und Formularfelder.

Zeilennummern der Anlage EÜR werden bewusst leer gelassen: sie ändern sich
fast jedes Jahr und werden je Steuerjahr gegen das amtliche Formular gepflegt
(Admin > Formularzeilen, Haken "Zeile geprüft").
"""

MANDANTEN = [
    # kuerzel, name, art, ust_unternehmen
    ("FFS", "Felix Frede Snooker (Coach, Trainer, TV-Experte)", "freiberuf", True),
    ("FFD", "felixfrede dienstleistungen", "gewerbe", True),
    ("WHG", "Eigentumswohnung", "vermietung", False),
    ("PRV", "Privat", "privat", False),
    ("EFU", "EFU-Solartechnik", "fremd", False),
]

KATEGORIEN = [
    # code, name, typ, in_ust_va, abzugsfaehig_prozent
    ("BE_UST_PFLICHTIG", "Umsatzsteuerpflichtige Betriebseinnahmen", "einnahme", True, 100),
    ("BE_UST_FREI", "Umsatzsteuerfreie oder nicht steuerbare Betriebseinnahmen", "einnahme", True, 100),
    ("BE_ANLAGE_VERKAUF", "Veräußerung oder Entnahme von Anlagevermögen", "einnahme", True, 100),
    ("BE_UST_ERSTATTUNG", "Vom Finanzamt erstattete Umsatzsteuer", "einnahme", False, 100),
    ("BA_WAREN", "Waren, Rohstoffe und Hilfsstoffe einschl. Nebenkosten", "ausgabe", True, 100),
    ("BA_FREMDLEISTUNG", "Bezogene Fremdleistungen", "ausgabe", True, 100),
    ("BA_PERSONAL", "Ausgaben für eigenes Personal", "ausgabe", True, 100),
    ("BA_GWG", "Geringwertige Wirtschaftsgüter (bis 800 € netto)", "ausgabe", True, 100),
    ("BA_RAUM", "Miete und Nebenkosten für Geschäftsräume", "ausgabe", True, 100),
    ("BA_TELEKOM", "Telekommunikation (Telefon, Internet)", "ausgabe", True, 100),
    ("BA_SOFTWARE", "Software, Lizenzen, Online-Dienste", "ausgabe", True, 100),
    ("BA_REISE", "Übernachtungs- und Reisenebenkosten bei Geschäftsreisen", "ausgabe", True, 100),
    ("BA_FAHRTKOSTEN", "Fahrtkosten Geschäftsreisen (Bahn, Flug, Taxi)", "ausgabe", True, 100),
    ("BA_VERPFLEGUNG", "Verpflegungsmehraufwendungen (Pauschalen)", "ausgabe", True, 100),
    ("BA_KFZ", "Kfz-Kosten", "ausgabe", True, 100),
    ("BA_FORTBILDUNG", "Fortbildungskosten", "ausgabe", True, 100),
    ("BA_BERATUNG", "Rechts- und Steuerberatung, Buchführung", "ausgabe", True, 100),
    ("BA_MIETE_BEWEGLICH", "Miete/Leasing für bewegliche Wirtschaftsgüter (ohne Kfz)", "ausgabe", True, 100),
    ("BA_BEITRAEGE", "Beiträge, Gebühren, Abgaben, Versicherungen", "ausgabe", True, 100),
    ("BA_WERBUNG", "Werbekosten", "ausgabe", True, 100),
    ("BA_BUERO", "Bürobedarf, Porto, Fachliteratur", "ausgabe", True, 100),
    ("BA_ARBEITSKLEIDUNG", "Arbeitskleidung und Schutzausrüstung", "ausgabe", True, 100),
    ("BA_GESCHENKE", "Geschenke an Geschäftspartner (abziehbar)", "ausgabe", True, 100),
    ("BA_BEWIRTUNG", "Bewirtungsaufwendungen", "ausgabe", True, 70),
    ("BA_SCHULDZINSEN", "Schuldzinsen", "ausgabe", False, 100),
    ("BA_SONSTIGE", "Übrige unbeschränkt abziehbare Betriebsausgaben", "ausgabe", True, 100),
    ("BA_UST_AN_FA", "An das Finanzamt gezahlte Umsatzsteuer", "ausgabe", False, 100),
    ("NEUTRAL_PRIVAT", "Privateinlage oder Privatentnahme", "neutral", False, 100),
    ("NEUTRAL_UMBUCHUNG", "Umbuchung zwischen eigenen Konten", "neutral", False, 100),
]

# Summenfelder, die nicht direkt gebucht, sondern berechnet werden.
SUMMENFELDER = [
    ("BE_UST_VEREINNAHMT", "Vereinnahmte Umsatzsteuer"),
    ("BA_VORSTEUER", "Gezahlte Vorsteuerbeträge"),
    ("BA_BEWIRTUNG_NICHT_ABZIEHBAR", "Nicht abziehbare Bewirtungsaufwendungen (30 %)"),
    ("SUMME_BE", "Summe Betriebseinnahmen"),
    ("SUMME_BA", "Summe Betriebsausgaben"),
    ("GEWINN", "Gewinn / Verlust"),
]

JAHRE = [2024, 2025, 2026]


def lade_grunddaten(Mandant, Kategorie, FormularZeile):
    for kuerzel, name, art, ust in MANDANTEN:
        Mandant.objects.update_or_create(
            kuerzel=kuerzel, defaults={"name": name, "art": art, "ust_unternehmen": ust}
        )
    for i, (code, name, typ, in_ust_va, prozent) in enumerate(KATEGORIEN):
        Kategorie.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "typ": typ,
                "in_ust_va": in_ust_va,
                "abzugsfaehig_prozent": prozent,
                "reihenfolge": i,
            },
        )
    felder = [(c, n) for c, n, typ, *_ in KATEGORIEN if typ != "neutral"] + SUMMENFELDER
    for jahr in JAHRE:
        for code, bezeichnung in felder:
            FormularZeile.objects.get_or_create(
                jahr=jahr, formular="Anlage EÜR", code=code, defaults={"bezeichnung": bezeichnung}
            )
