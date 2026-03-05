"""
garage_sale/views.py

Cleaned + de-duplicated.
- Removes is_active usage (SaleItem doesn't have it)
- Fixes reservation_detail (now returns a response)
- Removes duplicate owner_item_create
- Implements owner_event_edit properly
- Simplifies map_data filtering (end_date is not nullable)
- Keeps your existing URL names working
"""

from __future__ import annotations
from django.http import HttpResponseForbidden
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import (
    GarageSaleEventForm,
    LocationCreateForm,
    SaleItemForm,
)
from .models import (
    GarageSaleEvent,
    Reservation,
    ReservationItem,
    SaleItem,
)

# -------------------------
# Helpers: session cart
# -------------------------

CART_KEY = "gs_cart"  # { "<item_id>": qty_int }


def _get_cart(request) -> dict:
    cart = request.session.get(CART_KEY)
    if not isinstance(cart, dict):
        cart = {}
        request.session[CART_KEY] = cart
    return cart


def _save_cart(request, cart: dict) -> None:
    request.session[CART_KEY] = cart
    request.session.modified = True


def _cart_count(cart: dict) -> int:
    # cart values may be stored as ints or strings; normalize
    return sum(int(q) for q in cart.values()) if cart else 0


# -------------------------
# Public: Map + browsing
# -------------------------

def home(request):
    default_center = getattr(settings, "DEFAULT_MAP_CENTER", [-37.8136, 144.9631])
    default_zoom = getattr(settings, "DEFAULT_MAP_ZOOM", 10)

    return render(request, "garage_sale/home_map.html", {
        "default_map_center": default_center,
        "default_map_zoom": default_zoom,
    })


def map_data(request):
    """
    Returns pins for events within a date range.
    Note: GarageSaleEvent.end_date is not nullable in your model, so we only do overlap logic.
    """
    today = timezone.localdate()
    range_key = (request.GET.get("range") or "today").lower()

    if range_key == "tomorrow":
        start = today + timedelta(days=1)
        end = start
    elif range_key == "week":
        start = today
        end = today + timedelta(days=7)
    elif range_key == "month":
        start = today
        end = today + timedelta(days=30)
    else:
        start = today
        end = today

    qs = (
        GarageSaleEvent.objects
        .select_related("owner", "location")
        .filter(start_date__lte=end, end_date__gte=start)
        .order_by("start_date", "id")
    )

    pins = []
    for ev in qs:
        loc = ev.location
        if not loc or loc.latitude is None or loc.longitude is None:
            continue

        pins.append({
            "id": ev.id,
            "title": ev.title,
            "lat": float(loc.latitude),
            "lng": float(loc.longitude),
            "start_date": ev.start_date.isoformat() if ev.start_date else None,
            "end_date": ev.end_date.isoformat() if ev.end_date else None,
            "detail_url": reverse("garage_sale:event_detail", args=[ev.id]),
            "manage_url": reverse("garage_sale:event_manage", args=[ev.id]),

            "owner_id": ev.owner_id,
        })



    return JsonResponse({
        "pins": pins,
        "events": pins,  # backward compat
        "range": range_key,
        "start": start.isoformat(),
        "end": end.isoformat(),
    })


def events_list(request):
    """
    List all events (you can later restrict to active/upcoming if desired).
    """
    today = timezone.localdate()
    events = (
        GarageSaleEvent.objects
        .select_related("location")
        .order_by("-start_date", "-id")
    )
    return render(request, "garage_sale/events_list.html", {
        "events": events,
        "today": today,
    })


def event_detail(request, event_id: int):
    event = get_object_or_404(GarageSaleEvent, id=event_id)

    items = event.items.filter(is_listed=True, quantity_available__gt=0)

    cart = _get_cart(request)
    cart_count = sum(int(q) for q in cart.values()) if cart else 0

    user_role = getattr(request.user, "role", "")
    can_shop = request.user.is_authenticated and user_role == "CUSTOMER"
    is_owner = request.user.is_authenticated and (event.owner_id == request.user.id)

    return render(request, "garage_sale/event_detail.html", {
        "event": event,
        "items": items,
        "cart_count": cart_count,
        "can_shop": can_shop,
        "is_owner": is_owner,
    })

@login_required
def event_manage(request, pk):
    event = get_object_or_404(GarageSaleEvent, pk=pk)

    # owner-only (and optionally role check)
    if request.user != event.owner:
        return HttpResponseForbidden("You do not have permission to manage this event.")

    # This page should show: edit event + add/edit items (not public view)
    return render(request, "garage_sale/event_manage.html", {"event": event})


