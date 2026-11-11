from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .investment_forms import HoldingForm, WatchlistForm
from .models import Holding, WatchlistEntry


def _home():
    return redirect(reverse("finance:dashboard") + "#stocks-news")


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def holding_form(request, pk=None):
    entry = get_object_or_404(Holding, user=request.user, pk=pk) if pk is not None else None
    return _entry_form(request, HoldingForm, entry, "holding")


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def watchlist_add(request):
    return _entry_form(request, WatchlistForm, None, "watchlist entry")


def _entry_form(request, form_class, entry, kind):
    form = form_class(request.POST if request.method == "POST" else None, instance=entry, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            form.add_error("symbol", "This symbol was already saved. Reload and edit the existing entry.")
        else:
            messages.success(request, f"{kind.capitalize()} {'updated' if entry else 'added'}.")
            return _home()
    return render(request, "members/investment_form.html", {"form": form, "entry": entry, "kind": kind})


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def holding_delete(request, pk):
    entry = get_object_or_404(Holding, user=request.user, pk=pk)
    if request.method == "POST":
        entry.delete()
        messages.success(request, "Holding removed. No trade was placed.")
        return _home()
    return render(request, "members/investment_delete.html", {"entry": entry})


@login_required
@require_POST
def watchlist_delete(request, pk):
    get_object_or_404(WatchlistEntry, user=request.user, pk=pk).delete()
    messages.success(request, "Symbol removed from watchlist.")
    return _home()
