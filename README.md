# Finanz-Cockpit

Eigene Finanz- und Buchhaltungssoftware für Felix: ein Hauptbuch für die freiberufliche
Tätigkeit (FFS), das Gewerbe (FFD), die Wohnung, Privat und getrennt davon EFU.

Dieser Stand ist **Phase 2 aus dem Plan: der Buchungskern**, dazu der Rechnungsabruf aus Mailpostfächern.

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

## Rechnungen aus Mails abholen

1. Im Postfach ein **App-Passwort** für IMAP erzeugen (Gmail: Google-Konto > Sicherheit > App-Passwörter;
   GMX: Einstellungen > POP3/IMAP aktivieren, App-Passwort bei aktiver 2FA).
2. Das Passwort in die `.env` schreiben, z. B. `MAIL_GMX_PASSWORT=...`.
3. Im Admin unter **Mailkonten** das Konto anlegen und als Passwort-Variable `MAIL_GMX_PASSWORT` eintragen.
4. Optional **Zuordnungsregeln** anlegen (z. B. Absender `discovery` → FFS).
5. Abrufen: `python manage.py rufe_belege_ab`. Neue Belege stehen im Admin unter Belege mit Status „Neu“.

Abgeholt werden PDF-, XML- (E-Rechnung) und Bildanhänge aus Mails, deren Betreff oder Anhang nach
Rechnung, Beleg, Quittung oder Invoice klingt. Duplikate werden über den Hash erkannt, das Postfach
wird nur gelesen (nichts gelöscht oder als gelesen markiert).

## Auf dem Raspberry Pi (neben dem Academy-System)

Voraussetzung: Raspberry Pi OS 64-bit mit Docker. Das Cockpit bekommt eigene Container, eine
eigene Datenbank und den Port 8010 (`COCKPIT_PORT`), damit es dem Academy-System nicht in die Quere kommt.

```bash
git clone https://github.com/coldfinger147/Finanzverwaltung.git ~/finanzcockpit && cd ~/finanzcockpit
cp .env.example .env      # Secret Key, DB-Passwort, Mail-Passwörter eintragen
docker compose up -d --build
docker compose exec cockpit python manage.py createsuperuser
```

Täglicher Belegabruf per Cron (`crontab -e`):

```
15 6 * * * cd ~/finanzcockpit && docker compose exec -T cockpit python manage.py rufe_belege_ab >> ~/finanzcockpit/daten/belegabruf.log 2>&1
```

Zugriff vom Handy über Tailscale: `sudo tailscale serve --bg --https=8443 http://127.0.0.1:8010`
und den Tailscale-Namen des Pi in `DJANGO_ALLOWED_HOSTS` und `DJANGO_CSRF_TRUSTED_ORIGINS` eintragen.

## Mit Docker allgemein

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
4. eBay-Rechnungen über die eBay-Schnittstelle, Amazon-Rechnungen per automatisiertem Browser
5. Beträge aus Belegen auslesen und Buchungen vorschlagen
6. Google Drive und Kalender, Bankabruf per FinTS
