"""Hauptbuch des Finanz-Cockpits.

Grundsätze (GoBD):
- Jede Buchung gehört genau einem Mandanten (FFS, FFD, Wohnung, Privat, EFU).
- Festgeschriebene Buchungen sind unveränderbar; Korrekturen nur per Storno.
- Jede Änderung landet im Protokoll mit altem und neuem Stand.
- Belege werden mit SHA-256 abgelegt und danach nicht mehr verändert.
"""

import hashlib
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.forms.models import model_to_dict
from django.utils import timezone

CENT = Decimal("0.01")


def runde(betrag):
    return Decimal(betrag).quantize(CENT, rounding=ROUND_HALF_UP)


class Mandant(models.Model):
    class Art(models.TextChoices):
        FREIBERUF = "freiberuf", "Freiberufliche Tätigkeit (Anlage S)"
        GEWERBE = "gewerbe", "Gewerbebetrieb (Anlage G)"
        VERMIETUNG = "vermietung", "Vermietung (Anlage V)"
        PRIVAT = "privat", "Privat"
        FREMD = "fremd", "Fremde Firma (nur Angebote/Verwaltung)"

    kuerzel = models.CharField("Kürzel", max_length=8, unique=True)
    name = models.CharField(max_length=120)
    art = models.CharField(max_length=20, choices=Art.choices)
    ust_unternehmen = models.BooleanField(
        "Gehört zum USt-Unternehmen",
        default=False,
        help_text="Alle Mandanten mit Haken laufen in einer gemeinsamen USt-Voranmeldung.",
    )

    class Meta:
        verbose_name = "Mandant"
        verbose_name_plural = "Mandanten"
        ordering = ["kuerzel"]

    def __str__(self):
        return f"{self.kuerzel} – {self.name}"

    @property
    def hat_euer(self):
        return self.art in (self.Art.FREIBERUF, self.Art.GEWERBE)


class Kategorie(models.Model):
    """Eine Buchungskategorie, die auf ein Feld der Anlage EÜR zeigt."""

    class Typ(models.TextChoices):
        EINNAHME = "einnahme", "Betriebseinnahme"
        AUSGABE = "ausgabe", "Betriebsausgabe"
        NEUTRAL = "neutral", "Steuerlich neutral"

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    typ = models.CharField(max_length=10, choices=Typ.choices)
    in_ust_va = models.BooleanField(
        "Fließt in die USt-VA",
        default=True,
        help_text="Aus für Zahlungen/Erstattungen an das Finanzamt selbst.",
    )
    abzugsfaehig_prozent = models.PositiveSmallIntegerField(
        "Abziehbar in %", default=100, help_text="Z. B. 70 für Bewirtung."
    )
    reihenfolge = models.PositiveSmallIntegerField(default=100)

    class Meta:
        verbose_name = "Kategorie"
        verbose_name_plural = "Kategorien"
        ordering = ["typ", "reihenfolge", "name"]

    def __str__(self):
        return self.name


class FormularZeile(models.Model):
    """Zielzeile einer Kategorie im amtlichen Formular, je Steuerjahr gepflegt."""

    jahr = models.PositiveSmallIntegerField()
    formular = models.CharField(max_length=40, default="Anlage EÜR")
    code = models.CharField(max_length=40, help_text="Kategorie-Code oder Summenfeld, z. B. BE_UST_VEREINNAHMT")
    zeile = models.CharField(max_length=10, blank=True)
    bezeichnung = models.CharField(max_length=200)
    geprueft = models.BooleanField(
        "Zeile geprüft", default=False, help_text="Erst setzen, wenn mit dem amtlichen Formular abgeglichen."
    )

    class Meta:
        verbose_name = "Formularzeile"
        verbose_name_plural = "Formularzeilen"
        unique_together = [("jahr", "formular", "code")]
        ordering = ["jahr", "formular", "zeile"]

    def __str__(self):
        return f"{self.formular} {self.jahr} Z. {self.zeile or '?'}: {self.bezeichnung}"


def beleg_pfad(instance, filename):
    endung = Path(filename).suffix.lower()
    return f"{timezone.now():%Y/%m}/{instance.sha256}{endung}"


