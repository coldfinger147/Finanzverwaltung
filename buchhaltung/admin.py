from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import format_html

from .models import Beleg, Buchung, FormularZeile, Kategorie, MailKonto, Mandant, Protokoll, ZuordnungsRegel

admin.site.disable_action("delete_selected")


@admin.register(Mandant)
class MandantAdmin(admin.ModelAdmin):
    list_display = ["kuerzel", "name", "art", "ust_unternehmen"]


@admin.register(Kategorie)
class KategorieAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "typ", "in_ust_va", "abzugsfaehig_prozent"]
    list_filter = ["typ"]
    search_fields = ["name", "code"]


@admin.register(FormularZeile)
class FormularZeileAdmin(admin.ModelAdmin):
    list_display = ["jahr", "formular", "zeile", "bezeichnung", "code", "geprueft"]
    list_editable = ["zeile", "geprueft"]
    list_filter = ["jahr", "formular", "geprueft"]


@admin.register(Beleg)
class BelegAdmin(admin.ModelAdmin):
    list_display = ["originalname", "status", "quelle", "vorschlag_mandant", "absender", "empfangen_am", "datei_link"]
    list_filter = ["status", "quelle", "vorschlag_mandant"]
    list_editable = ["status", "vorschlag_mandant"]
    search_fields = ["originalname", "notiz", "absender", "betreff"]
    readonly_fields = ["originalname", "sha256", "erfasst_am", "absender", "betreff", "empfangen_am", "herkunft_id"]

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (["datei"] if obj else [])

    @admin.display(description="Datei")
    def datei_link(self, obj):
        return format_html('<a href="{}">öffnen</a>', reverse("buchhaltung:beleg_datei", args=[obj.pk]))

    def save_model(self, request, obj, form, change):
        try:
            super().save_model(request, obj, form, change)
        except ValidationError as fehler:
            self.message_user(request, "; ".join(fehler.messages), messages.ERROR)


@admin.register(Buchung)
class BuchungAdmin(admin.ModelAdmin):
    list_display = ["belegnummer", "datum", "mandant", "text", "kategorie", "brutto", "ust_satz", "pruefen", "hat_beleg", "fest"]
    list_filter = ["mandant", "kategorie__typ", "pruefen", "kategorie", ("beleg", admin.EmptyFieldListFilter)]
    search_fields = ["belegnummer", "alte_belegnummer", "text", "partner", "rechnungsnummer"]
    date_hierarchy = "datum"
    autocomplete_fields = ["kategorie"]
    raw_id_fields = ["beleg"]
    readonly_fields = ["belegnummer", "netto", "ust", "festgeschrieben_am", "storno_von", "erfasst_am"]
    actions = ["bestaetigen", "stornieren"]
    list_per_page = 50

    @admin.display(boolean=True, description="Beleg")
    def hat_beleg(self, obj):
        return obj.beleg_id is not None

    @admin.display(boolean=True, description="Fest")
    def fest(self, obj):
        return obj.festgeschrieben

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.festgeschrieben:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.festgeschrieben:
            return False
        return super().has_delete_permission(request, obj)

    @admin.action(description="Vorschlag bestätigen (Prüfen entfernen)")
    def bestaetigen(self, request, queryset):
        anzahl = 0
        for buchung in queryset.filter(pruefen=True, festgeschrieben_am__isnull=True):
            buchung.pruefen = False
            buchung.save()
            anzahl += 1
        self.message_user(request, f"{anzahl} Buchungen bestätigt.")

    @admin.action(description="Stornieren (Gegenbuchung anlegen)")
    def stornieren(self, request, queryset):
        for buchung in queryset:
            try:
                storno = buchung.stornieren()
                self.message_user(request, f"{buchung.belegnummer} storniert durch {storno.belegnummer}.")
            except ValidationError as fehler:
                self.message_user(request, f"{buchung.belegnummer}: {'; '.join(fehler.messages)}", messages.ERROR)


@admin.register(Protokoll)
class ProtokollAdmin(admin.ModelAdmin):
    list_display = ["zeitpunkt", "modell", "objekt_id", "aktion"]
    list_filter = ["modell", "aktion"]
    readonly_fields = ["zeitpunkt", "modell", "objekt_id", "aktion", "vorher", "nachher"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MailKonto)
class MailKontoAdmin(admin.ModelAdmin):
    list_display = ["name", "benutzer", "host", "aktiv", "zuletzt_abgerufen"]
    readonly_fields = ["letzte_uid", "zuletzt_abgerufen"]


@admin.register(ZuordnungsRegel)
class ZuordnungsRegelAdmin(admin.ModelAdmin):
    list_display = ["muster", "feld", "mandant", "quelle", "reihenfolge"]
    list_editable = ["reihenfolge"]
