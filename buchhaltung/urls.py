from django.urls import path

from . import views

app_name = "buchhaltung"

urlpatterns = [
    path("", views.uebersicht, name="uebersicht"),
    path("ust-va/", views.ust_va, name="ust_va"),
    path("euer/<str:kuerzel>/", views.euer, name="euer"),
    path("wiso/", views.wiso, name="wiso"),
    path("beleg/<int:pk>/", views.beleg_datei, name="beleg_datei"),
]
