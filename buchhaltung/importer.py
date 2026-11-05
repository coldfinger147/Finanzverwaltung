"""Import aus der Excel-EÜR-Vorlage (Pierre Tunger, Blätter "Einn" und "Ausg").

Alle importierten Buchungen werden als "Prüfen" markiert. Bereich (FFS/FFD)
und Kategorie sind Vorschläge, die in der Buchungsliste bestätigt werden.
"""

import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal

import openpyxl
from django.db import transaction

from .models import Buchung, Kategorie, Mandant, runde

# Reihenfolge zählt: der erste Treffer gewinnt.
EUER_ART_ZU_CODE = [
    ("umsatzsteuerfrei", "BE_UST_FREI"),
    ("umsatzsteuerpflichtig", "BE_UST_PFLICHTIG"),
    ("veräußerung", "BE_ANLAGE_VERKAUF"),
    ("erstattete", "BE_UST_ERSTATTUNG"),
    ("beiträge", "BA_BEITRAEGE"),  # vor "kfz": der Text lautet "... (ohne Gebäude und Kfz)"
    ("waren", "BA_WAREN"),
    ("fremdleistung", "BA_FREMDLEISTUNG"),
    ("personal", "BA_PERSONAL"),
    ("geringwertig", "BA_GWG"),
    ("telekommunikation", "BA_TELEKOM"),
    ("übernachtung", "BA_REISE"),
    ("fahrtkosten", "BA_FAHRTKOSTEN"),
    ("verpflegung", "BA_VERPFLEGUNG"),
    ("kraftfahrzeug", "BA_KFZ"),
    ("kfz", "BA_KFZ"),
    ("fortbildung", "BA_FORTBILDUNG"),
    ("rechts", "BA_BERATUNG"),
    ("leasing", "BA_MIETE_BEWEGLICH"),
    ("raumkosten", "BA_RAUM"),
    ("geschäftsräume", "BA_RAUM"),
    ("werbe", "BA_WERBUNG"),
    ("geschenk", "BA_GESCHENKE"),
    ("bewirtung", "BA_BEWIRTUNG"),
    ("schuldzinsen", "BA_SCHULDZINSEN"),
    ("gezahlte umsatzsteuer", "BA_UST_AN_FA"),
]

# Feinere Vorschläge für die Sammelkategorie "Waren", anhand des Buchungstexts.
TEXT_ZU_CODE = [
    (r"druckerpatron|papier|schnellhefter|ordner|porto|briefmark", "BA_BUERO"),
    (r"vpn|software|lizenz|abo|cloud|domain|hosting", "BA_SOFTWARE"),
    (r"arbeitsschuh|arbeitskleid|handschuh|schutzbrille", "BA_ARBEITSKLEIDUNG"),
    (r"flug|bahn|zug|taxi", "BA_FAHRTKOSTEN"),
    (r"hotel|übernachtung", "BA_REISE"),
    (r"ihk|beitrag|versicherung|gebühr", "BA_BEITRAEGE"),
]

FFS_TEXT = re.compile(r"kommentat|kommentier|tv|experte|trainer|coach|snooker|honorar|billard", re.I)
FFD_TEXT = re.compile(r"objekt|montage|planung|tischheizung|solar|material|lieferung|wartung|reparatur|sls", re.I)

GWG_GRENZE = Decimal("800")


def _norm(wert):
    return re.sub(r"[^a-z0-9äöüß]", "", str(wert or "").lower())


def _spalten(kopf):
    spalten = {}
    for i, zelle in enumerate(kopf):
        n = _norm(zelle)
        if not n:
            continue
        if n.startswith("belegnr"):
            spalten["belegnr"] = i
        elif n.startswith("rechnnr"):
            spalten["rechnungsnummer"] = i
        elif n.startswith("rechndatum"):
            spalten["rechnungsdatum"] = i
        elif n.startswith("zahlungsdatum"):
            spalten["datum"] = i
        elif n.startswith("netto"):
            spalten["netto"] = i
        elif n.startswith("brutto"):
            spalten["brutto"] = i
        elif n.startswith("ustsatz"):
            spalten["satz"] = i
        elif n.startswith("buchungstext"):
            spalten["text"] = i
        elif "eür" in n and "art" in n:
            spalten["euer_art"] = i
        elif "bwa" in n and "art" in n:
            spalten["bwa_art"] = i
    return spalten


def _datum(wert):
    if isinstance(wert, datetime.datetime):
        return wert.date()
    if isinstance(wert, datetime.date):
        return wert
    return None


def _zahl(wert):
    if wert in (None, ""):
        return None
    try:
        return Decimal(str(wert))
    except Exception:
        return None


