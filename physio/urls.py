# central/urls.py
from django.urls import path
from . import views

app_name = "physio"

urlpatterns = [

    path("", views.home, name='home'),
    path("map-data/", views.map_data, name="map_data"),

# workflow endpoints
    path("api/timeslots/", views.api_timeslots, name="api_timeslots"),
    path("api/available-consultants/", views.api_available_consultants, name="api_available_consultants"),
    path("api/book/", views.request_booking, name="request_booking"),

    path("customer/schedule/", views.customer_schedule, name="customer_schedule"),
    path("appointment/<int:appointment_id>/cancel/", views.cancel_appointment, name="cancel_appointment"),

    path("consultant/dashboard/", views.consultant_dashboard, name="consultant_dashboard"),
    path("consultant/appointments/", views.consultant_appointments, name="consultant_appointments"),
    path("consultant/appointments/<int:pk>/accept/", views.consultant_accept, name="consultant_accept"),
    path("consultant/appointments/<int:pk>/decline/", views.consultant_decline, name="consultant_decline"),

    path("owner/dashboard/", views.owner_dashboard, name="owner_dashboard"),

    path("consultant/token/accept/<uuid:token>/", views.consultant_token_accept, name="consultant_token_accept"),
    path("consultant/token/decline/<uuid:token>/", views.consultant_token_decline, name="consultant_token_decline"),
]

