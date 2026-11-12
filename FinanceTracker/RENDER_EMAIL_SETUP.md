# Email notifications on Render

The account page lets each user opt in to monthly financial summaries and budget-limit alerts. Set these environment variables on the Render web service using an SMTP provider and a verified sender address:

- `EMAIL_HOST`
- `EMAIL_PORT` (usually `587`)
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS` (`True` for STARTTLS)
- `DEFAULT_FROM_EMAIL` (a sender address verified with your provider)

The SMTP credentials are deployment secrets and must not be committed to the repository. `render.yaml` marks credentials and the sender address as values to enter in the Render dashboard.

Budget alerts are sent when a recorded transaction brings a budget to or above its limit. Monthly summaries cover the previous calendar month. To send them automatically, create a Render Cron Job that uses the same repository, Python version, database, and email environment variables as the web service. Set its command to:

```text
python FinanceTracker/manage.py send_monthly_summaries
```

Schedule it for the first day of each month. The app does not create a paid cron service automatically, so enabling scheduled emails does not change the existing Render plan.

Authenticator-app secrets are encrypted using a key derived from Django's `SECRET_KEY`. Keep the Render `SECRET_KEY` stable when deploying; rotating it without migrating/re-enrolling authenticators makes existing authenticator secrets unreadable. The existing Render pre-deploy migration command applies the account preference and security fields.
