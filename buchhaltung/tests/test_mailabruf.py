import tempfile
from email.message import EmailMessage

from django.test import TestCase, override_settings

from buchhaltung.mailabruf import rufe_konto_ab
from buchhaltung.models import Beleg, MailKonto, Mandant, ZuordnungsRegel


def mail(absender, betreff, anhang=None, inhalt=b"%PDF-1.4 rechnung"):
    m = EmailMessage()
    m["From"] = absender
    m["Subject"] = betreff
    m["Date"] = "Wed, 04 Nov 2026 10:00:00 +0100"
    m["Message-ID"] = f"<{betreff}@test>"
    m.set_content("Hallo")
    if anhang:
        m.add_attachment(inhalt, maintype="application", subtype="pdf", filename=anhang)
    return m.as_bytes()


class FalschesImap:
    def __init__(self, mails):
        self.mails = mails  # uid -> bytes
        self.abgemeldet = False

    def select(self, ordner, readonly=False):
        return "OK", [b"1"]

    def uid(self, befehl, *args):
        if befehl == "search":
            return "OK", [b" ".join(str(u).encode() for u in self.mails)]
        uid = int(args[0])
        return "OK", [(b"1 (BODY[] {1})", self.mails[uid])]

    def logout(self):
        self.abgemeldet = True


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class MailabrufTest(TestCase):
    def setUp(self):
        self.konto = MailKonto.objects.create(name="GMX", host="imap.gmx.net", benutzer="f@gmx.de", passwort_variable="X")
        ZuordnungsRegel.objects.create(muster=r"discovery", mandant=Mandant.objects.get(kuerzel="FFS"))

    def test_rechnungen_werden_belege(self):
        imap = FalschesImap({
            5: mail("Amazon.de <auto-confirm@amazon.de>", "Ihre Rechnung zur Bestellung 302-1", "Rechnung.pdf"),
            6: mail("Newsletter <news@shop.de>", "Angebote der Woche", "prospekt.pdf", b"%PDF prospekt"),
            7: mail("Discovery <billing@discovery.com>", "Purchase Order 3900031660", "invoice_3900031660.pdf", b"%PDF po"),
            8: mail("eBay <ebay@ebay.de>", "Bestellbestätigung: USB-Mikrofon", None),
            9: mail("Shop <info@shop.de>", "Ihre Bestellung", None),
        })
        e = rufe_konto_ab(self.konto, verbindung=imap)
        self.assertEqual((e.mails_geprueft, e.belege_neu, e.duplikate), (5, 3, 0))
        ebay = Beleg.objects.get(quelle=Beleg.Quelle.EBAY)
        self.assertTrue(ebay.originalname.endswith(".eml"))
        amazon = Beleg.objects.get(originalname="Rechnung.pdf")
        self.assertEqual(amazon.quelle, Beleg.Quelle.AMAZON)
        self.assertIsNone(amazon.vorschlag_mandant)
        po = Beleg.objects.get(originalname="invoice_3900031660.pdf")
        self.assertEqual(po.vorschlag_mandant.kuerzel, "FFS")
        self.assertEqual(po.status, Beleg.Status.NEU)
        self.konto.refresh_from_db()
        self.assertEqual(self.konto.letzte_uid, 9)
        self.assertTrue(imap.abgemeldet)

    def test_zweiter_abruf_holt_nur_neue_und_erkennt_duplikate(self):
        rufe_konto_ab(self.konto, verbindung=FalschesImap({1: mail("a@b.de", "Rechnung 1", "r1.pdf")}))
        e = rufe_konto_ab(self.konto, verbindung=FalschesImap({
            1: mail("a@b.de", "Rechnung 1", "r1.pdf"),
            2: mail("a@b.de", "Rechnung 1 erneut", "r1-kopie.pdf"),
        }))
        self.assertEqual((e.mails_geprueft, e.belege_neu, e.duplikate), (1, 0, 1))

    def test_ohne_passwort_kein_abruf(self):
        e = rufe_konto_ab(self.konto)
        self.assertIn("nicht gesetzt", e.fehler[0])
