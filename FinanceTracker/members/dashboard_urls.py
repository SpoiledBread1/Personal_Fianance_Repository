from django.contrib.auth import views as auth_views
from django.urls import path
from .dashboard_views import dashboard, transaction_edit, transaction_delete
from .market_data_views import market_data
from .views import signup

app_name = "finance"
urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("transactions/<int:pk>/edit/", transaction_edit, name="transaction-edit"),
    path("transactions/<int:pk>/delete/", transaction_delete, name="transaction-delete"),
    path("market-data/", market_data, name="market-data"),
    path("login/", auth_views.LoginView.as_view(template_name="members/login.html", redirect_authenticated_user=True), name="login"),
    path("signup/", signup, name="signup"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
