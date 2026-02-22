from django import forms
from core.models import Location
from .models import GarageSaleEvent


class GarageSaleEventForm(forms.ModelForm):
    class Meta:
        model = GarageSaleEvent
        fields = ["title", "start_date", "end_date", "location", "consultant"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class LocationCreateForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ["name", "latitude", "longitude"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.required = False
