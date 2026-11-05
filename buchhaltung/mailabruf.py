"""Rechnungsabruf aus Postfächern per IMAP (Gmail, GMX und andere).

Läuft täglich auf dem Server (`python manage.py rufe_belege_ab`). Speichert
PDF-, XML- (E-Rechnung) und Bildanhänge als Beleg, erkennt Duplikate über den
Hash und schlägt anhand der Zuordnungsregeln einen Bereich vor. Gebucht wird
erst nach Bestätigung.
"""

import email
import imaplib
import os
import re
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import Beleg, MailKonto, ZuordnungsRegel

BELEG_ENDUNGEN = (".pdf", ".xml", ".jpg", ".jpeg", ".png")
RECHNUNG_STICHWORTE = re.compile(r"rechnung|invoice|beleg|quittung|receipt|gutschrift|e-rechnung|zugferd|xrechnung", re.I)
MARKTPLAETZE = [
    (re.compile(r"amazon\.", re.I), Beleg.Quelle.AMAZON),
    (re.compile(r"ebay\.", re.I), Beleg.Quelle.EBAY),
]


def _text(wert):
    if not wert:
        return ""
    return str(make_header(decode_header(wert)))


@dataclass
class Abrufergebnis:
    konto: str
    mails_geprueft: int = 0
    belege_neu: int = 0
    duplikate: int = 0
    fehler: list = field(default_factory=list)


def bereich_vorschlag(absender, betreff):
    for regel in ZuordnungsRegel.objects.select_related("mandant"):
        if regel.passt(absender, betreff):
            return regel
    return None


def anhaenge(nachricht):
    for teil in nachricht.walk():
        name = _text(teil.get_filename())
        if not name or not name.lower().endswith(BELEG_ENDUNGEN):
            continue
        inhalt = teil.get_payload(decode=True)
        if inhalt:
            yield name, inhalt


def verarbeite_nachricht(roh, konto, ergebnis):
    nachricht = email.message_from_bytes(roh)
    absender = parseaddr(_text(nachricht.get("From")))[1] or _text(nachricht.get("From"))
    betreff = _text(nachricht.get("Subject"))
    try:
        empfangen = parsedate_to_datetime(nachricht.get("Date"))
    except (TypeError, ValueError):
        empfangen = None
    teile = list(anhaenge(nachricht))
    if konto.nur_rechnungen and not (
        RECHNUNG_STICHWORTE.search(betreff) or any(RECHNUNG_STICHWORTE.search(n) for n, _ in teile)
    ):
        return
    regel = bereich_vorschlag(absender, betreff)
    quelle = next((q for muster, q in MARKTPLAETZE if muster.search(absender)), Beleg.Quelle.MAIL)
    if regel and regel.quelle:
        quelle = regel.quelle
    for name, inhalt in teile:
        beleg = Beleg(
            datei=ContentFile(inhalt, name=name),
            quelle=quelle,
            absender=absender[:255],
            betreff=betreff[:255],
            empfangen_am=empfangen,
            herkunft_id=_text(nachricht.get("Message-ID"))[:255],
            vorschlag_mandant=regel.mandant if regel else None,
            notiz=f"Aus Postfach {konto.name}",
        )
        try:
            beleg.save()
            ergebnis.belege_neu += 1
        except ValidationError:
            ergebnis.duplikate += 1


def rufe_konto_ab(konto, verbindung=None):
    """`verbindung` erlaubt Tests ohne echten Server; sonst wird per IMAP-SSL verbunden."""
    ergebnis = Abrufergebnis(konto=konto.name)
    if verbindung is None:
        passwort = os.environ.get(konto.passwort_variable)
        if not passwort:
            ergebnis.fehler.append(f"Umgebungsvariable {konto.passwort_variable} ist nicht gesetzt.")
            return ergebnis
        verbindung = imaplib.IMAP4_SSL(konto.host, konto.port)
        verbindung.login(konto.benutzer, passwort)
    try:
        verbindung.select(konto.ordner, readonly=True)
        status, daten = verbindung.uid("search", None, f"UID {konto.letzte_uid + 1}:*")
        uids = [int(u) for u in (daten[0] or b"").split() if int(u) > konto.letzte_uid] if status == "OK" else []
        for uid in sorted(uids):
            status, teile = verbindung.uid("fetch", str(uid), "(BODY.PEEK[])")
            if status != "OK" or not teile or not isinstance(teile[0], tuple):
                ergebnis.fehler.append(f"Mail {uid} konnte nicht gelesen werden.")
                continue
            ergebnis.mails_geprueft += 1
            verarbeite_nachricht(teile[0][1], konto, ergebnis)
            konto.letzte_uid = uid
        konto.zuletzt_abgerufen = timezone.now()
        konto.save(update_fields=["letzte_uid", "zuletzt_abgerufen"])
    finally:
        try:
            verbindung.logout()
        except Exception:  # noqa: BLE001 – Abmelden darf den Abruf nicht scheitern lassen
            pass
    return ergebnis


def rufe_alle_ab():
    return [rufe_konto_ab(k) for k in MailKonto.objects.filter(aktiv=True)]
