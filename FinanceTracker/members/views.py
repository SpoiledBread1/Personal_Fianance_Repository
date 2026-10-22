from django.contrib.auth import login
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template import loader

from .forms import SignupForm


def members(request):
    template = loader.get_template("myfirst.html")
    return HttpResponse(template.render())


def signup(request):
    if request.user.is_authenticated:
        return redirect("finance:dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("finance:dashboard")
    return render(request, "members/signup.html", {"form": form})