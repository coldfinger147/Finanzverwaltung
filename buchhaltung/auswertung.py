"""Auswertungen: USt-Voranmeldung, EÜR je Betrieb, WISO-Übersicht.

Annahme: Ist-Versteuerung (§ 20 UStG). Maßgeblich ist das Zahlungsdatum.
"""

import datetime
from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

from django.db.models import Sum

from .models import Buchung, FormularZeile, Kategorie, Mandant, runde

NULL = Decimal("0.00")


def quartal_zeitraum(jahr, quartal):
    if quartal not in (1, 2, 3, 4):
        raise ValueError("Quartal muss 1 bis 4 sein.")
    von = datetime.date(jahr, 3 * quartal - 2, 1)
    bis_monat = 3 * quartal
    bis = datetime.date(jahr, 12, 31) if bis_monat == 12 else datetime.date(jahr, bis_monat + 1, 1) - datetime.timedelta(days=1)
    return von, bis


def _summe(qs, feld):
    return runde(qs.aggregate(s=Sum(feld))["s"] or NULL)


def ganze_euro(betrag):
    """Bemessungsgrundlagen werden in der USt-VA auf volle Euro abgerundet."""
    return Decimal(betrag).quantize(Decimal("1"), rounding=ROUND_DOWN)


@dataclass
class UstVoranmeldung:
    von: datetime.date
    bis: datetime.date
    kz81: Decimal  # Bemessungsgrundlage 19 %, volle Euro
    kz81_steuer: Decimal
    kz86: Decimal  # Bemessungsgrundlage 7 %, volle Euro
    kz86_steuer: Decimal
    kz66: Decimal  # Vorsteuer
    kz83: Decimal  # Vorauszahlung (+) oder Überschuss (-)
    steuerfrei: Decimal  # steuerfreie/nicht steuerbare Umsätze, nur zur Kontrolle
    anzahl_buchungen: int
    offene_pruefungen: int

    @property
    def ist_erstattung(self):
        return self.kz83 < 0


def ust_voranmeldung(von, bis):
    basis = Buchung.objects.filter(
        mandant__ust_unternehmen=True, kategorie__in_ust_va=True
    ).im_zeitraum(von, bis)
    einnahmen = basis.filter(kategorie__typ=Kategorie.Typ.EINNAHME)
    ausgaben = basis.filter(kategorie__typ=Kategorie.Typ.AUSGABE)

    kz81 = ganze_euro(_summe(einnahmen.filter(ust_satz=19), "netto"))
    kz86 = ganze_euro(_summe(einnahmen.filter(ust_satz=7), "netto"))
    kz81_steuer = runde(kz81 * Decimal("0.19"))
    kz86_steuer = runde(kz86 * Decimal("0.07"))
    kz66 = _summe(ausgaben, "ust")
    return UstVoranmeldung(
        von=von,
        bis=bis,
        kz81=kz81,
        kz81_steuer=kz81_steuer,
        kz86=kz86,
        kz86_steuer=kz86_steuer,
        kz66=kz66,
        kz83=kz81_steuer + kz86_steuer - kz66,
        steuerfrei=_summe(einnahmen.filter(ust_satz=0), "netto"),
        anzahl_buchungen=basis.count(),
        offene_pruefungen=basis.filter(pruefen=True).count(),
    )


@dataclass
class EuerPosten:
    code: str
    bezeichnung: str
    betrag: Decimal
    zeile: str = ""
    geprueft: bool = False


@dataclass
class Euer:
    mandant: Mandant
    jahr: int
    einnahmen: list = field(default_factory=list)
    ausgaben: list = field(default_factory=list)
    summe_einnahmen: Decimal = NULL
    summe_ausgaben: Decimal = NULL
    gewinn: Decimal = NULL
    hinweise: list = field(default_factory=list)


def _zeilen(jahr):
    return {z.code: z for z in FormularZeile.objects.filter(jahr=jahr, formular="Anlage EÜR")}


def _posten(code, name, betrag, zeilen):
    z = zeilen.get(code)
    return EuerPosten(
        code=code,
        bezeichnung=z.bezeichnung if z else name,
        betrag=betrag,
        zeile=z.zeile if z else "",
        geprueft=z.geprueft if z else False,
    )


