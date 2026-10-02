from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template import loader


def members(request):
  template = loader.get_template("myfirst.html")
  return HttpResponse(template.render())


def signup(request):
  if request.method == "POST":
    form = UserCreationForm(request.POST)
    if form.is_valid():
      user = form.save()
      login(request, user)
      return redirect("finance:dashboard")
  else:
    form = UserCreationForm()
  return render(request, "members/signup.html", {"form": form})