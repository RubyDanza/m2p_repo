from __future__ import annotations
import os
from collections import defaultdict
from datetime import date as date_cls, datetime
from django.conf import settings
from django.db import transaction
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.contrib.auth.forms import AuthenticationForm
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST, require_http_methods
import traceback
from django.db import IntegrityError
from django.utils.http import url_has_allowed_host_and_scheme
import json
from core.models import User, Location
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import Appointment
from django.contrib import messages


@ensure_csrf_cookie
def home(request):
    default_center = getattr(settings, "DEFAULT_MAP_CENTER", [-37.8136, 144.9631])
    default_zoom = getattr(settings, "DEFAULT_MAP_ZOOM", 10)

    return render(request, "physio/home_map.html", {
        "default_map_center": default_center,
        "default_map_zoom": default_zoom,
    })


def map_data(request):
    qs = (
        Location.objects.filter(is_physio=True)
        .exclude(latitude__isnull=True)
        .exclude(longitude__isnull=True)
    )
    locations = [{"id": l.id, "name": l.name, "lat": float(l.latitude), "lng": float(l.longitude)} for l in qs]
    return JsonResponse({"ok": True, "locations": locations})

@require_GET
def api_timeslots(request):
    location_id = request.GET.get("location_id")
    date_str = request.GET.get("date")  # YYYY-MM-DD
    if not location_id or not date_str:
        return JsonResponse({"ok": False, "error": "location_id and date required"}, status=400)

    _ = get_object_or_404(Location, id=location_id, is_physio=True)

    try:
        datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"ok": False, "error": "Invalid date format (YYYY-MM-DD)"}, status=400)

    return JsonResponse({"ok": True, "slots": SLOTS})


@require_GET
@login_required
def api_available_consultants(request):
    if getattr(request.user, "role", None) != User.Role.CUSTOMER:
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    location_id = request.GET.get("location_id")
    date_str = request.GET.get("date")
    time_str = request.GET.get("time")
    if not (location_id and date_str and time_str):
        return JsonResponse({"ok": False, "error": "Missing location_id/date/time"}, status=400)

    location = get_object_or_404(Location, id=location_id, is_physio=True)

    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        time_obj = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        return JsonResponse({"ok": False, "error": "Invalid date/time format"}, status=400)

    # v1: consultants linked to the location
    qs = location.consultants.filter(role=User.Role.CONSULTANT).order_by("username")

    # v1.1: optionally remove consultants already ACCEPTED at that time
    taken_ids = set(
        Appointment.objects.filter(
            consultant__in=qs,
            date=date_obj,
            time=time_obj,
            status=Appointment.Status.ACCEPTED,
        ).values_list("consultant_id", flat=True)
    )
    qs = qs.exclude(id__in=taken_ids)

    consultants = [{"id": u.id, "name": u.username} for u in qs]
    return JsonResponse({"ok": True, "consultants": consultants})


@require_POST
@login_required
def request_booking(request):
    """
    POST JSON:
      { "location_id": 2, "consultant_id": 7, "date": "2026-02-19", "time": "11:00" }

    Returns:
      { "ok": true, "appointment_id": 123 }
      or
      { "ok": false, "error": "..." }
    """
    # Must be customer
    if getattr(request.user, "role", None) != User.Role.CUSTOMER:
        return JsonResponse({"ok": False, "error": "Only customers can book."}, status=403)

    # Parse JSON body safely
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON body."}, status=400)

    location_id = payload.get("location_id")
    consultant_id = payload.get("consultant_id")
    date_str = payload.get("date")
    time_str = payload.get("time")

    if not (location_id and consultant_id and date_str and time_str):
        return JsonResponse({"ok": False, "error": "Missing location_id, consultant_id, date, or time."}, status=400)

    # Parse date/time
    try:
        appt_date = date_cls.fromisoformat(date_str)
    except Exception:
        return JsonResponse({"ok": False, "error": f"Bad date '{date_str}' (expected YYYY-MM-DD)."}, status=400)

    try:
        # accepts "11:00" or "11:00:00"
        appt_time = time_cls.fromisoformat(time_str)
    except Exception:
        return JsonResponse({"ok": False, "error": f"Bad time '{time_str}' (expected HH:MM)."}, status=400)

    # Load objects + validate consultant belongs to location
    try:
        location = Location.objects.get(id=location_id, is_physio=True)
    except Location.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Location not found."}, status=404)

    try:
        consultant = User.objects.get(id=consultant_id, role=User.Role.CONSULTANT)
    except User.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Consultant not found."}, status=404)

    if not location.consultants.filter(id=consultant.id).exists():
        return JsonResponse({"ok": False, "error": "Consultant is not linked to this location."}, status=400)

    # Create appointment (PENDING) – room can be allocated later when accepted
    try:
        with transaction.atomic():
            appt = Appointment.objects.create(
                location=location,
                consultant=consultant,
                created_by=request.user,
                customer_label=request.user.username,  # until you add FK
                date=appt_date,
                time=appt_time,
                status=Appointment.Status.PENDING,
            )
    except Exception as e:
        # Avoid silent 500s
        return JsonResponse({"ok": False, "error": f"Booking failed: {type(e).__name__}: {e}"}, status=400)

    return JsonResponse({"ok": True, "appointment_id": appt.id})

