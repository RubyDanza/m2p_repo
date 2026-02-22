from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from django.http import HttpResponseForbidden
from .forms import LocationForm
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from .models import Location, User  # adjust if your User import differs


User = get_user_model()



@login_required
def location_consultants(request, location_id):
    location = get_object_or_404(Location, id=location_id)

    # Only owner can edit
    if getattr(request.user, "role", None) != User.Role.LOCATION_OWNER or location.owner_id != request.user.id:
        return render(request, "core/not_allowed.html", status=403)

    consultants = User.objects.filter(role=User.Role.CONSULTANT).order_by("username")

    if request.method == "POST":
        # getlist is crucial for checkboxes
        ids = request.POST.getlist("consultant_ids")
        location.consultants.set(ids)  # works with list of strings too
        messages.success(request, "Consultants updated.")
        return redirect("physio:owner_dashboard")

    selected_ids = set(location.consultants.values_list("id", flat=True))

    return render(request, "core/location_consultants.html", {
        "location": location,
        "consultants": consultants,
        "selected_ids": selected_ids,
    })


def _safe_next(request):
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return ""

def home(request):
    return render(request, "core/home.html")


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        nxt = _safe_next(request)
        return redirect(nxt or "core:post_login")

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())

            # if ?next=... exists, go there, else role-router
            nxt = _safe_next(request)
            return redirect(nxt or "core:post_login")
    else:
        form = AuthenticationForm()

    return render(request, "core/login.html", {
        "form": form,
        "next": request.GET.get("next", ""),
    })


@login_required
def post_login(request):
    """
    Role router. No template needed.
    """
    role = getattr(request.user, "role", User.Role.CUSTOMER)

    # optional: respect last chosen service
    service = (request.session.get("active_service") or "").lower()
    if service not in {"physio", "garage_sale"}:
        service = "physio"

    if role == User.Role.LOCATION_OWNER:
        # Owner dashboard could be per service later
        return redirect("core:location_owner_overview")

    if role == User.Role.CONSULTANT:
        # Consultant landing per service
        return redirect("garage_sale:home" if service == "garage_sale" else "physio:home")

    # Customers go to chosen service home
    return redirect("garage_sale:home" if service == "garage_sale" else "physio:home")



def logout_view(request):
    logout(request)
    nxt = _safe_next(request)
    return redirect(nxt or "core:home")


@require_http_methods(["GET", "POST"])
def register_view(request):
    """
    Shared registration view for all services (Physio, Garage Sale, etc.)

    Supports:
    - ?next=... redirect after registration (safe)
    - ?service=... (or POST service) so templates can show context
    - role-based fields:
        * CUSTOMER / CONSULTANT: username + password
        * LOCATION_OWNER: also creates the owner's first Location (physio flags preserved)
    """
    service = (request.GET.get("service") or request.POST.get("service") or "").strip()
    next_url = _safe_next(request) or request.GET.get("next", "")  # keep current behavior

    def _render(error=None, prefill=None):
        ctx = {
            "error": error,
            "next": next_url,
            "service": service,
            "user_model": User,   # template uses user_model.Role.choices
            "prefill": prefill or {},
        }
        return render(request, "core/register.html", ctx)

    # ---- GET ----
    if request.method == "GET":
        return _render()

    # ---- POST ----
    username = (request.POST.get("username") or "").strip()
    role = (request.POST.get("role") or User.Role.CUSTOMER).strip()
    pw1 = request.POST.get("password1") or ""
    pw2 = request.POST.get("password2") or ""

    # Owner fields (only required if role == LOCATION_OWNER)
    location_name = (request.POST.get("location_name") or "").strip()
    room_count = (request.POST.get("room_count") or "").strip()
    latitude = (request.POST.get("latitude") or "").strip()
    longitude = (request.POST.get("longitude") or "").strip()

    prefill = {
        "username": username,
        "role": role,
        "location_name": location_name,
        "room_count": room_count,
        "latitude": latitude,
        "longitude": longitude,
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

    # If owner, validate and parse owner-specific fields
    room_count_int = None
    lat_val = None
    lng_val = None

    if role == User.Role.LOCATION_OWNER:
        if not location_name:
            return _render("Location name is required for Location Owners.", prefill)

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

    # Create user
    user = User.objects.create_user(username=username, password=pw1, role=role)

    # If owner, create their FIRST location (preserve your Physio defaults)
    if role == User.Role.LOCATION_OWNER:
        Location.objects.create(
            name=location_name,
            owner=user,
            latitude=lat_val,
            longitude=lng_val,
            room_count=room_count_int,
            is_physio=True,
            is_garage_sale=False,
        )

    login(request, user)
    messages.success(request, "Account created.")

    # ✅ IMPORTANT: return to where the user came from (Create Event etc.)
    # next_url is already safe (via _safe_next); if blank, fall back.
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
            return redirect("physio:home")  # or core:location_owner_overview if you have it
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

    return redirect("core:home")