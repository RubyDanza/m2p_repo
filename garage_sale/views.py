from decimal import Decimal
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from .forms import GarageSaleEventForm, LocationCreateForm
from .models import GarageSaleEvent, SaleItem, Reservation, ReservationItem


# -------------------------
# Helpers: session cart
# -------------------------

CART_KEY = "gs_cart"  # { "<item_id>": qty_int }

def _get_cart(request) -> dict:
    cart = request.session.get(CART_KEY)
    if not isinstance(cart, dict):
        cart = {}
    return cart

def _save_cart(request, cart: dict) -> None:
    request.session[CART_KEY] = cart
    request.session.modified = True


# -------------------------
# Public: Map + browsing
# -------------------------

def home(request):
    # Australia-ish default; override with your settings.DEFAULT_MAP_CENTER if you want
    default_center = getattr(settings, "DEFAULT_MAP_CENTER", [-25.0, 133.0])
    default_zoom = getattr(settings, "DEFAULT_MAP_ZOOM", 4)

    return render(request, "garage_sale/home_map.html", {
        "default_map_center": default_center,
        "default_map_zoom": default_zoom,
    })


def map_data(request):
    """
    Returns pins for the map.
    Keep it lightweight: only data you need for the popup.
    """
    today = timezone.localdate()
    qs = (
        GarageSaleEvent.objects
        .select_related("owner", "location")
        .order_by("start_date", "id")
    )

    pins = []
    for ev in qs:
        # Using Location for lat/lng (since event has FK location)
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
        })

    return JsonResponse({"pins": pins})


def event_detail(request, event_id: int):
    event = get_object_or_404(GarageSaleEvent, pk=event_id, is_active=True)

    items = (
        SaleItem.objects
        .filter(event=event, is_active=True)
        .order_by("title", "id")
    )

    cart = _get_cart(request)

    return render(request, "garage_sale/event_detail.html", {
        "event": event,
        "items": items,
        "cart_count": sum(int(q) for q in cart.values()) if cart else 0,
    })


# -------------------------
# Cart
# -------------------------

def cart_view(request):
    cart = _get_cart(request)
    item_ids = [int(k) for k in cart.keys()] if cart else []
    items = SaleItem.objects.filter(id__in=item_ids, is_active=True).select_related("event")

    line_items = []
    total = Decimal("0.00")

    item_map = {i.id: i for i in items}
    for k, qty in cart.items():
        item_id = int(k)
        qty = int(qty)
        item = item_map.get(item_id)
        if not item:
            continue
        line_total = (item.price or Decimal("0.00")) * qty
        total += line_total
        line_items.append({
            "item": item,
            "qty": qty,
            "line_total": line_total,
        })

    return render(request, "garage_sale/cart_review.html", {
        "line_items": line_items,
        "total": total,
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

    item = get_object_or_404(SaleItem, pk=item_id, is_active=True)

    cart = _get_cart(request)
    cart[str(item.id)] = int(cart.get(str(item.id), 0)) + qty
    _save_cart(request, cart)

    return redirect("garage_sale:cart_review")


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

    return redirect("garage_sale:cart_review")


# -------------------------
# Checkout -> Reservation
# -------------------------

@login_required
def checkout(request):
    """
    Simple: create a Reservation for current user.
    Assumes cart can include items from multiple events OR you can restrict to single event later.
    """
    cart = _get_cart(request)
    if not cart:
        return redirect("garage_sale:cart")

    item_ids = [int(k) for k in cart.keys()]
    items = list(SaleItem.objects.filter(id__in=item_ids, is_active=True).select_related("event"))

    # Basic validation: remove missing items
    item_map = {i.id: i for i in items}

    with transaction.atomic():
        reservation = Reservation.objects.create(
            customer=request.user,
            status=Reservation.Status.PENDING,  # adjust to your enum
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
    reservation = get_object_or_404(Reservation, pk=reservation_id, customer=request.user)
    items = []
    qs = (
        ReservationItem.objects
        .filter(reservation=reservation)
        .select_related("item", "item__event")
        .order_by("id")
    )

    for r in qs:
        r.line_total = r.quantity * r.unit_price
        items.append(r)


# -------------------------
# Owner views (light wiring)
# -------------------------

@login_required
def owner_dashboard(request):
    print("Authenticated:", request.user.is_authenticated)  # Debugging: Check if logged in
    # Adjust to your role system (e.g. request.user.role == "LOCATION_OWNER")
    events = GarageSaleEvent.objects.filter(owner=request.user).order_by("-id")
    return render(request, "garage_sale/owner/dashboard.html", {"events": events})


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

            # ✅ IMPORTANT: redirect after POST so the form doesn't show again
            return redirect("garage_sale:owner_dashboard")

        # invalid -> fall through and re-render with errors
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
    return render(request, "garage_sale/owner/event_form.html", {"event": event})


@login_required
def owner_items(request, event_id: int):
    event = get_object_or_404(GarageSaleEvent, pk=event_id, owner=request.user)
    items = SaleItem.objects.filter(event=event).order_by("name", "id")
    return render(request, "garage_sale/owner/items_list.html", {"event": event, "items": items})


@login_required
def owner_event_reservations(request, event_id: int):
    event = get_object_or_404(GarageSaleEvent, pk=event_id, owner=request.user)
    reservations = (
        Reservation.objects
        .filter(items__item__event=event)
        .distinct()
        .order_by("-id")
    )
    return render(request, "garage_sale/owner/reservations.html", {"event": event, "reservations": reservations})