@require_GET
def debug_session(request):
    return JsonResponse({
        "active_service": request.session.get("active_service"),
        "is_authenticated": request.user.is_authenticated,
        "user": getattr(request.user, "username", None),
        "role": getattr(request.user, "role", None),
    })


def set_active_service(request, service):
    service = (service or "").lower()
    request.session["active_service"] = service

    if service == "garage_sale":
        return redirect("garage_sale/home")

    if service == "physio":
        return redirect("physio/map_home")

    # future businesses
    return redirect("home")




def map_home(request):
    """
    Central map page:
    - reads ?service=physio or ?service=garage_sale and stores in session
    - returns pins based on active_service
    """
    requested = (request.GET.get("service") or "").lower().strip()

    # Remember the service the user clicked
    if requested in {"physio", "garage_sale"}:
        request.session["active_service"] = requested

    # Decide current mode:
    # - physio => physio pins
    # - garage_sale => garage sale pins
    # - otherwise => landing (no pins)
    service = request.session.get("active_service", "")

    if not service:
        service = "physio"
        request.session["active_service"] = "physio"

    # Gate pins
    if service == "physio":
        locations_qs = (
            Location.objects.filter(is_physio=True)
            .exclude(latitude__isnull=True)
            .exclude(longitude__isnull=True)
        )
    elif service == "garage_sale":
        locations_qs = (
            Location.objects.filter(is_garage_sale=True)
            .exclude(latitude__isnull=True)
            .exclude(longitude__isnull=True)
        )
    else:
        locations_qs = Location.objects.none()

    locations = [
        {
            "id": loc.id,
            "name": loc.name,
            "lat": float(loc.latitude),
            "lng": float(loc.longitude),
        }
        for loc in locations_qs
    ]

    return render(
        request,
        "home.html",
        {
            "locations_json": json.dumps(locations),
            "service": service,
        },
    )

def mfp_landing(request):
    # optional: clear active service so it feels like “home”
    request.session.pop("active_service", None)
    return render(request, "mfp_landing.html")



@login_required
def onboarding_router(request):
    role = getattr(request.user, "role", None)

    if role == User.Role.CONSULTANT:
        return redirect("consultant_onboarding")

    # If you later re-enable:
    # if role == User.Role.LOCATION_OWNER:
    #     return redirect("physio/location_owner_overview")

    return redirect("home")


# Example static schedule (replace later with real availability)
SLOTS = ["09:00", "10:00", "11:00", "13:00", "14:00", "15:00"]