def item_detail(request, item_id: int):
    item = get_object_or_404(
        SaleItem,
        id=item_id,
        is_listed=True,
        quantity_available__gt=0,
    )

    cart = _get_cart(request)
    cart_count = sum(int(q) for q in cart.values()) if cart else 0

    user_role = getattr(request.user, "role", "")
    can_shop = request.user.is_authenticated and user_role == "CUSTOMER"

    return render(request, "garage_sale/item_detail.html", {
        "item": item,
        "cart_count": cart_count,
        "can_shop": can_shop,
    })

# -------------------------
# Cart
# -------------------------

def cart_view(request):
    cart = _get_cart(request)
    item_ids = [int(k) for k in cart.keys()] if cart else []

    items = (
        SaleItem.objects
        .filter(id__in=item_ids, is_listed=True, quantity_available__gt=0)
        .select_related("event")
    )

    line_items = []
    total = Decimal("0.00")

    item_map = {i.id: i for i in items}
    for k, qty in cart.items():
        item_id = int(k)
        qty = int(qty)
        item = item_map.get(item_id)
        if not item:
            continue

        price = item.price or Decimal("0.00")
        line_total = price * qty
        total += line_total
        line_items.append({
            "item": item,
            "qty": qty,
            "line_total": line_total,
        })

    return render(request, "garage_sale/cart_review.html", {
        "line_items": line_items,
        "total": total,
        "cart_count": _cart_count(cart),
    })


