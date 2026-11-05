import datetime
import tempfile
from decimal import Decimal
from pathlib import Path

import openpyxl
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from buchhaltung import auswertung
from buchhaltung.importer import importiere, kategorie_code
from buchhaltung.models import Beleg, Buchung, Kategorie, Mandant, Protokoll, festschreiben

D = Decimal


def buche(kuerzel, code, datum, brutto, satz=19, text="Test"):
    b = Buchung(
        mandant=Mandant.objects.get(kuerzel=kuerzel),
        kategorie=Kategorie.objects.get(code=code),
        datum=datum,
        brutto=D(brutto),
        ust_satz=D(satz),
        text=text,
    )
    b.save()
    return b


class BuchungTest(TestCase):
    def test_steuer_und_belegnummer(self):
        b1 = buche("FFS", "BE_UST_PFLICHTIG", datetime.date(2026, 6, 30), "1401.70", 7)
        b2 = buche("FFS", "BE_UST_PFLICHTIG", datetime.date(2026, 9, 15), "920.00", 19)
        b3 = buche("FFD", "BE_UST_PFLICHTIG", datetime.date(2026, 1, 31), "3903.20", 19)
        self.assertEqual((b1.netto, b1.ust), (D("1310.00"), D("91.70")))
        self.assertEqual((b2.netto, b2.ust), (D("773.11"), D("146.89")))
        self.assertEqual(b1.belegnummer, "FFS-2026-0001")
        self.assertEqual(b2.belegnummer, "FFS-2026-0002")
        self.assertEqual(b3.belegnummer, "FFD-2026-0001")

    def test_festgeschrieben_ist_unveraenderbar(self):
        b = buche("FFD", "BA_WAREN", datetime.date(2026, 2, 3), "119.00")
        self.assertEqual(festschreiben(datetime.date(2026, 3, 31)), 1)
        b.refresh_from_db()
        b.text = "geändert"
        with self.assertRaises(ValidationError):
            b.save()
        with self.assertRaises(ValidationError):
            b.delete()
        with self.assertRaises(ValidationError):
            Buchung.objects.filter(pk=b.pk).update(text="x")
        with self.assertRaises(ValidationError):
            Buchung.objects.all().delete()

    def test_storno(self):
        b = buche("FFD", "BA_WAREN", datetime.date(2026, 2, 3), "119.00")
        festschreiben(datetime.date(2026, 3, 31))
        storno = b.stornieren(datum=datetime.date(2026, 4, 2))
        self.assertEqual(storno.brutto, D("-119.00"))
        self.assertEqual(storno.ust, D("-19.00"))
        self.assertEqual(storno.storno_von, b)
        with self.assertRaises(ValidationError):
            b.stornieren()

    def test_protokoll(self):
        b = buche("FFD", "BA_WAREN", datetime.date(2026, 2, 3), "119.00")
        b.text = "Neu"
        b.save()
        eintraege = Protokoll.objects.filter(modell="buchung", objekt_id=str(b.pk)).order_by("id")
        self.assertEqual([e.aktion for e in eintraege], ["angelegt", "geändert"])
        self.assertEqual(eintraege[1].vorher["text"], "Test")
        with self.assertRaises(ValidationError):
            eintraege[0].delete()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class BelegTest(TestCase):
    def test_hash_und_duplikat(self):
        beleg = Beleg(datei=SimpleUploadedFile("rechnung.pdf", b"%PDF-1.4 test"))
        beleg.save()
        self.assertEqual(len(beleg.sha256), 64)
        with self.assertRaises(ValidationError):
            Beleg(datei=SimpleUploadedFile("kopie.pdf", b"%PDF-1.4 test")).save()


class AuswertungTest(TestCase):
    def setUp(self):
        buche("FFS", "BE_UST_PFLICHTIG", datetime.date(2026, 4, 10), "1070.00", 7)
        buche("FFD", "BE_UST_PFLICHTIG", datetime.date(2026, 5, 10), "1190.00", 19)
        buche("FFD", "BA_WAREN", datetime.date(2026, 6, 10), "238.00", 19)
        buche("FFD", "BA_BEWIRTUNG", datetime.date(2026, 6, 11), "119.00", 19)
        buche("PRV", "NEUTRAL_PRIVAT", datetime.date(2026, 6, 12), "500.00", 0)
        buche("FFD", "BE_UST_PFLICHTIG", datetime.date(2026, 7, 1), "119.00", 19)  # Q3

    def test_ust_va_quartal(self):
        u = auswertung.ust_voranmeldung(*auswertung.quartal_zeitraum(2026, 2))
        self.assertEqual(u.kz81, D("1000"))
        self.assertEqual(u.kz86, D("1000"))
        self.assertEqual(u.kz66, D("57.00"))
        self.assertEqual(u.kz83, D("190.00") + D("70.00") - D("57.00"))

    def test_euer_getrennt_je_betrieb(self):
        ffs = auswertung.euer(Mandant.objects.get(kuerzel="FFS"), 2026)
        ffd = auswertung.euer(Mandant.objects.get(kuerzel="FFD"), 2026)
        self.assertEqual(ffs.summe_einnahmen, D("1070.00"))
        self.assertEqual(ffs.summe_ausgaben, D("0"))
        # FFD: 1000 + 100 netto + 209 USt; Ausgaben 200 + 70 % von 100 + 57 Vorsteuer
        self.assertEqual(ffd.summe_einnahmen, D("1309.00"))
        self.assertEqual(ffd.summe_ausgaben, D("327.00"))
        self.assertEqual(ffd.gewinn, D("982.00"))
        self.assertTrue(any("nicht abziehbar" in h for h in ffd.hinweise))

    def test_seiten_brauchen_login(self):
        url = reverse("buchhaltung:wiso")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(User.objects.create_superuser("felix", "", "x" * 12))
        for name, args in [("uebersicht", []), ("ust_va", []), ("euer", ["FFD"]), ("wiso", [])]:
            antwort = self.client.get(reverse(f"buchhaltung:{name}", args=args), {"jahr": 2026})
            self.assertEqual(antwort.status_code, 200, name)
        self.assertContains(self.client.get(url, {"jahr": 2026}), "Anlage G")


