from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import Account, AccountType, Budget, Category, Transaction


CUSTOM_CATEGORY = "__new__"
COMMON_CATEGORIES = (
    "Groceries",
    "Dining",
    "Transport",
    "Housing",
    "Utilities",
    "Healthcare",
    "Entertainment",
    "Shopping",
    "Insurance",
    "Education",
    "Personal Care",
    "Travel",
    "Savings",
)


def category_choices(include_uncategorized=False):
    choices = [("", "Uncategorized")] if include_uncategorized else []
    known_names = set()
    for name in COMMON_CATEGORIES:
        choices.append((name, name))
        known_names.add(name.casefold())
    for name in Category.objects.order_by("category_name").values_list(
        "category_name", flat=True
    ):
        if name.casefold() not in known_names:
            choices.append((name, name))
            known_names.add(name.casefold())
    choices.append((CUSTOM_CATEGORY, "Add a new category..."))
    return choices


class CategoryChoiceField(forms.ChoiceField):
    def valid_value(self, value):
        if (
            isinstance(value, str)
            and value not in ("", CUSTOM_CATEGORY)
            and bool(value.strip())
        ):
            return True
        return super().valid_value(value)

    def clean(self, value):
        value = super().clean(value)
        if value and len(value.strip()) > 100:
            raise forms.ValidationError("Category names must be 100 characters or fewer.")
        return value


def find_or_create_category(name):
    category = Category.objects.filter(category_name__iexact=name).first()
    if category is None:
        category = Category.objects.create(category_name=name)
    return category


class TransactionForm(forms.ModelForm):
    category_name = CategoryChoiceField(label="Category", required=False)
    custom_category = forms.CharField(
        label="New category",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Enter a category name"}),
    )

    class Meta:
        model = Transaction
        fields = (
            "account",
            "transaction_type",
            "amount",
            "transaction_date",
            "description",
        )
        widgets = {
            "transaction_date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
        }
        labels = {"category_name": "Category"}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["transaction_date"].initial = timezone.localdate()
        self.fields["account"].queryset = Account.objects.filter(user=user).order_by(
            "account_name"
        )
        self.fields["category_name"].choices = category_choices(
            include_uncategorized=True
        )
        self.order_fields(
            (
                "account",
                "transaction_type",
                "amount",
                "transaction_date",
                "category_name",
                "custom_category",
                "description",
            )
        )

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Enter an amount greater than zero.")
        return amount

    def clean(self):
        cleaned_data = super().clean()
        category_name = cleaned_data.get("category_name", "")
        legacy_category_id = self.data.get(self.add_prefix("category"))
        if not category_name and legacy_category_id:
            legacy_category = Category.objects.filter(pk=legacy_category_id).first()
            if legacy_category is None:
                self.add_error("category_name", "Select a valid category.")
            else:
                category_name = legacy_category.category_name
        if category_name == CUSTOM_CATEGORY:
            custom_category = cleaned_data.get("custom_category", "").strip()
            if not custom_category:
                self.add_error("custom_category", "Enter a category name.")
            else:
                cleaned_data["resolved_category_name"] = custom_category
        else:
            cleaned_data["resolved_category_name"] = category_name
        return cleaned_data

    def save(self, commit=True):
        transaction = super().save(commit=False)
        category_name = self.cleaned_data["resolved_category_name"]
        transaction.category = (
            find_or_create_category(category_name) if category_name else None
        )
        if commit:
            transaction.save()
            self.save_m2m()
        return transaction


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


class BudgetForm(forms.Form):
    category_name = CategoryChoiceField(label="Category")
    custom_category = forms.CharField(
        label="New category",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Enter a category name"}),
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0.01,
        label="Monthly limit",
        widget=forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category_name"].choices = [
            ("", "Select a category"),
            *category_choices(),
        ]

    def clean(self):
        cleaned_data = super().clean()
        category_name = cleaned_data.get("category_name")
        if category_name == CUSTOM_CATEGORY:
            custom_category = cleaned_data.get("custom_category", "").strip()
            if not custom_category:
                self.add_error("custom_category", "Enter a category name.")
            else:
                cleaned_data["resolved_category_name"] = custom_category
        else:
            cleaned_data["resolved_category_name"] = category_name
        return cleaned_data

    def save(self, user):
        category = find_or_create_category(self.cleaned_data["resolved_category_name"])

        today = timezone.localdate()
        period_start = today.replace(day=1)
        next_month = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        period_end = next_month - timedelta(days=1)
        return Budget.objects.update_or_create(
            user=user,
            category=category,
            period_start=period_start,
            period_end=period_end,
            defaults={"amount": self.cleaned_data["amount"]},
        )[0]