from django import forms
from django.utils import timezone

from .models import Account, AccountType, Category, Transaction


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = (
            "account",
            "transaction_type",
            "amount",
            "transaction_date",
            "category",
            "description",
        )
        widgets = {
            "transaction_date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["transaction_date"].initial = timezone.localdate()
        self.fields["account"].queryset = Account.objects.filter(user=user).order_by(
            "account_name"
        )
        self.fields["category"].queryset = Category.objects.order_by("category_name")
        self.fields["category"].required = False

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Enter an amount greater than zero.")
        return amount


class AccountForm(forms.Form):
    account_name = forms.CharField(max_length=100, label="Account name")
    account_type_name = forms.ChoiceField(label="Account type")
    opening_balance = forms.DecimalField(
        max_digits=12, decimal_places=2, initial=0, label="Starting balance"
    )
    currency = forms.CharField(max_length=3, min_length=3, initial="USD")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        type_names = {"Checking", "Savings", "Cash", "Credit Card", "Investment", "Other"}
        type_names.update(AccountType.objects.values_list("type_name", flat=True))
        self.fields["account_type_name"].choices = [
            (name, name) for name in sorted(type_names)
        ]

    def clean_currency(self):
        return self.cleaned_data["currency"].upper()

    def save(self, user):
        account_type, _ = AccountType.objects.get_or_create(
            type_name=self.cleaned_data["account_type_name"]
        )
        return Account.objects.create(
            user=user,
            account_type=account_type,
            account_name=self.cleaned_data["account_name"],
            current_balance=self.cleaned_data["opening_balance"],
            currency=self.cleaned_data["currency"],
        )