def euer(mandant, jahr):
    von, bis = datetime.date(jahr, 1, 1), datetime.date(jahr, 12, 31)
    buchungen = Buchung.objects.filter(mandant=mandant).im_zeitraum(von, bis)
    zeilen = _zeilen(jahr)
    ergebnis = Euer(mandant=mandant, jahr=jahr)

    for kat in Kategorie.objects.exclude(typ=Kategorie.Typ.NEUTRAL):
        qs = buchungen.filter(kategorie=kat)
        if not qs.exists():
            continue
        # USt-Zahlungen/-Erstattungen sind schon Bruttobeträge ohne eigene Steuer.
        netto = _summe(qs, "netto")
        if kat.typ == Kategorie.Typ.EINNAHME:
            ergebnis.einnahmen.append(_posten(kat.code, kat.name, netto, zeilen))
        else:
            abziehbar = runde(netto * kat.abzugsfaehig_prozent / 100)
            ergebnis.ausgaben.append(_posten(kat.code, kat.name, abziehbar, zeilen))
            if kat.abzugsfaehig_prozent < 100:
                ergebnis.hinweise.append(
                    f"{kat.name}: {netto - abziehbar} € nicht abziehbar, gesondert in der Anlage EÜR angeben."
                )

    ust_vereinnahmt = _summe(buchungen.filter(kategorie__typ=Kategorie.Typ.EINNAHME, kategorie__in_ust_va=True), "ust")
    vorsteuer = _summe(buchungen.filter(kategorie__typ=Kategorie.Typ.AUSGABE, kategorie__in_ust_va=True), "ust")
    if ust_vereinnahmt:
        ergebnis.einnahmen.append(_posten("BE_UST_VEREINNAHMT", "Vereinnahmte Umsatzsteuer", ust_vereinnahmt, zeilen))
    if vorsteuer:
        ergebnis.ausgaben.append(_posten("BA_VORSTEUER", "Gezahlte Vorsteuerbeträge", vorsteuer, zeilen))

    ergebnis.summe_einnahmen = sum((p.betrag for p in ergebnis.einnahmen), NULL)
    ergebnis.summe_ausgaben = sum((p.betrag for p in ergebnis.ausgaben), NULL)
    ergebnis.gewinn = ergebnis.summe_einnahmen - ergebnis.summe_ausgaben

    offen = buchungen.filter(pruefen=True).count()
    if offen:
        ergebnis.hinweise.append(f"{offen} Buchungen sind noch als „Prüfen“ markiert.")
    ohne_beleg = buchungen.filter(beleg__isnull=True).exclude(kategorie__code__in=["BA_VERPFLEGUNG"]).count()
    if ohne_beleg:
        ergebnis.hinweise.append(f"{ohne_beleg} Buchungen haben noch keinen Beleg.")
    if any(not p.zeile for p in ergebnis.einnahmen + ergebnis.ausgaben):
        ergebnis.hinweise.append(
            f"Für {jahr} sind noch nicht alle Zeilennummern der Anlage EÜR gepflegt (Admin > Formularzeilen)."
        )
    return ergebnis


ANLAGE_JE_ART = {
    Mandant.Art.FREIBERUF: "Anlage S + Anlage EÜR",
    Mandant.Art.GEWERBE: "Anlage G + Anlage EÜR + Gewerbesteuererklärung",
}


def wiso_uebersicht(jahr):
    """Alles, was für das Steuerjahr in WISO übertragen werden muss."""
    abschnitte = OrderedDict()
    for mandant in Mandant.objects.filter(art__in=ANLAGE_JE_ART.keys()):
        abschnitte[mandant] = {"formulare": ANLAGE_JE_ART[mandant.art], "euer": euer(mandant, jahr)}
    quartale = [ust_voranmeldung(*quartal_zeitraum(jahr, q)) for q in (1, 2, 3, 4)]
    ust_jahr = ust_voranmeldung(datetime.date(jahr, 1, 1), datetime.date(jahr, 12, 31))
    return {"jahr": jahr, "betriebe": abschnitte, "quartale": quartale, "ust_jahr": ust_jahr}
