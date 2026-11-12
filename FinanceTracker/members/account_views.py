import base64
import io
import logging

import pyotp
import qrcode
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import send_mail
from django.core import signing
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from qrcode.image.svg import SvgPathImage
import smtplib

from .forms import (
    AccountDetailsForm,
    AuthenticatorCodeForm,
    DisableAuthenticatorForm,
)
from .models import MemberProfile

logger = logging.getLogger(__name__)
PENDING_2FA_USER = "pending_2fa_user_id"
PENDING_2FA_ATTEMPTS = "pending_2fa_attempts"
PENDING_2FA_NEXT = "pending_2fa_next"
PENDING_2FA_BACKEND = "pending_2fa_backend"
EMAIL_CHANGE_SALT = "members.account-email-change"
EMAIL_CHANGE_MAX_AGE = 24 * 60 * 60


def _fernet():
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"sable-authenticator-secret",
    ).derive(settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt_totp_secret(secret):
    return _fernet().encrypt(secret.encode()).decode()


def _decrypt_totp_secret(profile):
    if not profile.totp_secret:
        return ""
    try:
        return _fernet().decrypt(profile.totp_secret.encode()).decode()
    except InvalidToken as error:
        raise ImproperlyConfigured(
            "The authenticator secret cannot be decrypted. Check that the stable "
            "SECRET_KEY configured in the deployment has not changed."
        ) from error


def _authenticator_qr_data(secret, user):
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=user.email or user.username,
        issuer_name="Sable Finance",
    )
    qr = qrcode.QRCode(box_size=5, border=3)
    qr.add_data(uri)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    output = io.BytesIO()
    image.save(output)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _send_email_change_confirmation(request, user, profile):
    token = signing.dumps(
        {"user_id": user.pk, "email": profile.pending_email},
        salt=EMAIL_CHANGE_SALT,
    )
    confirmation_url = request.build_absolute_uri(
        reverse("finance:email-confirm", kwargs={"token": token})
    )
    try:
        sent = send_mail(
            "Confirm your Sable email address",
            (
                f"Hello {user.first_name or 'there'},\n\n"
                "Confirm this email address for your Sable account by opening the link "
                "below within 24 hours:\n\n"
                f"{confirmation_url}\n\n"
                "Your current email address will stay active until you confirm this change."
            ),
            settings.DEFAULT_FROM_EMAIL,
            [profile.pending_email],
            fail_silently=False,
        )
    except (OSError, smtplib.SMTPException):
        logger.exception("Could not send an email address confirmation for user %s", user.pk)
        return False
    return sent == 1


class AccountLoginView(LoginView):
    template_name = "members/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        try:
            profile = user.profile
        except MemberProfile.DoesNotExist:
            profile = None
        if profile and profile.totp_enabled:
            self.request.session[PENDING_2FA_USER] = user.pk
            self.request.session[PENDING_2FA_ATTEMPTS] = 0
            self.request.session[PENDING_2FA_NEXT] = self.get_success_url()
            self.request.session[PENDING_2FA_BACKEND] = user.backend
            self.request.session.set_expiry(300)
            return redirect("finance:login-verify")
        return super().form_valid(form)