@require_POST
@login_required
def request_booking(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    if request.user.role != User.Role.CUSTOMER:
        return JsonResponse({"ok": False, "error": "Only customers can book appointments."}, status=403)

    location_id = data.get("location_id")
    consultant_id = data.get("consultant_id")
    date_str = data.get("date")
    time_str = data.get("time")

    if not (location_id and consultant_id and date_str and time_str):
        return JsonResponse({"ok": False, "error": "Missing booking fields"}, status=400)

    location = get_object_or_404(Location, id=location_id)
    consultant = get_object_or_404(User, id=consultant_id, role=User.Role.CONSULTANT)

    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        time_obj = datetime.strptime(time_str, "%H:%M").time()

        appt = Appointment.objects.create(
            location=location,
            location_label=location.name,
            consultant=consultant,
            created_by=request.user,
            customer_label=request.user.username,
            date=date_obj,
            time=time_obj,
            status=Appointment.Status.PENDING,
        )

        return JsonResponse({"ok": True, "appointment_id": appt.id, "status": appt.status})

    except IntegrityError as e:
        # Usually: a required field is missing or unique constraint hit
        payload = {"ok": False, "error": f"DB integrity error: {str(e)}"}
        if settings.DEBUG:
            payload["trace"] = traceback.format_exc()
        return JsonResponse(payload, status=500)

    except Exception as e:
        payload = {"ok": False, "error": str(e)}
        if settings.DEBUG:
            payload["trace"] = traceback.format_exc()
        return JsonResponse(payload, status=500)


def _token_valid(appt: Appointment) -> bool:
    if appt.action_token_expires_at and timezone.now() > appt.action_token_expires_at:
        return False
    return True


def partner_landing(request):
    return render(request, "partner_landing.html")

# -----------------------------
# Auth (uses templates in central/templates/registration/)
# -----------------------------



def login_view(request):
    if request.user.is_authenticated:
        return redirect("physio/post_login")

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)

            # ✅ NEXT ALWAYS WINS
            next_url = request.POST.get("next") or request.GET.get("next")
            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}
            ):
                return redirect(next_url)

            # fallback to role-based routing
            return redirect("post_login")
    else:
        form = AuthenticationForm()

    return render(request, "registration/login.html", {
        "form": form,
        "next": request.GET.get("next", ""),
    })


def logout_view(request):
    request.session.pop("active_service", None)  # <-- this is the reset
    logout(request)
    return redirect("home")


@require_http_methods(["GET", "POST"])
def register(request):
    if request.method == "GET":
        return render(request, "registration/register.html")

    # ---- POST ----
    role = request.POST.get("role", User.Role.CUSTOMER)
    username = (request.POST.get("username") or "").strip()
    pw1 = request.POST.get("password1") or ""
    pw2 = request.POST.get("password2") or ""

    email = request.POST.get("email", "").strip()
    phone = request.POST.get("phone", "").strip()

    # Owner fields (optional unless role == LOCATION_OWNER)
    location_name = (request.POST.get("location_name") or "").strip()
    room_count = (request.POST.get("room_count") or "").strip()
    latitude = (request.POST.get("latitude") or "").strip()
    longitude = (request.POST.get("longitude") or "").strip()

    # Basic validation
    if not username:
        return render(request, "registration/register.html", {"error": "Username is required."})

    if pw1 != pw2:
        return render(request, "registration/register.html", {"error": "Passwords do not match."})

    if User.objects.filter(username=username).exists():
        return render(request, "registration/register.html", {"error": "That username is already taken."})

    try:
        validate_password(pw1)
    except ValidationError as e:
        return render(request, "registration/register.html", {"error": " ".join(e.messages)})

    # Role validation
    valid_roles = {c[0] for c in User.Role.choices}
    if role not in valid_roles:
        role = User.Role.CUSTOMER

    # If owner, validate location fields now
    if role == User.Role.LOCATION_OWNER:
        if not location_name:
            return render(request, "registration/register.html", {
                "error": "Location name is required for Location Owners.",
                "prefill": request.POST,
            })

        # room_count default
        try:
            room_count_int = int(room_count) if room_count else 1
            if room_count_int < 1 or room_count_int > 3:
                return render(request, "registration/register.html", {
                    "error": "Room count must be 1–3.",
                    "prefill": request.POST,
                })
        except ValueError:
            return render(request, "registration/register.html", {
                "error": "Room count must be a number (1–3).",
                "prefill": request.POST,
            })

        # lat/long required (since you asked to load at registration)
        try:
            lat_val = float(latitude)
            lng_val = float(longitude)
        except ValueError:
            return render(request, "registration/register.html", {
                "error": "Latitude and Longitude must be numbers.",
                "prefill": request.POST,
            })

    # Create user
    user = User.objects.create_user(username=username, password=pw1, role=role)

    # If owner, create their first location
    if role == User.Role.LOCATION_OWNER:
        Location.objects.create(
            name=location_name,
            owner=user,
            latitude=lat_val,
            longitude=lng_val,
            room_count=room_count_int,
        )

    # ✅ THIS is what “store them on the user” means
    user.email = email
    user.phone = phone
    user.save()

    # Auto-login after registration
    login(request, user)

    # Redirect by role
    if role == User.Role.LOCATION_OWNER:
        return redirect("physio/location_owner_overview")
    if role == User.Role.CONSULTANT:
        return redirect("physio/consultant_onboarding")  # or your onboarding router
    return redirect("physio/home")


