from django.core.management.base import BaseCommand

from buchhaltung.importer import importiere


class Command(BaseCommand):
    help = "Importiert Einnahmen und Ausgaben aus der Excel-EÜR-Vorlage (Blätter Einn/Ausg)."

    def add_arguments(self, parser):
        parser.add_argument("datei")
        parser.add_argument("--jahr", type=int, help="Nur Buchungen dieses Jahres übernehmen.")
        parser.add_argument("--trocken", action="store_true", help="Nur anzeigen, nichts speichern.")

    def handle(self, datei, jahr=None, trocken=False, **optionen):
        ergebnis = importiere(datei, jahr=jahr, trocken=trocken)
        modus = "Probelauf, nichts gespeichert" if trocken else "gespeichert"
        self.stdout.write(f"{ergebnis.angelegt} Buchungen angelegt ({modus}), {ergebnis.uebersprungen} schon vorhanden.")
        for kuerzel, anzahl in sorted(ergebnis.je_bereich.items()):
            self.stdout.write(f"  {kuerzel}: {anzahl}")
        for hinweis in ergebnis.hinweise:
            self.stdout.write(self.style.WARNING(hinweis))
        self.stdout.write("Alle importierten Buchungen sind als „Prüfen“ markiert.")
