from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Finanz-Cockpit"
admin.site.site_title = "Finanz-Cockpit"
admin.site.index_title = "Verwaltung"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("buchhaltung.urls")),
]
