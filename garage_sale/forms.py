from core.models import Location
from .models import GarageSaleEvent
from django import forms
from .models import SaleItem



class SaleItemForm(forms.ModelForm):
    class Meta:
        model = SaleItem
        fields = ["title", "description", "price", "quantity_available", "is_listed"]

    def clean_price(self):
        price = self.cleaned_data.get("price")
        if price is None:
            return 0
        return price



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