@login_required
def post_login(request):

    if request.session.get("active_service") == "garage_sale":
        return redirect("garage_sale:post_login_router")

    role = getattr(request.user, "role", User.Role.CUSTOMER)

    active_service = request.session.get("active_service")
    if active_service not in {"physio", "garage_sale"}:
        active_service = "physio"  # hard default

    if role == User.Role.CUSTOMER:
        return redirect("garage_sale:home" if active_service == "garage_sale" else "physio/home")

    if role == User.Role.CONSULTANT:
        return redirect("garage_sale:consultant_dashboard" if active_service == "garage_sale"
                        else "physio/consultant_requests")

    if role == User.Role.LOCATION_OWNER:
        active_service = request.session.get("active_service", "physio")
        if active_service == "garage_sale":
            return redirect("garage_sale:owner_dashboard")
        return redirect("physio/location_owner_dashboard")

    return redirect("physio/home")

# -----------------------------
# Dashboards (placeholders)
# -----------------------------

@login_required
def consultant_dashboard(request):
    if getattr(request.user, "role", "") != "CONSULTANT":
        return redirect("physio:home")  # ✅ instead of 403

    today = timezone.localdate()

    consultant_appointments = (
        Appointment.objects
        .filter(consultant=request.user)
        .select_related("location")
        .order_by("date", "time", "id")
    )

    return render(request, "physio/consultant_dashboard.html", {
        "consultant_appointments": consultant_appointments,
        "today": today,
        "next_url": reverse("physio:home"),
    })


@login_required
def location_owner_dashboard(request):
    return redirect("physio/location_owner_overview")


# -----------------------------
# Appointments (placeholders)
# -----------------------------

@login_required
def book_appointment(request):
    return render(request, "central/appointments/book_appointment.html")

@login_required
def view_appointments(request):
    return render(request, "central/appointments/view_appointments.html")



@login_required
def appointment_status(request, appointment_id):
    appt = get_object_or_404(Appointment, id=appointment_id)

    # Customer = who created it
    is_customer = (appt.created_by_id == request.user.id)
    is_consultant = (appt.consultant_id == request.user.id)

    if not (is_customer or is_consultant):
        return JsonResponse({"ok": False, "error": "Forbidden"}, status=403)

    return JsonResponse({
        "ok": True,
        "appointment_id": appt.id,
        "status": appt.status,
        "room_number": appt.room_number,
    })



@login_required
def consultant_appointments(request):
    if request.user.role != request.user.Role.CONSULTANT:
        return redirect("physio:home")

    appointments = Appointment.objects.filter(
        consultant=request.user
    ).order_by("date", "time")

    return render(request, "physio/consultant_appointments.html", {
        "appointments": appointments
    })




@login_required
def consultant_requests(request):
    pending = Appointment.objects.filter(
        consultant=request.user,
        status="PENDING",
    ).order_by("date", "time")

    return render(request, "central/consultant_requests.html", {"pending": pending})

