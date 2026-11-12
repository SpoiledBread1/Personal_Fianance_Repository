import logging
import smtplib
from datetime import date

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Sum

from .models import Budget, Transaction

logger = logging.getLogger(__name__)


def update_budget_email_alerts(user, changed_groups, *, allow_send=True):
    profile = getattr(user, "profile", None)
    if profile is None:
        return True

    delivered = True
    for category_id, transaction_date in set(changed_groups):
        if category_id is None:
            continue
        budgets = Budget.objects.filter(
            user=user,
            category_id=category_id,
            period_start__lte=transaction_date,
            period_end__gte=transaction_date,
        )
        for budget in budgets:
            spent = Transaction.objects.filter(
                account__user=user,
                category_id=category_id,
                transaction_type=Transaction.TransactionType.DEBIT,
                transaction_date__range=(budget.period_start, budget.period_end),
            ).aggregate(total=Sum("amount"))["total"] or 0

            if spent < budget.amount:
                if budget.alert_sent:
                    budget.alert_sent = False
                    budget.save(update_fields=("alert_sent",))
                continue
            if budget.alert_sent or not allow_send:
                continue
            if not profile.email_budget_alerts or not user.email:
                continue

            subject = f"Sable budget alert: {budget.category.category_name}"
            body = (
                f"Hello {user.first_name or 'there'},\n\n"
                f"Your {budget.category.category_name} budget has reached or exceeded its limit.\n"
                f"Period: {budget.period_start:%b %d, %Y}–{budget.period_end:%b %d, %Y}\n"
                f"Budget limit: {budget.amount:,.2f}\n"
                f"Current spending: {spent:,.2f}\n\n"
                "Review your budget and transactions in Sable."
            )
            try:
                sent = send_mail(
                    subject,
                    body,
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
            except (OSError, smtplib.SMTPException):
                logger.exception("Could not send budget alert for user %s", user.pk)
                delivered = False
                continue
            if sent != 1:
                logger.error("Budget alert was not accepted for user %s", user.pk)
                delivered = False
                continue
            budget.alert_sent = True
            budget.save(update_fields=("alert_sent",))

    return delivered


def budget_groups(category_id, transaction_date):
    if category_id is None or not isinstance(transaction_date, date):
        return ()
    return ((category_id, transaction_date),)
