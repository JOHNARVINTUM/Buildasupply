# Operations

## Reservation expiry

Checkout stock reservations expire after 30 minutes. Run the following command every five minutes from the same environment, virtual environment, and application release as the web process:

```powershell
& .\.venv\Scripts\python.exe manage.py expire_reservations
```

The command is safe to rerun. For each eligible unpaid `PENDING_PAYMENT` order it locks the order and related payment/inventory rows, releases each active expired reservation once, restores available inventory, creates one `RESERVATION_RELEASE` movement per reservation, then marks the order `CANCELLED` with payment status `EXPIRED`.

It skips paid/non-pending orders and orders with an open or investigating payment reconciliation. A later verified payment callback for an expired order continues through the late-payment reconciliation flow; this command never refunds or reallocates stock.

### Dry run

Use dry-run before enabling a new scheduler or when investigating a backlog. It performs no writes and does not call the reservation-release service.

```powershell
& .\.venv\Scripts\python.exe manage.py expire_reservations --dry-run
```

The command prints a JSON summary with:

- `expired_reservations_discovered`
- `candidate_orders`
- `orders_processed`
- `reservations_released`
- `orders_skipped`
- `reconciliation_cases`
- `errors`
- `duration_ms`

An exit code of `0` means all candidate orders completed or were expected skips. A non-zero exit code means one or more individual orders failed; successfully processed orders remain committed and failed orders are safely retryable on the next run. The application logger emits `reservation_expiry_*` events with order IDs and counts only—never payment credentials or customer secrets.

### Local Windows development: Task Scheduler

Create a task that runs whether the user is logged on or not. Set **Start in** to the repository root, and set the program and arguments as follows:

```text
Program/script: C:\Users\John Arvin\Downloads\Buildasupply\.venv\Scripts\python.exe
Arguments: manage.py expire_reservations
Start in: C:\Users\John Arvin\Downloads\Buildasupply
Trigger: Daily, repeat every 5 minutes, indefinitely
```

For local testing, run the dry-run command first. In Task Scheduler, check **History** and the task's **Last Run Result**. A `0x0` result is successful; investigate non-zero values with the application logs and a manual dry run.

### Production Linux: cron

The repository has no configured worker, Celery, Redis, Docker scheduler, or service manager. Use the deployment platform's existing scheduler if it has one. Otherwise, cron is the simplest supported option:

```cron
*/5 * * * * cd /srv/builtasupply && /srv/builtasupply/.venv/bin/python manage.py expire_reservations >> /var/log/builtasupply/reservation-expiry.log 2>&1
```

Run this as the same least-privileged application user that owns the release and has access to its environment variables. Configure log rotation for the output file and alert on non-zero scheduler results or recurring `reservation_expiry_order_failed` logs.

### Production Linux: systemd timer

Use this instead of cron where systemd is standard in the deployment.

`/etc/systemd/system/builtasupply-reservation-expiry.service`:

```ini
[Unit]
Description=BUILTASUPPLY reservation expiry

[Service]
Type=oneshot
User=builtasupply
WorkingDirectory=/srv/builtasupply
EnvironmentFile=/etc/builtasupply/environment
ExecStart=/srv/builtasupply/.venv/bin/python manage.py expire_reservations
```

`/etc/systemd/system/builtasupply-reservation-expiry.timer`:

```ini
[Unit]
Description=Run BUILTASUPPLY reservation expiry every five minutes

[Timer]
OnCalendar=*:0/5
Persistent=true
Unit=builtasupply-reservation-expiry.service

[Install]
WantedBy=timers.target
```

Enable and verify it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now builtasupply-reservation-expiry.timer
systemctl list-timers builtasupply-reservation-expiry.timer
journalctl -u builtasupply-reservation-expiry.service -n 100
```

### Failure recovery and verification

1. Run `manage.py expire_reservations --dry-run` and inspect its counts.
2. Run the command normally once the scheduler/environment is corrected.
3. Re-run it safely; released reservations are no longer active and will not produce duplicate movements.
4. Investigate a remaining expired active reservation with Django shell or read-only SQL, including its master order status and any `PaymentReconciliation` record. Do not manually adjust inventory as the first response.
5. For an order with an open reconciliation, use the approved payment reconciliation process; do not force this command to expire or fulfill it.

PostgreSQL is the production target and is needed to validate true row-lock contention. SQLite development tests validate state transitions and idempotency but cannot prove PostgreSQL concurrency behavior.