@login_required
@require_POST
def consultant_accept(request, appointment_id):
    if getattr(request.user, "role", None) != User.Role.CONSULTANT:
        return redirect("physio/home")

    appt = get_object_or_404(
        Appointment,
        id=appointment_id,
        consultant=request.user,
    )

    # only allow accepting pending
    if appt.status != Appointment.Status.PENDING:
        return redirect("physio/consultant_requests")

    # 1) Prevent consultant double-booking
    consultant_taken = Appointment.objects.filter(
        consultant=request.user,
        date=appt.date,
        time=appt.time,
        status=Appointment.Status.ACCEPTED,
    ).exclude(id=appt.id).exists()

    if consultant_taken:
        appt.status = Appointment.Status.DECLINED
        appt.save(update_fields=["status"])
        messages.warning(request, f"Request #{appt.id} auto-declined: you already have an ACCEPTED booking at that time.")
        return redirect("physio/consultant_requests")

    # 2) Allocate a room (only if location exists + not already set)
    if appt.location and not appt.room_number:
        room_count = getattr(appt.location, "room_count", 0) or 0

        if room_count >= 1:
            taken_rooms = set(
                Appointment.objects.filter(
                    location=appt.location,
                    date=appt.date,
                    time=appt.time,
                    status=Appointment.Status.ACCEPTED,
                ).exclude(id=appt.id).values_list("room_number", flat=True)
            )

            chosen = None
            for r in range(1, room_count + 1):
                if r not in taken_rooms:
                    chosen = r
                    break

            if chosen is None:
                appt.status = Appointment.Status.DECLINED
                appt.save(update_fields=["status"])
                messages.warning(request, f"Request #{appt.id} auto-declined: no rooms available at {appt.location.name} for that timeslot.")
                return redirect("physio/consultant_requests")

            appt.room_number = chosen

    # 3) Accept
    appt.status = Appointment.Status.ACCEPTED
    appt.save(update_fields=["status", "room_number"])
    messages.success(request, f"Accepted appointment #{appt.id} (Room {appt.room_number or 'TBD'}).")
    return redirect("physio/consultant_requests")

@login_required
@require_POST
def consultant_decline(request, appointment_id):
    if getattr(request.user, "role", None) != User.Role.CONSULTANT:
        return redirect("physio/home")

    appt = get_object_or_404(
        Appointment,
        id=appointment_id,
        consultant=request.user,
    )

    if appt.status != Appointment.Status.PENDING:
        return redirect("physio/consultant_requests")

    appt.status = Appointment.Status.DECLINED
    appt.save(update_fields=["status"])
    messages.info(request, f"Declined appointment #{appt.id}.")
    return redirect("physio/consultant_requests")


@login_required
def consultant_onboarding(request):
    if request.user.role != User.Role.CONSULTANT:
        return render(request, "central/consultant_forbidden.html", status=403)

    locations = Location.objects.all().order_by("name")

    pending_ids = set(
        LocationJoinRequest.objects.filter(
            consultant=request.user, status=LocationJoinRequest.STATUS_PENDING
        ).values_list("location_id", flat=True)
    )

    joined_ids = set(
        request.user.consultant_locations.values_list("id", flat=True)
    )

    return render(request, "central/onboarding/consultant_onboarding.html", {
        "locations": locations,
        "pending_ids": pending_ids,
        "joined_ids": joined_ids,
    })


@login_required
def consultant_accept(request, pk):
    appt = get_object_or_404(Appointment, pk=pk, consultant=request.user)

    if appt.status != Appointment.Status.PENDING:
        return redirect("physio:consultant_appointments")

    appt.status = Appointment.Status.ACCEPTED
    appt.save()

    return redirect("physio:consultant_appointments")


@login_required
def consultant_decline(request, pk):
    appt = get_object_or_404(Appointment, pk=pk, consultant=request.user)

    if appt.status != Appointment.Status.PENDING:
        return redirect("physio:consultant_appointments")

    appt.status = Appointment.Status.DECLINED
    appt.save()

    return redirect("physio:consultant_appointments")

@login_required
@require_POST
def consultant_request_join(request, location_id):
    if request.user.role != User.Role.CONSULTANT:
        return redirect("physio/home")

    location = get_object_or_404(Location, id=location_id)

    if location.owner is None:
        messages.error(request, "This location has no owner yet.")
        return redirect("physio/consultant_onboarding")

    LocationJoinRequest.objects.get_or_create(
        consultant=request.user,
        location=location,
    )
    return redirect("physio/consultant_onboarding")

@login_required
def owner_dashboard(request):
    if request.user.role != User.Role.LOCATION_OWNER:
        return render(request, "physio/not_allowed.html")

    locations = request.user.owned_locations.all()
    appointments = Appointment.objects.filter(
        location__owner=request.user
    ).select_related("consultant", "location")

    return render(request, "physio/owner_dashboard.html", {
        "locations": locations,
        "appointments": appointments,
        "next_url": reverse("physio:home"),
    })

