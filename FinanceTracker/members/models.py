from django.conf import settings
from django.db import models


class AccountType(models.Model):
    type_name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.type_name


class Account(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accounts"
    )
    account_type = models.ForeignKey(
        AccountType, on_delete=models.PROTECT, related_name="accounts"
    )
    account_name = models.CharField(max_length=100)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="USD")
    opened_date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.account_name} ({self.user})"


class Category(models.Model):
    category_name = models.CharField(max_length=100)
    parent_category = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subcategories",
    )

    class Meta:
        verbose_name_plural = "categories"

    def __str__(self):
        return self.category_name


class Payee(models.Model):
    payee_name = models.CharField(max_length=150, unique=True)

    def __str__(self):
        return self.payee_name


class Tag(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tags"
    )
    tag_name = models.CharField(max_length=50)

    class Meta:
        unique_together = ("user", "tag_name")

    def __str__(self):
        return self.tag_name


class Transaction(models.Model):
    class TransactionType(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="transactions"
    )
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transactions",
    )
    payee = models.ForeignKey(
        Payee,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transactions",
    )
    transaction_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=6, choices=TransactionType.choices)
    description = models.CharField(max_length=255, blank=True)
    tags = models.ManyToManyField(
        Tag, through="TransactionTag", related_name="transactions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.transaction_date} — {self.amount} ({self.account})"


class TransactionTag(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("transaction", "tag")


class Budget(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budgets"
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="budgets"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    period_start = models.DateField()
    period_end = models.DateField()

    def __str__(self):
        return f"{self.category} budget {self.period_start}–{self.period_end}"