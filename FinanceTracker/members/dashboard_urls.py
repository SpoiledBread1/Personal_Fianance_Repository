from django.contrib.auth import views as auth_views
from django.urls import path
from .dashboard_views import (
    balances,
    budgets,
    dashboard,
    investments,
    transaction_delete,
    transaction_edit,
    transactions,
)
from .market_data_views import market_data, instrument_search
from .investment_views import holding_form, holding_delete, watchlist_add, watchlist_delete
from .views import signup

app_name = "finance"
urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("transactions/", transactions, name="transactions"),
    path("budgets/", budgets, name="budgets"),
    path("balances/", balances, name="balances"),
    path("investments/", investments, name="investments"),
    path("transactions/<int:pk>/edit/", transaction_edit, name="transaction-edit"),
    path("transactions/<int:pk>/delete/", transaction_delete, name="transaction-delete"),
    path("investments/add/", holding_form, name="holding-add"),
    path("investments/<int:pk>/edit/", holding_form, name="holding-edit"),
    path("investments/<int:pk>/remove/", holding_delete, name="holding-delete"),
    path("investments/search/", instrument_search, name="instrument-search"),
    path("watchlist/add/", watchlist_add, name="watchlist-add"),
    path("watchlist/<int:pk>/remove/", watchlist_delete, name="watchlist-delete"),
    path("market-data/", market_data, name="market-data"),
    path("login/", auth_views.LoginView.as_view(template_name="members/login.html", redirect_authenticated_user=True), name="login"),
    path("signup/", signup, name="signup"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
