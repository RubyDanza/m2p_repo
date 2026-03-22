from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .forms import LocationForm
from .models import Location

User = get_user_model()


def _safe_next(request):
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return ""


def _get_service(request):
    service = (
        request.POST.get("service")
        or request.GET.get("service")
        or request.session.get("active_service")
        or ""
    ).strip().lower()

    if service not in {"physio", "garage_sale"}:
        service = "physio"

    return service


def home(request):
    return render(request, "core/home.html")


@login_required
def location_consultants(request, location_id):
    location = get_object_or_404(Location, id=location_id)

    if getattr(request.user, "role", None) != User.Role.LOCATION_OWNER or location.owner_id != request.user.id:
        return render(request, "core/not_allowed.html", status=403)

    consultants = User.objects.filter(role=User.Role.CONSULTANT).order_by("username")

    if request.method == "POST":
        ids = request.POST.getlist("consultant_ids")
        location.consultants.set(ids)
        messages.success(request, "Consultants updated.")
        return redirect("physio:owner_dashboard")

    selected_ids = set(location.consultants.values_list("id", flat=True))

    return render(
        request,
        "core/location_consultants.html",
        {
            "location": location,
            "consultants": consultants,
            "selected_ids": selected_ids,
        },
    )


@require_http_methods(["GET", "POST"])
def login_view(request):
    service = _get_service(request)
    request.session["active_service"] = service

    if request.user.is_authenticated:
        nxt = _safe_next(request)
        return redirect(nxt or "core:post_login")

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            request.session["active_service"] = service

            nxt = _safe_next(request)
            return redirect(nxt or "core:post_login")
    else:
        form = AuthenticationForm()

    return render(
        request,
        "core/login.html",
        {
            "form": form,
            "next": request.GET.get("next", ""),
            "service": service,
        },
    )


@login_required
def post_login(request):
    role = getattr(request.user, "role", User.Role.CUSTOMER)
    service = _get_service(request)
    request.session["active_service"] = service

    if role == User.Role.LOCATION_OWNER:
        if service == "garage_sale":
            return redirect("garage_sale:owner_dashboard")
        return redirect("physio:owner_dashboard")

    if role == User.Role.CONSULTANT:
        if service == "garage_sale":
            return redirect("garage_sale:home")
        return redirect(""
                        " physio:home")

    if service == "garage_sale":
        return redirect("garage_sale:home")
    return redirect("physio:home")


def logout_view(request):
    logout(request)
    nxt = _safe_next(request)
    return redirect(nxt or "core:home")


