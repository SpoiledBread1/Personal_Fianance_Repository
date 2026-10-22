from calendar import monthrange

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Account, AccountType, Budget, Category, MemberProfile, Transaction


class SignupForm(forms.Form):
    email = forms.EmailField(
        max_length=150,
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "autocapitalize": "none",
                "placeholder": "you@example.com",
                "spellcheck": "false",
            }
        ),
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"autocomplete": "new-password", "placeholder": "Create a password"}
        ),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "placeholder": "Enter your password again",
            }
        ),
    )
    bank_name = forms.CharField(
        max_length=100,
        label="Bank",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "organization",
                "placeholder": "Enter your bank",
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        user_model = get_user_model()
        if user_model.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        if user_model.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("This email is already in use.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")
        if password1:
            try:
                validate_password(password1)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned_data

    @transaction.atomic
    def save(self):
        email = self.cleaned_data["email"]
        user = get_user_model().objects.create_user(
            username=email,
            email=email,
            password=self.cleaned_data["password1"],
        )
        MemberProfile.objects.create(
            user=user, bank_name=self.cleaned_data["bank_name"].strip()
        )
        return user


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
        self.fields["category"].label = "Budget"
        self.fields["category"].queryset = (
            Category.objects.filter(budgets__user=user)
            .order_by("category_name")
            .distinct()
        )
        self.fields["category"].required = False
        self.fields["category"].empty_label = "Unbudgeted"

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


class BudgetForm(forms.ModelForm):
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
        label="Budget amount",
    )

    class Meta:
        model = Budget
        fields = ("category", "amount", "period_start", "period_end")
        widgets = {
            "period_start": forms.DateInput(attrs={"type": "date"}),
            "period_end": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "category": "Budget category",
            "period_start": "Period start",
            "period_end": "Period end",
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        today = timezone.localdate()
        self.fields["category"].queryset = Category.objects.order_by("category_name")
        self.fields["period_start"].initial = today.replace(day=1)
        self.fields["period_end"].initial = today.replace(
            day=monthrange(today.year, today.month)[1]
        )

    def clean(self):
        cleaned_data = super().clean()
        period_start = cleaned_data.get("period_start")
        period_end = cleaned_data.get("period_end")
        if period_start and period_end and period_end < period_start:
            self.add_error(
                "period_end", "The end date must be on or after the start date."
            )
        return cleaned_data

    def save(self, commit=True):
        budget = super().save(commit=False)
        budget.user = self.user
        if commit:
            budget.save()
        return budget