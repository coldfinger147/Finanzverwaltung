# Finanz-Cockpit

Eigene Finanz- und Buchhaltungssoftware für Felix: ein Hauptbuch für die freiberufliche
Tätigkeit (FFS), das Gewerbe (FFD), die Wohnung, Privat und getrennt davon EFU.

Dieser Stand ist **Phase 2 aus dem Plan: der Buchungskern**.

- Mandanten, Kategorien mit Ziel-Feld in der Anlage EÜR, Buchungen, Belege
- Belegnummern je Bereich und Jahr (`FFS-2026-0001`)
- GoBD-Grundlagen: Festschreiben, Storno statt Ändern, unveränderbares Änderungsprotokoll,
  Belege mit SHA-256 und ohne nachträglichen Austausch
- Import aus der bisherigen Excel-EÜR (Blätter `Einn` und `Ausg`), mit Vorschlag für Bereich
  und Kategorie; alles Importierte ist als „Prüfen“ markiert
- Auswertungen: USt-Voranmeldung je Quartal (FFS + FFD zusammen), EÜR getrennt je Betrieb,
  Übersicht „Was trage ich in WISO ein?“

Annahmen: Ist-Versteuerung (Zahlungsdatum zählt), vierteljährliche USt-Voranmeldung.

## Lokal starten (ohne Server)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py importiere_tunger_excel /pfad/zur/EUER.xlsx --trocken   # erst ansehen
.venv/bin/python manage.py importiere_tunger_excel /pfad/zur/EUER.xlsx              # dann übernehmen
.venv/bin/python manage.py runserver
```

Dann <http://localhost:8000> öffnen. Daten liegen in `daten/` (SQLite und Belege) und werden
nie eingecheckt.

## Mit Docker (später auf dem Mini-PC)

```bash
cp .env.example .env      # Werte anpassen, vor allem Secret Key und Passwort
docker compose up -d --build
docker compose exec cockpit python manage.py createsuperuser
```

Die App lauscht nur auf `127.0.0.1:8000`. Zugriff vom Handy kommt über Tailscale
(`tailscale serve`), nicht über offene Ports.

## Bedienung

- **Buchungen bestätigen:** Admin > Buchungen > Filter „Prüfen: Ja“, Bereich und Kategorie
  korrigieren, dann Aktion „Vorschlag bestätigen“.
- **Zeilennummern Anlage EÜR:** Admin > Formularzeilen. Je Steuerjahr gegen das amtliche
  Formular eintragen und „Zeile geprüft“ setzen. Sie sind absichtlich leer vorbelegt.
- **Festschreiben** nach Abgabe einer USt-VA:
  `python manage.py shell -c "import datetime; from buchhaltung.models import festschreiben; festschreiben(datetime.date(2026, 9, 30))"`
- **USt-Zahlungen ans Finanzamt** als Ausgabe mit Kategorie „An das Finanzamt gezahlte
  Umsatzsteuer“ und 0 % buchen, auf den Betrieb, dem sie zuzuordnen sind.

## Tests

```bash
.venv/bin/python manage.py test buchhaltung
```

## Nächste Schritte

1. Rechnungsgenerator aus den Word-Vorlagen (FFS, FFD) mit Nummernkreis
2. Wohnung: Kaufbelege, AfA, Mieteingänge, Anlage V
3. Reisekosten mit Verpflegungspauschalen
4. Paperless-ngx, Mail-Abruf, Google Drive und Kalender, Bankabruf per FinTS