@require_http_methods(["GET", "POST"])
def register_view(request):
    service = _get_service(request)
    request.session["active_service"] = service
    next_url = _safe_next(request) or request.GET.get("next", "")

    def _render(error=None, prefill=None):
        ctx = {
            "error": error,
            "next": next_url,
            "service": service,
            "user_model": User,
            "prefill": prefill or {},
        }
        return render(request, "core/register.html", ctx)

    if request.method == "GET":
        return _render()

    username = (request.POST.get("username") or "").strip()
    role = (request.POST.get("role") or User.Role.CUSTOMER).strip()
    pw1 = request.POST.get("password1") or ""
    pw2 = request.POST.get("password2") or ""

    location_name = (request.POST.get("location_name") or "").strip()
    room_count = (request.POST.get("room_count") or "").strip()
    latitude = (request.POST.get("latitude") or "").strip()
    longitude = (request.POST.get("longitude") or "").strip()

    address_line_1 = (request.POST.get("address_line_1") or "").strip()
    address_line_2 = (request.POST.get("address_line_2") or "").strip()
    suburb = (request.POST.get("suburb") or "").strip()
    state = (request.POST.get("state") or "").strip()
    postcode = (request.POST.get("postcode") or "").strip()

    prefill = {
        "username": username,
        "role": role,
        "location_name": location_name,
        "room_count": room_count,
        "latitude": latitude,
        "longitude": longitude,
        "address_line_1": address_line_1,
        "address_line_2": address_line_2,
        "suburb": suburb,
        "state": state,
        "postcode": postcode,
    }

    if not username:
        return _render("Username required.", prefill)

    if pw1 != pw2:
        return _render("Passwords do not match.", prefill)

    if User.objects.filter(username=username).exists():
        return _render("Username already taken.", prefill)

    valid_roles = {c[0] for c in User.Role.choices}
    if role not in valid_roles:
        role = User.Role.CUSTOMER
        prefill["role"] = role

    room_count_int = None
    lat_val = None
    lng_val = None

    if role == User.Role.LOCATION_OWNER:
        owner_label = "Event name" if service == "garage_sale" else "Location name"

        if not location_name:
            return _render(f"{owner_label} is required.", prefill)

        if service == "physio":
            try:
                room_count_int = int(room_count) if room_count else 1
                if room_count_int < 1 or room_count_int > 3:
                    raise ValueError
            except ValueError:
                return _render("Rooms must be a number from 1 to 3.", prefill)

        try:
            lat_val = float(latitude)
            lng_val = float(longitude)
        except ValueError:
            return _render("Latitude and Longitude must be numbers.", prefill)

    user = User.objects.create_user(username=username, password=pw1, role=role)

    if role == User.Role.LOCATION_OWNER:
        location = Location(
            name=location_name,
            owner=user,
            latitude=lat_val,
            longitude=lng_val,
            is_physio=(service == "physio"),
            is_garage_sale=(service == "garage_sale"),
        )

        if service == "physio":
            location.room_count = room_count_int

        # Only set these if your Location model has these fields.
        if hasattr(location, "address_line_1"):
            location.address_line_1 = address_line_1
        if hasattr(location, "address_line_2"):
            location.address_line_2 = address_line_2
        if hasattr(location, "suburb"):
            location.suburb = suburb
        if hasattr(location, "state"):
            location.state = state
        if hasattr(location, "postcode"):
            location.postcode = postcode

        location.save()

    login(request, user)
    request.session["active_service"] = service
    messages.success(request, "Account created.")

    return redirect(next_url or "core:post_login")


@login_required
def location_add(request):
    if getattr(request.user, "role", None) != User.Role.LOCATION_OWNER:
        return HttpResponseForbidden("Location owners only")

    if request.method == "POST":
        form = LocationForm(request.POST)
        if form.is_valid():
            loc = form.save(commit=False)
            loc.owner = request.user
            loc.save()
            form.save_m2m()
            return redirect("physio:home")
    else:
        form = LocationForm(initial={"is_physio": True, "is_garage_sale": False})

    return render(request, "core/location_form.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def location_create(request):
    if request.user.role != User.Role.LOCATION_OWNER:
        return redirect("core:home")

    if request.method == "GET":
        return render(request, "core/location_form.html")

    name = (request.POST.get("name") or "").strip()
    room_count = (request.POST.get("room_count") or "").strip()
    latitude = (request.POST.get("latitude") or "").strip()
    longitude = (request.POST.get("longitude") or "").strip()

    if not name:
        return render(request, "core/location_form.html", {"error": "Location name is required."})

    try:
        room_count_int = int(room_count) if room_count else 1
        if room_count_int < 1 or room_count_int > 3:
            raise ValueError
    except ValueError:
        return render(request, "core/location_form.html", {"error": "Room count must be 1–3."})

    try:
        lat_val = float(latitude)
        lng_val = float(longitude)
    except ValueError:
        return render(request, "core/location_form.html", {"error": "Latitude and Longitude must be numbers."})

    Location.objects.create(
        name=name,
        owner=request.user,
        latitude=lat_val,
        longitude=lng_val,
        room_count=room_count_int,
        is_physio=True,
        is_garage_sale=False,
    )

    return redirect("physio:owner_dashboard")