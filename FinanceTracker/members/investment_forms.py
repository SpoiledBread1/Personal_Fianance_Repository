from decimal import Decimal

from django import forms

from .market_data import MarketDataError, resolve_instrument, SYMBOL_PATTERN
from .models import Holding, WatchlistEntry


class InstrumentForm(forms.ModelForm):
    symbol = forms.CharField(
        label="Stock or ETF", max_length=15,
        widget=forms.TextInput(attrs={"autocomplete": "off", "list": "instrument-results", "placeholder": "Search a company or enter AAPL"}),
        help_text="US-listed stocks and ETFs priced in USD. Select a ticker from the suggestions.",
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.original_symbol = self.instance.symbol if self.instance.pk else ""

    def clean_symbol(self):
        symbol = self.cleaned_data["symbol"].strip().upper()
        if not SYMBOL_PATTERN.fullmatch(symbol):
            raise forms.ValidationError("Enter a ticker symbol, for example AAPL or VOO.")
        if self._meta.model.objects.filter(user=self.user, symbol=symbol).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("You already track this symbol. Edit the existing entry instead.")
        limit = 20 if self._meta.model is Holding else 10
        if not self.instance.pk and self._meta.model.objects.filter(user=self.user).count() >= limit:
            raise forms.ValidationError(f"You can track up to {limit} entries here.")
        if symbol != self.original_symbol:
            try:
                instrument = resolve_instrument(symbol)
            except MarketDataError as error:
                raise forms.ValidationError(str(error)) from error
            self.instance.name = instrument["name"]
        return symbol

    def save(self, commit=True):
        self.instance.user = self.user
        return super().save(commit=commit)


class HoldingForm(InstrumentForm):
    shares = forms.DecimalField(
        label="Shares owned", max_digits=18, decimal_places=6,
        min_value=Decimal("0.000001"),
        widget=forms.NumberInput(attrs={"step": "0.000001", "min": "0.000001", "placeholder": "10.5"}),
        help_text="Fractional shares are supported. Enter your current total, not an additional purchase.",
    )

    class Meta:
        model = Holding
        fields = ["symbol", "shares"]


class WatchlistForm(InstrumentForm):
    class Meta:
        model = WatchlistEntry
        fields = ["symbol"]