class Beleg(models.Model):
    class Quelle(models.TextChoices):
        UPLOAD = "upload", "Upload"
        MAIL = "mail", "E-Mail"
        AMAZON = "amazon", "Amazon"
        EBAY = "ebay", "eBay"
        SCAN = "scan", "Scan / Foto"
        IMPORT = "import", "Import"
        RECHNUNG = "rechnung", "Eigene Ausgangsrechnung"

    datei = models.FileField(upload_to=beleg_pfad)
    originalname = models.CharField(max_length=255, editable=False)
    sha256 = models.CharField(max_length=64, unique=True, editable=False)
    quelle = models.CharField(max_length=10, choices=Quelle.choices, default=Quelle.UPLOAD)
    class Status(models.TextChoices):
        NEU = "neu", "Neu, noch nicht zugeordnet"
        ZUGEORDNET = "zugeordnet", "Gebucht"
        IGNORIERT = "ignoriert", "Kein Beleg / ignoriert"

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEU)
    vorschlag_mandant = models.ForeignKey(
        Mandant, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="Vorschlag Bereich"
    )
    absender = models.CharField(max_length=255, blank=True)
    betreff = models.CharField(max_length=255, blank=True)
    empfangen_am = models.DateTimeField(null=True, blank=True)
    herkunft_id = models.CharField(
        "Herkunfts-ID", max_length=255, blank=True, help_text="Message-ID der Mail oder Bestellnummer."
    )
    notiz = models.CharField(max_length=255, blank=True)
    erfasst_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Beleg"
        verbose_name_plural = "Belege"
        ordering = ["-erfasst_am"]

    def __str__(self):
        return self.originalname

    def save(self, *args, **kwargs):
        neu = self.pk is None
        if not neu:
            alt = Beleg.objects.get(pk=self.pk)
            if alt.datei.name != self.datei.name:
                raise ValidationError("Die Datei eines Belegs kann nicht ersetzt werden. Neuen Beleg anlegen.")
        else:
            inhalt = self.datei.read()
            self.datei.seek(0)
            self.sha256 = hashlib.sha256(inhalt).hexdigest()
            self.originalname = Path(self.datei.name).name
            if Beleg.objects.filter(sha256=self.sha256).exists():
                raise ValidationError("Dieser Beleg ist schon vorhanden.")
        super().save(*args, **kwargs)
        protokolliere(self, "angelegt" if neu else "geändert")

    def delete(self, *args, **kwargs):
        if self.buchungen.exists():
            raise ValidationError("Ein Beleg mit Buchungen kann nicht gelöscht werden.")
        protokolliere(self, "gelöscht")
        return super().delete(*args, **kwargs)


class BuchungQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError("Massenlöschen ist gesperrt. Buchungen einzeln löschen oder stornieren.")

    def update(self, **kwargs):
        if self.filter(festgeschrieben_am__isnull=False).exists():
            raise ValidationError("Festgeschriebene Buchungen können nicht geändert werden.")
        return super().update(**kwargs)

    def im_zeitraum(self, von, bis):
        return self.filter(datum__gte=von, datum__lte=bis)