@login_required
@require_GET
def location_owner_overview(request):
    if getattr(request.user, "role", None) != User.Role.LOCATION_OWNER:
        return render(request, "central/location_owner_forbidden.html", status=403)

    today = date_cls.today()

    locations = Location.objects.filter(owner_id=request.user.id).order_by("name")

    # ✅ Debug (temporary)
    debug_user = {"id": request.user.id, "username": request.user.username, "role": getattr(request.user, "role", None)}
    debug_owned = list(locations.values("id", "name", "owner_id"))

    base_qs = (
        Appointment.objects
        .filter(location__in=locations)
        .select_related("location", "consultant", "created_by")
    )

    past_appts = base_qs.filter(date__lt=today).order_by("-date", "-time")
    today_appts = base_qs.filter(date=today).order_by("time")
    future_appts = base_qs.filter(date__gt=today).order_by("date", "time")

    # Backward compatible: upcoming list for your current template
    appts = base_qs.filter(date__gte=today).order_by("date", "time")

    # Occupancy grid for today+future
    occupancy = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    times_by_date_loc = defaultdict(lambda: defaultdict(set))

    for a in appts:
        if not a.time or not a.location_id:
            continue
        d = a.date.isoformat()
        t = a.time.strftime("%H:%M")
        times_by_date_loc[d][a.location_id].add(t)

        if a.room_number:
            occupancy[d][a.location_id][t][a.room_number] = a
        else:
            occupancy[d][a.location_id][t].setdefault(0, [])
            occupancy[d][a.location_id][t][0].append(a)

    dates_sorted = sorted(times_by_date_loc.keys())
    times_sorted = {
        d: {loc_id: sorted(times_by_date_loc[d][loc_id]) for loc_id in times_by_date_loc[d]}
        for d in times_by_date_loc
    }

    return render(request, "central/appointments/location_owner_overview.html", {
        "locations": locations,
        "appts": appts,  # ✅ your current template uses this
        "past_appts": past_appts,
        "today_appts": today_appts,
        "future_appts": future_appts,
        "occupancy": occupancy,
        "dates_sorted": dates_sorted,
        "times_sorted": times_sorted,
        "today": today,

        # ✅ Debug (remove later)
        "debug_user": debug_user,
        "debug_owned": debug_owned,
        "debug_counts": {
            "past": past_appts.count(),
            "today": today_appts.count(),
            "future": future_appts.count(),
            "upcoming": appts.count(),
        },
    })

@login_required
@require_POST
def owner_approve_join(request, req_id):
    if getattr(request.user, "role", None) != User.Role.LOCATION_OWNER:
        return redirect("physio/home")

    jr = get_object_or_404(LocationJoinRequest, id=req_id)

    # Security: owner can only approve requests for their own locations
    if jr.location.owner_id != request.user.id:
        messages.error(request, "Not allowed.")
        return redirect("physio/owner_onboarding")

    # Mark approved (use YOUR status constants/field names)
    jr.status = LocationJoinRequest.STATUS_APPROVED  # or "APPROVED"
    jr.save(update_fields=["status"])

    # ✅ The important part:
    jr.location.consultants.add(jr.consultant)

    messages.success(request, f"Approved {jr.consultant.username} for {jr.location.name}.")
    return redirect("physio/location_owner_overview")

@login_required
@require_POST
def owner_decline_join(request, request_id):
    if getattr(request.user, "role", None) != User.Role.LOCATION_OWNER:
        return redirect("physio/home")

    jr = get_object_or_404(LocationJoinRequest, id=req_id)

    if jr.location.owner_id != request.user.id:
        messages.error(request, "Not allowed.")
        return redirect("physio/owner_onboarding")

    jr.status = LocationJoinRequest.STATUS_REJECTED  # or "REJECTED"
    jr.save(update_fields=["status"])

    messages.info(request, f"Rejected {jr.consultant.username} for {jr.location.name}.")
    return redirect("physio/location_owner_overview")

