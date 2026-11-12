from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import send_mail
from django.db.models import Sum
from django.utils import timezone

from members.models import MemberProfile, Transaction


class Command(BaseCommand):
    help = "Email opted-in users a summary of the previous calendar month."

    def handle(self, *args, **options):
        today = timezone.localdate()
        this_month = today.replace(day=1)
        previous_month_end = this_month - timedelta(days=1)
        period_start = previous_month_end.replace(day=1)
        users = MemberProfile.objects.filter(
            email_monthly_summary=True,
            user__is_active=True,
        ).select_related("user")
        sent_count = 0

        for profile in users:
            user = profile.user
            if not user.email:
                self.stderr.write(f"Skipped user {user.pk}: no email address.")
                continue
            totals = (
                Transaction.objects.filter(
                    account__user=user,
                    transaction_date__range=(period_start, previous_month_end),
                )
                .values("account__currency", "transaction_type")
                .annotate(total=Sum("amount"))
                .order_by("account__currency", "transaction_type")
            )
            totals_by_currency = {}
            for row in totals:
                currency = row["account__currency"]
                totals_by_currency.setdefault(currency, {"income": 0, "spending": 0})
                label = "income" if row["transaction_type"] == "credit" else "spending"
                totals_by_currency[currency][label] = row["total"]

            lines = [
                f"Hello {user.first_name or 'there'},",
                "",
                f"Here is your Sable financial summary for {period_start:%B %Y}.",
                "",
            ]
            if totals_by_currency:
                for currency, values in totals_by_currency.items():
                    lines.extend(
                        (
                            f"{currency}",
                            f"  Income: {values['income']:,.2f}",
                            f"  Spending: {values['spending']:,.2f}",
                        )
                    )
            else:
                lines.append("No transactions were recorded during this period.")
            lines.extend(("", "Review your accounts and transactions in Sable."))

            sent = send_mail(
                f"Your Sable financial summary for {period_start:%B %Y}",
                "\n".join(lines),
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
            if sent != 1:
                raise CommandError(f"Email delivery failed for user {user.pk}.")
            sent_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Sent {sent_count} monthly summaries for {period_start:%B %Y}."
            )
        )