def cart_add(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    item_id = request.POST.get("item_id")
    qty = request.POST.get("qty", "1")

    try:
        item_id = int(item_id)
        qty = max(1, int(qty))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Bad item_id/qty")

    # Only allow adding listed + in-stock items
    item = get_object_or_404(
        SaleItem,
        pk=item_id,
        is_listed=True,
        quantity_available__gt=0,
    )

    cart = _get_cart(request)
    cart[str(item.id)] = int(cart.get(str(item.id), 0)) + qty
    _save_cart(request, cart)

    return redirect("garage_sale:cart")


def cart_remove(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    item_id = request.POST.get("item_id")
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Bad item_id")

    cart = _get_cart(request)
    cart.pop(str(item_id), None)
    _save_cart(request, cart)

    return redirect("garage_sale:cart")


# -------------------------
# Checkout -> Reservation
# -------------------------

@login_required
def checkout(request):
    """
    Creates a Reservation for current user from cart contents.
    NOTE: currently does not decrement stock; you can do that on "confirm" later.
    """
    cart = _get_cart(request)
    if not cart:
        return redirect("garage_sale:cart")

    item_ids = [int(k) for k in cart.keys()]
    items = list(
        SaleItem.objects
        .filter(id__in=item_ids, is_listed=True, quantity_available__gt=0)
        .select_related("event")
    )

    item_map = {i.id: i for i in items}

    with transaction.atomic():
        reservation = Reservation.objects.create(
            customer=request.user,
            status=Reservation.Status.PENDING,  # adjust if your enum differs
        )

        total = Decimal("0.00")

        for k, qty in cart.items():
            item_id = int(k)
            qty = int(qty)
            item = item_map.get(item_id)
            if not item:
                continue

            price = item.price or Decimal("0.00")
            line_total = price * qty
            total += line_total

            ReservationItem.objects.create(
                reservation=reservation,
                item=item,
                quantity=qty,
                unit_price=price,
            )

        reservation.total_amount = total
        reservation.save(update_fields=["total_amount"])

    # Clear cart after successful reservation creation
    _save_cart(request, {})

    return redirect("garage_sale:reservation_detail", reservation_id=reservation.id)


@login_required
def reservation_detail(request, reservation_id: int):
    reservation = get_object_or_404(
        Reservation,
        pk=reservation_id,
        customer=request.user,
    )

    qs = (
        ReservationItem.objects
        .filter(reservation=reservation)
        .select_related("item", "item__event")
        .order_by("id")
    )

    items = []
    for r in qs:
        r.line_total = r.quantity * r.unit_price
        items.append(r)

    return render(request, "garage_sale/reservation_detail.html", {
        "reservation": reservation,
        "items": items,
        "cart_count": _cart_count(_get_cart(request)),
    })


# -------------------------
# Owner views (light wiring)
# -------------------------

@login_required
def owner_dashboard(request):
    # Later: enforce request.user.role == "LOCATION_OWNER" if you want strict gating
    events = GarageSaleEvent.objects.filter(owner=request.user).order_by("-id")
    return render(request, "garage_sale/owner/dashboard.html", {"events": events})


@login_required
def owner_items(request, event_id: int):
    event = get_object_or_404(GarageSaleEvent, pk=event_id, owner=request.user)
    items = SaleItem.objects.filter(event=event).order_by("title", "id")

    return render(request, "garage_sale/owner/items_list.html", {
        "event": event,
        "items": items,
        "is_owner": True,
        "preselected": set(),
    })


@login_required
def owner_event_create(request):
    if request.method == "POST":
        event_form = GarageSaleEventForm(request.POST)

        create_new_location = request.POST.get("create_new_location") == "1"
        location_form = LocationCreateForm(request.POST) if create_new_location else LocationCreateForm()

        if event_form.is_valid() and (not create_new_location or location_form.is_valid()):
            with transaction.atomic():
                event = event_form.save(commit=False)
                event.owner = request.user

                if create_new_location:
                    loc = location_form.save(commit=False)
                    # Optional: only set owner if their role is LOCATION_OWNER
                    if getattr(request.user, "role", "") == "LOCATION_OWNER":
                        loc.owner = request.user
                    else:
                        loc.owner = None
                    loc.save()
                    event.location = loc
                else:
                    event.location = event_form.cleaned_data["location"]

                event.save()
                event_form.save_m2m()

            return redirect("garage_sale:owner_items", event_id=event.id)

        return render(request, "garage_sale/owner/event_form.html", {
            "form": event_form,
            "location_form": location_form,
        })

    # GET
    return render(request, "garage_sale/owner/event_form.html", {
        "form": GarageSaleEventForm(),
        "location_form": LocationCreateForm(),
    })


@login_required
def owner_event_edit(request, event_id: int):
    event = get_object_or_404(GarageSaleEvent, pk=event_id, owner=request.user)

    if request.method == "POST":
        form = GarageSaleEventForm(request.POST, instance=event)
        if form.is_valid():
            form.save()
            messages.success(request, "Event updated.")
            return redirect("garage_sale:owner_items", event_id=event.id)
    else:
        form = GarageSaleEventForm(instance=event)

    # If your template expects location_form only on create, you can remove it here.
    return render(request, "garage_sale/owner/event_form.html", {
        "form": form,
        "event": event,
        "location_form": LocationCreateForm(),
    })


@login_required
def owner_event_reservations(request, event_id: int):
    event = get_object_or_404(GarageSaleEvent, pk=event_id, owner=request.user)
    reservations = (
        Reservation.objects
        .filter(items__item__event=event)
        .distinct()
        .order_by("-id")
    )
    return render(request, "garage_sale/owner/reservations.html", {
        "event": event,
        "reservations": reservations,
    })


@login_required
def owner_item_create(request, event_id: int):
    event = get_object_or_404(GarageSaleEvent, pk=event_id, owner=request.user)

    if request.method == "POST":
        form = SaleItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.event = event
            item.save()
            messages.success(request, "Item added.")
            return redirect("garage_sale:owner_items", event_id=event.id)
    else:
        form = SaleItemForm()

    return render(request, "garage_sale/owner/item_form.html", {
        "event": event,
        "form": form,
        "mode": "create",
    })


@login_required
def owner_item_edit(request, item_id: int):
    item = get_object_or_404(SaleItem, pk=item_id, event__owner=request.user)
    event = item.event

    if request.method == "POST":
        form = SaleItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, "Item updated.")
            return redirect("garage_sale:owner_items", event_id=event.id)
    else:
        form = SaleItemForm(instance=item)

    return render(request, "garage_sale/owner/item_form.html", {
        "event": event,
        "form": form,
        "mode": "edit",
        "item": item,
    })


@login_required
def owner_item_delete(request, item_id: int):
    item = get_object_or_404(SaleItem, pk=item_id, event__owner=request.user)
    event_id = item.event_id

    if request.method == "POST":
        item.delete()
        messages.success(request, "Item deleted.")
        return redirect("garage_sale:owner_items", event_id=event_id)

    return render(request, "garage_sale/owner/item_confirm_delete.html", {
        "item": item,
        "event_id": event_id,
    })