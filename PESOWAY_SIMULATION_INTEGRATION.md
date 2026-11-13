# PesoWay simulation integration

BUILTASUPPLY is a merchant client of the local PesoWay prototype. PesoWay is a simulation only: it does not move money and is not a GCash, Maya, card, QR Ph, PayMongo, or bank integration.

## Local configuration

The ignored `.env` file is loaded automatically for local development. Deployed environment variables take precedence over its values:

```powershell
$env:PESOWAY_BASE_URL = "http://localhost:8000"
$env:PESOWAY_API_KEY = "pw_replace_with_scoped_key"
$env:PESOWAY_WEBHOOK_SECRET = "whsec_replace_with_endpoint_secret"
$env:DJANGO_CSRF_TRUSTED_ORIGINS = "https://your-ngrok-address.ngrok-free.dev"
```

Run PesoWay and BUILTASUPPLY on different local ports. If PesoWay uses `http://localhost:8000`, start BUILTASUPPLY on port `8001`:

```powershell
& .\.venv\Scripts\python.exe manage.py runserver 8001
```

PesoWay intentionally rejects loopback webhook URLs. For local testing, expose port `8001` through a temporary HTTPS tunnel, then register its public URL ending in `/webhooks/pesoway/`. The production equivalent must also be a public HTTPS URL.

## Test flow

1. Create a customer order in BUILTASUPPLY and choose **Pay with PesoWay**.
2. Complete a simulated method at PesoWay hosted checkout.
3. PesoWay redirects the customer to `/payments/pesoway/complete/`; this page never confirms payment itself.
4. Run PesoWay's webhook delivery command. BUILTASUPPLY validates its signed raw payload, timestamp, event ID, provider intent, merchant reference, amount, and currency.
5. Refresh the payment status page. Only a verified `succeeded` intent consumes inventory and moves the order to processing.

No API keys or webhook secrets are stored in database records, templates, logs, or source control.
