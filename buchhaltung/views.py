import datetime

from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import get_object_or_404, render

from . import auswertung
from .models import Beleg, Buchung, Mandant


def _jahr(request):
    try:
        return int(request.GET.get("jahr", datetime.date.today().year))
    except ValueError:
        return datetime.date.today().year


@login_required
def uebersicht(request):
    heute = datetime.date.today()
    quartal = (heute.month - 1) // 3 + 1
    return render(
        request,
        "buchhaltung/uebersicht.html",
        {
            "ust": auswertung.ust_voranmeldung(*auswertung.quartal_zeitraum(heute.year, quartal)),
            "quartal": quartal,
            "jahr": heute.year,
            "mandanten": Mandant.objects.all(),
            "zu_pruefen": Buchung.objects.filter(pruefen=True).count(),
            "ohne_beleg": Buchung.objects.filter(beleg__isnull=True).exclude(mandant__art="privat").count(),
            "letzte": Buchung.objects.select_related("mandant", "kategorie")[:10],
        },
    )


@login_required
def ust_va(request):
    jahr = _jahr(request)
    quartale = [
        (q, auswertung.ust_voranmeldung(*auswertung.quartal_zeitraum(jahr, q))) for q in (1, 2, 3, 4)
    ]
    return render(request, "buchhaltung/ust_va.html", {"jahr": jahr, "quartale": quartale})


@login_required
def euer(request, kuerzel):
    mandant = get_object_or_404(Mandant, kuerzel=kuerzel)
    jahr = _jahr(request)
    return render(request, "buchhaltung/euer.html", {"e": auswertung.euer(mandant, jahr), "jahr": jahr})


@login_required
def wiso(request):
    return render(request, "buchhaltung/wiso.html", auswertung.wiso_uebersicht(_jahr(request)))


@login_required
def beleg_datei(request, pk):
    beleg = get_object_or_404(Beleg, pk=pk)
    return FileResponse(beleg.datei.open("rb"), filename=beleg.originalname)