def login_verify(request):
    user_id = request.session.get(PENDING_2FA_USER)
    if not user_id:
        messages.error(request, "Your sign-in verification expired. Please log in again.")
        return redirect("finance:login")

    try:
        user = MemberProfile.objects.select_related("user").get(
            user_id=user_id, totp_enabled=True
        ).user
    except MemberProfile.DoesNotExist:
        request.session.pop(PENDING_2FA_USER, None)
        request.session.pop(PENDING_2FA_ATTEMPTS, None)
        request.session.pop(PENDING_2FA_NEXT, None)
        request.session.pop(PENDING_2FA_BACKEND, None)
        messages.error(request, "Authenticator sign-in is unavailable. Please log in again.")
        return redirect("finance:login")
    if not user.is_active:
        request.session.pop(PENDING_2FA_USER, None)
        request.session.pop(PENDING_2FA_ATTEMPTS, None)
        request.session.pop(PENDING_2FA_NEXT, None)
        request.session.pop(PENDING_2FA_BACKEND, None)
        messages.error(request, "This account cannot sign in. Contact support.")
        return redirect("finance:login")

    form = AuthenticatorCodeForm(request.POST or None)
    if request.method == "POST":
        attempts = request.session.get(PENDING_2FA_ATTEMPTS, 0) + 1
        request.session[PENDING_2FA_ATTEMPTS] = attempts
        if attempts > 5:
            request.session.pop(PENDING_2FA_USER, None)
            request.session.pop(PENDING_2FA_ATTEMPTS, None)
            request.session.pop(PENDING_2FA_NEXT, None)
            request.session.pop(PENDING_2FA_BACKEND, None)
            messages.error(request, "Too many invalid codes. Please log in again.")
            return redirect("finance:login")
        if form.is_valid():
            secret = _decrypt_totp_secret(user.profile)
            if secret and pyotp.TOTP(secret).verify(form.cleaned_data["code"], valid_window=1):
                request.session.pop(PENDING_2FA_USER, None)
                request.session.pop(PENDING_2FA_ATTEMPTS, None)
                next_url = request.session.pop(PENDING_2FA_NEXT, "")
                backend = request.session.pop(PENDING_2FA_BACKEND, "")
                if backend not in settings.AUTHENTICATION_BACKENDS:
                    request.session.pop(PENDING_2FA_USER, None)
                    messages.error(
                        request,
                        "Your sign-in verification expired. Please log in again.",
                    )
                    return redirect("finance:login")
                request.session.pop(PENDING_2FA_USER, None)
                request.session.set_expiry(0)
                login(request, user, backend=backend)
                return redirect(next_url or "finance:dashboard")
            form.add_error("code", "That code could not be verified. Try the latest code.")

    return render(
        request,
        "members/login_verify.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


@login_required
@require_http_methods(["GET", "POST"])
def account_settings(request):
    profile, _ = MemberProfile.objects.get_or_create(
        user=request.user, defaults={"bank_name": ""}
    )
    details_form = AccountDetailsForm(
        request.POST if request.method == "POST" and request.POST.get("action") == "details" else None,
        user=request.user,
        profile=profile,
    )
    password_form = PasswordChangeForm(
        request.user,
        request.POST if request.method == "POST" and request.POST.get("action") == "password" else None,
    )
    authenticator_form = AuthenticatorCodeForm()
    disable_form = DisableAuthenticatorForm()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "details":
            details_form = AccountDetailsForm(
                request.POST, user=request.user, profile=profile
            )
            if details_form.is_valid():
                pending_email = details_form.save()
                messages.success(
                    request,
                    "Your account details and email preferences were saved.",
                )
                if pending_email:
                    if _send_email_change_confirmation(request, request.user, profile):
                        messages.info(
                            request,
                            f"Confirm the new address sent to {pending_email}. Your current address remains active until then.",
                        )
                    else:
                        messages.error(
                            request,
                            "Your details were saved, but the email confirmation could not be sent. Check the email settings in Render, then resend it here.",
                        )
                return redirect("finance:account")
        elif action == "password":
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, "Your password was changed.")
                return redirect("finance:account")
        elif action == "begin_authenticator":
            if not profile.totp_enabled:
                profile.totp_secret = _encrypt_totp_secret(pyotp.random_base32())
                profile.save(update_fields=("totp_secret",))
                messages.info(request, "Scan the code, then enter a current code to finish setup.")
            return redirect(f"{reverse('finance:account')}?auth=setup")
        elif action == "resend_email_confirmation":
            if profile.pending_email:
                if _send_email_change_confirmation(request, request.user, profile):
                    messages.success(request, "A new email confirmation link was sent.")
                else:
                    messages.error(
                        request,
                        "The confirmation email could not be sent. Check the email settings in Render.",
                    )
            return redirect("finance:account")
        elif action == "cancel_email_change":
            profile.pending_email = ""
            profile.save(update_fields=("pending_email",))
            messages.success(request, "The pending email change was cancelled.")
            return redirect("finance:account")
        elif action == "verify_authenticator":
            authenticator_form = AuthenticatorCodeForm(request.POST)
            secret = _decrypt_totp_secret(profile)
            if not secret:
                messages.error(request, "Start authenticator setup before verifying a code.")
            elif authenticator_form.is_valid() and pyotp.TOTP(secret).verify(
                authenticator_form.cleaned_data["code"], valid_window=1
            ):
                profile.totp_enabled = True
                profile.save(update_fields=("totp_enabled",))
                messages.success(request, "Authenticator sign-in is now enabled.")
                return redirect("finance:account")
            elif authenticator_form.is_valid():
                authenticator_form.add_error(
                    "code", "That code could not be verified. Try the latest code."
                )
        elif action == "disable_authenticator":
            disable_form = DisableAuthenticatorForm(request.POST)
            if disable_form.is_valid():
                secret = _decrypt_totp_secret(profile)
                if not request.user.check_password(
                    disable_form.cleaned_data["current_password"]
                ):
                    disable_form.add_error("current_password", "Enter your current password.")
                elif not secret or not pyotp.TOTP(secret).verify(
                    disable_form.cleaned_data["code"], valid_window=1
                ):
                    disable_form.add_error("code", "That code could not be verified.")
                else:
                    profile.totp_secret = ""
                    profile.totp_enabled = False
                    profile.save(update_fields=("totp_secret", "totp_enabled"))
                    messages.success(request, "Authenticator sign-in has been disabled.")
                    return redirect("finance:account")

    pending_secret = (
        _decrypt_totp_secret(profile)
        if not profile.totp_enabled and profile.totp_secret
        else ""
    )
    return render(
        request,
        "members/account.html",
        {
            "page_title": "Account",
            "page_subtitle": "Your personal details, sign-in security, and financial emails.",
            "current_month": timezone.localdate().strftime("%B %Y"),
            "profile": profile,
            "details_form": details_form,
            "password_form": password_form,
            "authenticator_form": authenticator_form,
            "disable_form": disable_form,
            "authenticator_setup": bool(pending_secret),
            "authenticator_qr": _authenticator_qr_data(pending_secret, request.user)
            if pending_secret
            else "",
            "authenticator_secret": pending_secret,
            "email_host_configured": bool(
                settings.EMAIL_HOST
                and settings.DEFAULT_FROM_EMAIL
                and "@localhost" not in settings.DEFAULT_FROM_EMAIL
            ),
            "pending_email": profile.pending_email,
        },
    )