class Buchung(models.Model):
    UST_SAETZE = [(Decimal("0"), "0 %"), (Decimal("7"), "7 %"), (Decimal("19"), "19 %")]

    mandant = models.ForeignKey(Mandant, on_delete=models.PROTECT, related_name="buchungen")
    belegnummer = models.CharField(max_length=30, blank=True, editable=False)
    alte_belegnummer = models.CharField("Alte Belegnummer", max_length=30, blank=True)
    datum = models.DateField("Zahlungsdatum", help_text="Maßgeblich für EÜR und USt (Ist-Versteuerung).")
    rechnungsdatum = models.DateField(null=True, blank=True)
    rechnungsnummer = models.CharField(max_length=60, blank=True)
    partner = models.CharField("Geschäftspartner", max_length=160, blank=True)
    text = models.CharField("Buchungstext", max_length=255)
    kategorie = models.ForeignKey(Kategorie, on_delete=models.PROTECT, related_name="buchungen")
    brutto = models.DecimalField(max_digits=12, decimal_places=2)
    ust_satz = models.DecimalField("USt-Satz %", max_digits=4, decimal_places=1, choices=UST_SAETZE, default=Decimal("19"))
    netto = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    ust = models.DecimalField("USt-Betrag", max_digits=12, decimal_places=2, editable=False)
    beleg = models.ForeignKey(Beleg, on_delete=models.PROTECT, null=True, blank=True, related_name="buchungen")
    pruefen = models.BooleanField("Prüfen", default=False, help_text="Vorschlag aus Import oder Automatik, noch nicht bestätigt.")
    festgeschrieben_am = models.DateTimeField(null=True, blank=True, editable=False)
    storno_von = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, editable=False, related_name="storniert_durch"
    )
    erfasst_am = models.DateTimeField(auto_now_add=True)

    objects = BuchungQuerySet.as_manager()

    class Meta:
        verbose_name = "Buchung"
        verbose_name_plural = "Buchungen"
        ordering = ["-datum", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["mandant", "belegnummer"], condition=~models.Q(belegnummer=""), name="belegnummer_je_mandant"
            )
        ]

    def __str__(self):
        return f"{self.belegnummer} {self.datum:%d.%m.%Y} {self.text} {self.brutto} €"

    @property
    def festgeschrieben(self):
        return self.festgeschrieben_am is not None

    def berechne_steuer(self):
        brutto = Decimal(self.brutto)
        satz = Decimal(self.ust_satz)
        self.netto = runde(brutto * 100 / (100 + satz))
        self.ust = brutto - self.netto

    def naechste_belegnummer(self):
        praefix = f"{self.mandant.kuerzel}-{self.datum.year}-"
        letzte = (
            Buchung.objects.filter(mandant=self.mandant, belegnummer__startswith=praefix)
            .order_by("-belegnummer")
            .values_list("belegnummer", flat=True)
            .first()
        )
        nummer = int(letzte.rsplit("-", 1)[1]) + 1 if letzte else 1
        return f"{praefix}{nummer:04d}"

    def clean(self):
        if self.kategorie_id and self.kategorie.typ == Kategorie.Typ.NEUTRAL and self.ust_satz:
            raise ValidationError("Steuerlich neutrale Buchungen haben keine Umsatzsteuer.")

    def save(self, *args, **kwargs):
        festschreibvorgang = kwargs.pop("_festschreiben", False)
        alt = None
        if self.pk:
            alt = Buchung.objects.get(pk=self.pk)
            if alt.festgeschrieben and not festschreibvorgang:
                raise ValidationError("Festgeschriebene Buchungen können nicht geändert werden. Bitte stornieren.")
        self.berechne_steuer()
        with transaction.atomic():
            if not self.belegnummer:
                self.belegnummer = self.naechste_belegnummer()
            super().save(*args, **kwargs)
            protokolliere(self, "geändert" if alt else "angelegt", vorher=alt)

    def delete(self, *args, **kwargs):
        if self.festgeschrieben:
            raise ValidationError("Festgeschriebene Buchungen können nicht gelöscht werden. Bitte stornieren.")
        protokolliere(self, "gelöscht", vorher=self)
        return super().delete(*args, **kwargs)

    def stornieren(self, datum=None, grund=""):
        """Legt eine Gegenbuchung an. Die Originalbuchung bleibt unverändert stehen."""
        if hasattr(self, "storniert_durch"):
            raise ValidationError("Diese Buchung ist bereits storniert.")
        if self.storno_von_id:
            raise ValidationError("Eine Stornobuchung kann nicht storniert werden.")
        storno = Buchung(
            mandant=self.mandant,
            datum=datum or timezone.localdate(),
            rechnungsdatum=self.rechnungsdatum,
            rechnungsnummer=self.rechnungsnummer,
            partner=self.partner,
            text=f"Storno {self.belegnummer}: {grund or self.text}"[:255],
            kategorie=self.kategorie,
            brutto=-self.brutto,
            ust_satz=self.ust_satz,
            beleg=self.beleg,
            storno_von=self,
        )
        storno.save()
        return storno