def kategorie_code(euer_art, text, typ):
    art = (euer_art or "").lower()
    code = next((c for schluessel, c in EUER_ART_ZU_CODE if schluessel in art), None)
    if typ == "ausgabe" and code in (None, "BA_WAREN"):
        code = next((c for muster, c in TEXT_ZU_CODE if re.search(muster, text or "", re.I)), code)
    if code is None:
        code = "BE_UST_PFLICHTIG" if typ == "einnahme" else "BA_SONSTIGE"
    return code


def bereich(text, bwa_art, satz, typ):
    text = text or ""
    bwa = (bwa_art or "").lower()
    if typ == "einnahme":
        if FFD_TEXT.search(text):
            return "FFD"
        if FFS_TEXT.search(text) or satz == 7:
            return "FFS"
        return "FFD"
    if "tv" in bwa or FFS_TEXT.search(text):
        return "FFS"
    return "FFD"


@dataclass
class Ergebnis:
    angelegt: int = 0
    uebersprungen: int = 0
    je_bereich: dict = field(default_factory=dict)
    hinweise: list = field(default_factory=list)


def _kopfzeile(blatt):
    for nr, zeile in enumerate(blatt.iter_rows(max_row=15, values_only=True), start=1):
        if any(_norm(z).startswith("belegnr") for z in zeile):
            return nr, _spalten(zeile)
    raise ValueError(f"Blatt {blatt.title}: Kopfzeile mit 'Beleg Nr.' nicht gefunden.")


def importiere(pfad, jahr=None, trocken=False):
    mappe = openpyxl.load_workbook(pfad, read_only=True, data_only=True)
    mandanten = {m.kuerzel: m for m in Mandant.objects.filter(kuerzel__in=["FFS", "FFD"])}
    kategorien = {k.code: k for k in Kategorie.objects.all()}
    ergebnis = Ergebnis()

    with transaction.atomic():
        for blattname, typ in (("Einn", "einnahme"), ("Ausg", "ausgabe")):
            if blattname not in mappe.sheetnames:
                ergebnis.hinweise.append(f"Blatt {blattname} fehlt, übersprungen.")
                continue
            blatt = mappe[blattname]
            kopf_nr, sp = _kopfzeile(blatt)
            for zeile in blatt.iter_rows(min_row=kopf_nr + 1, values_only=True):
                datum = _datum(zeile[sp["datum"]]) if "datum" in sp else None
                satz_roh = _zahl(zeile[sp["satz"]]) if "satz" in sp else None
                brutto = _zahl(zeile[sp["brutto"]]) if "brutto" in sp else None
                netto = _zahl(zeile[sp["netto"]]) if "netto" in sp else None
                if datum is None or not (brutto or netto):
                    continue
                if jahr and datum.year != jahr:
                    continue
                satz = runde((satz_roh or 0) * 100) if satz_roh is not None and satz_roh < 1 else (satz_roh or Decimal("0"))
                satz = Decimal(int(satz))
                if not brutto:
                    brutto = runde(netto * (100 + satz) / 100)
                text = str(zeile[sp["text"]] or "").strip() if "text" in sp else ""
                euer_art = zeile[sp["euer_art"]] if "euer_art" in sp else ""
                bwa_art = zeile[sp["bwa_art"]] if "bwa_art" in sp else ""
                nr = zeile[sp["belegnr"]] if "belegnr" in sp else None
                rechnungsnummer = zeile[sp["rechnungsnummer"]] if "rechnungsnummer" in sp else None
                alte_nr = f"XLS-{blattname}-{nr or rechnungsnummer or '?'}"
                brutto = runde(brutto)

                if Buchung.objects.filter(alte_belegnummer=alte_nr, datum=datum, brutto=brutto).exists():
                    ergebnis.uebersprungen += 1
                    continue

                kuerzel = bereich(text, bwa_art, satz, typ)
                code = kategorie_code(euer_art, text, typ)
                buchung = Buchung(
                    mandant=mandanten[kuerzel],
                    datum=datum,
                    rechnungsdatum=_datum(zeile[sp["rechnungsdatum"]]) if "rechnungsdatum" in sp else None,
                    rechnungsnummer=str(rechnungsnummer or "")[:60],
                    alte_belegnummer=alte_nr,
                    text=text[:255] or "(ohne Text)",
                    kategorie=kategorien[code],
                    brutto=brutto,
                    ust_satz=satz,
                    pruefen=True,
                )
                buchung.save()
                ergebnis.angelegt += 1
                ergebnis.je_bereich[kuerzel] = ergebnis.je_bereich.get(kuerzel, 0) + 1
                if typ == "ausgabe" and buchung.netto > GWG_GRENZE:
                    ergebnis.hinweise.append(
                        f"{buchung.belegnummer} „{text}“ ({buchung.netto} € netto) liegt über 800 € netto: "
                        "Anlagevermögen mit Abschreibung prüfen."
                    )
        if trocken:
            transaction.set_rollback(True)
    return ergebnis