class ImportTest(TestCase):
    def _mappe(self, pfad):
        mappe = openpyxl.Workbook()
        einn = mappe.active
        einn.title = "Einn"
        einn.append(["Beleg\nNr.", "Rechn.\nNr.", "Rechn.\nDatum", "Zahlungs\nDatum*", "Zahlungsart", "Monat",
                     "Netto*", "USt.\nSatz*", "Brutto", "USt.", "Buchungstext*",
                     "Einnahmen-Art\nfür die Tabelle EÜR*", "Einnahmen-Art\nfür die Tabelle BWA*"])
        einn.append([None, "1", datetime.datetime(2024, 8, 4), datetime.datetime(2024, 8, 16), "KTO", 8,
                     1350, 0.07, 1444.5, 94.5, "Kommentatoren-/Expertentätigkeit TV Sender",
                     "Umsatzsteuerpflichtige Betriebseinnahmen", "TV Experte"])
        einn.append([None, "7", datetime.datetime(2024, 5, 1), datetime.datetime(2024, 5, 21), "KTO", 5,
                     480, 0.19, 571.2, 91.2, "Objektbetreuung Halle", "Umsatzsteuerpflichtige Betriebseinnahmen",
                     "TV Experte"])
        ausg = mappe.create_sheet("Ausg")
        ausg.append(["Beleg\nNr.", "Zahlungs\nDatum*", "Monat", "Brutto*", "USt.\nSatz*", "USt.", "Netto",
                     "Buchungstext*", "Ausgaben-Art\nfür die Tabelle EÜR*", "Ausgaben-Art\nfür die Tabelle BWA*"])
        ausg.append(["1", datetime.datetime(2024, 7, 2), 7, 236.93, 0.19, 37.83, 199.1,
                     "Flug München Kommentieren", "Sonstige tatsächliche Fahrtkosten", "TV-Experte"])
        ausg.append(["2", datetime.datetime(2024, 3, 2), 3, 119, 0.19, 19, 100, "Bohrkrone",
                     "Waren, Rohstoffe, Hilfsstoffe", None])
        ausg.append(["3", datetime.datetime(2024, 3, 3), 3, 50, 0.19, 7.98, 42.02, "IHK Beitrag",
                     "Beiträge, Gebühren, Abgaben, Versich. (ohne Gebäude und Kfz)", None])
        ausg.append([None, None, None, None, None, None, None, None, None, None])
        mappe.save(pfad)

    def test_import_und_idempotenz(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "euer.xlsx"
            self._mappe(pfad)
            ergebnis = importiere(pfad)
            self.assertEqual(ergebnis.angelegt, 5)
            self.assertEqual(ergebnis.je_bereich, {"FFS": 2, "FFD": 3})
            tv = Buchung.objects.get(alte_belegnummer="XLS-Einn-1")
            self.assertEqual((tv.mandant.kuerzel, tv.ust_satz, tv.netto), ("FFS", D("7"), D("1350.00")))
            self.assertEqual(Buchung.objects.get(text="Objektbetreuung Halle").mandant.kuerzel, "FFD")
            self.assertEqual(Buchung.objects.get(text="IHK Beitrag").kategorie.code, "BA_BEITRAEGE")
            self.assertTrue(all(b.pruefen for b in Buchung.objects.all()))
            self.assertEqual(importiere(pfad).uebersprungen, 5)

    def test_trockenlauf_speichert_nichts(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "euer.xlsx"
            self._mappe(pfad)
            self.assertEqual(importiere(pfad, trocken=True).angelegt, 5)
            self.assertEqual(Buchung.objects.count(), 0)

    def test_kategorie_vorschlag_aus_text(self):
        self.assertEqual(kategorie_code("Waren, Rohstoffe, Hilfsstoffe", "NordVPN", "ausgabe"), "BA_SOFTWARE")
        self.assertEqual(kategorie_code("Waren, Rohstoffe, Hilfsstoffe", "Bohrkrone", "ausgabe"), "BA_WAREN")