def festschreiben(bis_datum, mandanten=None):
    """Schreibt alle Buchungen bis einschließlich bis_datum fest (z. B. nach Abgabe der USt-VA)."""
    qs = Buchung.objects.filter(datum__lte=bis_datum, festgeschrieben_am__isnull=True)
    if mandanten is not None:
        qs = qs.filter(mandant__in=mandanten)
    jetzt = timezone.now()
    anzahl = 0
    for buchung in qs:
        buchung.festgeschrieben_am = jetzt
        buchung.save(_festschreiben=True)
        anzahl += 1
    return anzahl


class Protokoll(models.Model):
    """Änderungsprotokoll. Wird nur angehängt, nie geändert."""

    zeitpunkt = models.DateTimeField(auto_now_add=True)
    modell = models.CharField(max_length=40)
    objekt_id = models.CharField(max_length=40)
    aktion = models.CharField(max_length=20)
    vorher = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    nachher = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)

    class Meta:
        verbose_name = "Protokolleintrag"
        verbose_name_plural = "Protokoll"
        ordering = ["-zeitpunkt", "-id"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Protokolleinträge sind unveränderbar.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Protokolleinträge können nicht gelöscht werden.")


def _als_dict(obj):
    if obj is None:
        return None
    daten = model_to_dict(obj)
    for feld in ("festgeschrieben_am", "belegnummer", "netto", "ust", "sha256", "originalname"):
        if hasattr(obj, feld):
            daten[feld] = getattr(obj, feld)
    if "datei" in daten:
        daten["datei"] = obj.datei.name
    return daten


def protokolliere(obj, aktion, vorher=None):
    Protokoll.objects.create(
        modell=obj._meta.model_name,
        objekt_id=str(obj.pk),
        aktion=aktion,
        vorher=_als_dict(vorher),
        nachher=None if aktion == "gelöscht" else _als_dict(obj),
    )



class MailKonto(models.Model):
    """Postfach, aus dem Rechnungsanhänge abgeholt werden. Das Passwort steht nie in der Datenbank."""

    name = models.CharField(max_length=60, unique=True)
    host = models.CharField(max_length=120, help_text="z. B. imap.gmail.com oder imap.gmx.net")
    port = models.PositiveIntegerField(default=993)
    benutzer = models.CharField(max_length=160)
    passwort_variable = models.CharField(
        max_length=60,
        help_text="Name der Umgebungsvariable mit dem App-Passwort, z. B. MAIL_GMX_PASSWORT (steht in der .env).",
    )
    ordner = models.CharField(max_length=120, default="INBOX")
    nur_rechnungen = models.BooleanField(
        default=True, help_text="Nur Mails, deren Betreff oder Anhang nach Rechnung, Beleg oder Quittung klingt."
    )
    aktiv = models.BooleanField(default=True)
    letzte_uid = models.PositiveBigIntegerField(default=0, editable=False)
    zuletzt_abgerufen = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Mailkonto"
        verbose_name_plural = "Mailkonten"

    def __str__(self):
        return f"{self.name} ({self.benutzer})"


class ZuordnungsRegel(models.Model):
    """Ordnet eingehende Belege anhand von Absender oder Betreff einem Bereich zu."""

    muster = models.CharField(max_length=200, help_text="Regulärer Ausdruck, ohne Groß-/Kleinschreibung.")
    feld = models.CharField(
        max_length=10, choices=[("absender", "Absender"), ("betreff", "Betreff"), ("beides", "Absender oder Betreff")],
        default="beides",
    )
    mandant = models.ForeignKey(Mandant, on_delete=models.CASCADE, verbose_name="Bereich")
    quelle = models.CharField(max_length=10, choices=Beleg.Quelle.choices, blank=True, help_text="Optional: Quelle umsetzen, z. B. Amazon.")
    reihenfolge = models.PositiveSmallIntegerField(default=100)

    class Meta:
        verbose_name = "Zuordnungsregel"
        verbose_name_plural = "Zuordnungsregeln"
        ordering = ["reihenfolge", "id"]

    def __str__(self):
        return f"{self.muster} → {self.mandant.kuerzel}"

    def passt(self, absender, betreff):
        texte = {"absender": [absender], "betreff": [betreff], "beides": [absender, betreff]}[self.feld]
        return any(re.search(self.muster, t or "", re.I) for t in texte)
