# Operational tasks

Run reservation cleanup every five minutes in the deployment scheduler:

```powershell
& .\.venv\Scripts\python.exe manage.py expire_reservations
```

The command releases only expired reservations for unpaid orders, restores inventory, and cancels those orders. It is safe to run repeatedly.