@require_http_methods(["GET", "POST"])
def confirm_email_change(request, token):
    try:
        payload = signing.loads(
            token,
            salt=EMAIL_CHANGE_SALT,
            max_age=EMAIL_CHANGE_MAX_AGE,
        )
        user_id = payload["user_id"]
        email = payload["email"]
        if not isinstance(email, str):
            raise signing.BadSignature("Invalid email confirmation data.")
        user = get_user_model().objects.get(pk=user_id)
        profile = user.profile
    except (
        signing.BadSignature,
        signing.SignatureExpired,
        KeyError,
        TypeError,
        ValueError,
        get_user_model().DoesNotExist,
        MemberProfile.DoesNotExist,
    ):
        messages.error(request, "That email confirmation link is invalid or has expired.")
        return redirect("finance:login")

    if profile.pending_email.casefold() != email.casefold():
        messages.error(request, "That email change is no longer pending.")
        return redirect("finance:login")
    if get_user_model().objects.filter(
        Q(email__iexact=email) | Q(username__iexact=email)
    ).exclude(pk=user.pk).exists():
        messages.error(request, "That email address is no longer available.")
        return redirect("finance:login")

    if request.method == "POST":
        old_email = user.email
        user.email = email
        if user.username.casefold() == old_email.casefold():
            user.username = email
        user.save(update_fields=("email", "username"))
        profile.pending_email = ""
        profile.save(update_fields=("pending_email",))
        messages.success(request, "Your Sable email address has been updated.")
        return redirect("finance:account" if request.user.is_authenticated else "finance:login")

    return render(request, "members/email_confirm.html", {"pending_email": email})
