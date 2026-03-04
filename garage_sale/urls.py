from django.urls import path
from . import views


app_name = "garage_sale"

urlpatterns = [
    # Public
    path("", views.home, name="home"),
    path("map-data/", views.map_data, name="map_data"),
    path("events/", views.events_list, name="events_list"),
    path("event/<int:event_id>/", views.event_detail, name="event_detail"),
    path("events/create/", views.owner_event_create, name="event_create"),
    path("item/<int:item_id>/", views.item_detail, name="item_detail"),

    # Cart + checkout (simple version)
    path("cart/", views.cart_view, name="cart"),
    path("cart/add/", views.cart_add, name="cart_add"),
    path("cart/remove/", views.cart_remove, name="cart_remove"),
    path("checkout/", views.checkout, name="checkout"),
    path("reservation/<int:reservation_id>/", views.reservation_detail, name="reservation_detail"),

    # Owner
    path("owner/", views.owner_dashboard, name="owner_dashboard"),
    path("owner/event/new/", views.owner_event_create, name="owner_event_create"),
    path("owner/event/<int:event_id>/edit/", views.owner_event_edit, name="owner_event_edit"),
    path("owner/event/<int:event_id>/items/", views.owner_items, name="owner_items"),
    path("owner/event/<int:event_id>/reservations/", views.owner_event_reservations, name="owner_event_reservations"),

    path("owner/event/<int:event_id>/items/new/", views.owner_item_create, name="owner_item_create"),
    path("owner/item/<int:item_id>/edit/", views.owner_item_edit, name="owner_item_edit"),
    path("owner/item/<int:item_id>/delete/", views.owner_item_delete, name="owner_item_delete"),
]