@login_required
@require_GET
def owner_onboarding(request):
    # Only owners
    if getattr(request.user, "role", None) != User.Role.LOCATION_OWNER:
        return HttpResponseForbidden("Owners only")

    # Locations owned by this owner
    locations = Location.objects.filter(owner=request.user).order_by("name")

    # Join requests for those locations (pending first)
    reqs = (
        LocationJoinRequest.objects
        .filter(location__in=locations)
        .select_related("location", "consultant", "location__owner")
        .order_by("status", "location__name", "consultant__username")
    )

    return render(request, "central/onboarding/owner_onboarding.html", {
        "locations": locations,
        "reqs": reqs,
    })


@login_required
@require_POST
def owner_approve_join(request, req_id):
    if getattr(request.user, "role", None) != User.Role.LOCATION_OWNER:
        return HttpResponseForbidden("Owners only")

    jr = get_object_or_404(LocationJoinRequest, id=req_id)

    # Security: owner can only act on their own locations
    if jr.location.owner_id != request.user.id:
        return HttpResponseForbidden("Not your location")

    if jr.status != LocationJoinRequest.STATUS_PENDING:
        messages.info(request, "That request is already processed.")
        return redirect("physio/owner_onboarding")

    # Approve + add consultant to that location
    jr.status = LocationJoinRequest.STATUS_ACCEPTED
    jr.save(update_fields=["status"])
    jr.location.consultants.add(jr.consultant)

    messages.success(request, f"Approved: {jr.consultant.username} joined {jr.location.name}.")
    return redirect("physio/owner_onboarding")


@login_required
@require_POST
def owner_reject_join(request, req_id):
    if getattr(request.user, "role", None) != User.Role.LOCATION_OWNER:
        return HttpResponseForbidden("Owners only")

    jr = get_object_or_404(LocationJoinRequest, id=req_id)

    if jr.location.owner_id != request.user.id:
        return HttpResponseForbidden("Not your location")

    if jr.status != LocationJoinRequest.STATUS_PENDING:
        messages.info(request, "That request is already processed.")
        return redirect("physio/owner_onboarding")

    jr.status = LocationJoinRequest.STATUS_DECLINED
    jr.save(update_fields=["status"])

    messages.warning(request, f"Rejected join request for {jr.consultant.username} → {jr.location.name}.")
    return redirect("physio/owner_onboarding")


def _token_valid(appt: Appointment) -> bool:
    return (appt.action_token_expires_at is None) or (appt.action_token_expires_at > timezone.now())


@login_required
def consultant_token_accept(request, token):
    appt = get_object_or_404(Appointment, action_token=token)

    # Must be the correct consultant
    if getattr(request.user, "role", None) != "CONSULTANT" or appt.consultant_id != request.user.id:
        return render(request, "core/token_result.html", {
            "title": "Not allowed",
            "message": "This link is not for your account.",
        }, status=403)

    # Token expiry check
    if not _token_valid(appt):
        return render(request, "core/token_result.html", {
            "title": "Link expired",
            "message": "This link has expired.",
        }, status=410)

    # Already decided?
    if appt.status != Appointment.Status.PENDING:
        return render(request, "core/token_result.html", {
            "title": "Already decided",
            "message": f"This request is already {appt.status}.",
        }, status=200)

    # Accept
    appt.status = Appointment.Status.ACCEPTED
    appt.save(update_fields=["status"])

    messages.success(request, "Appointment request accepted.")
    return redirect("physio:consultant_dashboard")


@login_required
def consultant_token_decline(request, token):
    appt = get_object_or_404(Appointment, action_token=token)

    if getattr(request.user, "role", None) != "CONSULTANT" or appt.consultant_id != request.user.id:
        return render(request, "core/token_result.html", {
            "title": "Not allowed",
            "message": "This link is not for your account.",
        }, status=403)

    if not _token_valid(appt):
        return render(request, "core/token_result.html", {
            "title": "Link expired",
            "message": "This link has expired.",
        }, status=410)

    if appt.status != Appointment.Status.PENDING:
        return render(request, "core/token_result.html", {
            "title": "Already decided",
            "message": f"This request is already {appt.status}.",
        }, status=200)

    appt.status = Appointment.Status.DECLINED
    appt.save(update_fields=["status"])

    messages.info(request, "Appointment request declined.")
    return redirect("physio:consultant_dashboard")
