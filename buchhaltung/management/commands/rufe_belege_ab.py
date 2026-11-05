from django.core.management.base import BaseCommand

from buchhaltung.mailabruf import rufe_alle_ab


class Command(BaseCommand):
    help = "Holt Rechnungsanhänge aus allen aktiven Mailkonten (täglich per Cron oder Timer starten)."

    def handle(self, **optionen):
        for e in rufe_alle_ab():
            self.stdout.write(
                f"{e.konto}: {e.mails_geprueft} Mails geprüft, {e.belege_neu} neue Belege, {e.duplikate} schon vorhanden."
            )
            for fehler in e.fehler:
                self.stdout.write(self.style.ERROR(f"  {fehler}"))
