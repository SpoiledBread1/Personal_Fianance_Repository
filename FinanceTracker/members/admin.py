from django.contrib import admin

from .models import (
    Account,
    AccountType,
    Budget,
    Category,
    Holding,
    MarketCache,
    MemberProfile,
    Payee,
    Tag,
    Transaction,
    TransactionTag,
    WatchlistEntry,
)


class TransactionTagInline(admin.TabularInline):
    model = TransactionTag
    extra = 0
    autocomplete_fields = ("tag",)


@admin.register(AccountType)
class AccountTypeAdmin(admin.ModelAdmin):
    list_display = ("type_name",)
    search_fields = ("type_name",)
    ordering = ("type_name",)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        "account_name",
        "user",
        "account_type",
        "current_balance",
        "currency",
        "opened_date",
    )
    list_filter = ("currency", "account_type", "opened_date")
    search_fields = ("account_name", "user__username", "user__email")
    autocomplete_fields = ("user", "account_type")
    list_select_related = ("user", "account_type")
    readonly_fields = ("opened_date",)
    fieldsets = (
        ("Account", {"fields": ("account_name", "user", "account_type")}),
        ("Balance", {"fields": ("current_balance", "currency")}),
        ("Dates", {"fields": ("opened_date",)}),
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("category_name", "parent_category")
    list_filter = ("parent_category",)
    search_fields = ("category_name", "parent_category__category_name")
    autocomplete_fields = ("parent_category",)
    list_select_related = ("parent_category",)
    ordering = ("category_name",)


@admin.register(Payee)
class PayeeAdmin(admin.ModelAdmin):
    list_display = ("payee_name",)
    search_fields = ("payee_name",)
    ordering = ("payee_name",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("tag_name", "user")
    list_filter = ("user",)
    search_fields = ("tag_name", "user__username", "user__email")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    ordering = ("tag_name",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_date",
        "transaction_type",
        "amount",
        "account",
        "category",
        "payee",
    )
    list_filter = ("transaction_type", "transaction_date", "category", "account__currency")
    search_fields = (
        "description",
        "payee__payee_name",
        "account__account_name",
        "account__user__username",
        "account__user__email",
    )
    date_hierarchy = "transaction_date"
    autocomplete_fields = ("account", "category", "payee")
    list_select_related = ("account", "account__user", "category", "payee")
    inlines = (TransactionTagInline,)
    readonly_fields = ("created_at",)
    fieldsets = (
        ("Transaction", {"fields": ("transaction_date", "transaction_type", "amount")}),
        ("Details", {"fields": ("account", "category", "payee", "description")}),
        ("Audit", {"fields": ("created_at",)}),
    )


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ("category", "user", "amount", "period_start", "period_end")
    list_filter = ("period_start", "period_end", "category")
    search_fields = ("category__category_name", "user__username", "user__email")
    autocomplete_fields = ("user", "category")
    list_select_related = ("user", "category")
    date_hierarchy = "period_start"
    fieldsets = (
        ("Budget", {"fields": ("user", "category", "amount")}),
        ("Period", {"fields": ("period_start", "period_end")}),
    )


@admin.register(MemberProfile)
class MemberProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "bank_name")
    search_fields = ("user__username", "user__email", "bank_name")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)


@admin.register(Holding)
class HoldingAdmin(admin.ModelAdmin):
    list_display = ("symbol", "name", "shares", "user")
    list_filter = ("symbol",)
    search_fields = ("symbol", "name", "user__username", "user__email")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    ordering = ("symbol", "user__username")


@admin.register(WatchlistEntry)
class WatchlistEntryAdmin(admin.ModelAdmin):
    list_display = ("symbol", "name", "user")
    list_filter = ("symbol",)
    search_fields = ("symbol", "name", "user__username", "user__email")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    ordering = ("symbol", "user__username")


@admin.register(MarketCache)
class MarketCacheAdmin(admin.ModelAdmin):
    list_display = ("key", "fetched_at", "refresh_after", "lease_until")
    search_fields = ("key",)
    readonly_fields = ("key", "payload", "fetched_at", "refresh_after", "lease_until")
    fields = ("key", "payload", "fetched_at", "refresh_after", "lease_until")
    ordering = ("key",)

    def has_add_permission(self, request):
        return False


admin.site.site_header = "Sable Finance Administration"
admin.site.site_title = "Sable Admin"
admin.site.index_title = "Manage finance data and users"
