from django.contrib.auth import views as auth_views
from django.urls import path
from .dashboard_views import balances, budgets, dashboard, news_stocks, transactions
from .views import signup

app_name = "finance"
urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("transactions/", transactions, name="transactions"),
    path("budgets/", budgets, name="budgets"),
    path("balances/", balances, name="balances"),
    path("news-stocks/", news_stocks, name="news_stocks"),
    path("login/", auth_views.LoginView.as_view(template_name="members/login.html", redirect_authenticated_user=True), name="login"),
    path("signup/", signup, name="signup"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
