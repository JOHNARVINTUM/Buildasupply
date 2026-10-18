from django.db import transaction
from django.utils import timezone
from .models import DomainEvent,Notification,NotificationDelivery
TEMPLATES={"payment.succeeded":("Payment confirmed","Payment confirmed for order {order_number}.","payment"),"supplier.approved":("Supplier approved","Your supplier account has been approved.","supplier"),"payout.completed":("Payout completed","Your payout has been completed.","payout")}
def emit(event_type,obj,payload):
    event=DomainEvent.objects.create(event_type=event_type,object_type=obj._meta.label,object_id=obj.pk,payload=payload)
    transaction.on_commit(lambda: process(event.id));return event
def process(event_id):
    event=DomainEvent.objects.filter(pk=event_id,status="PENDING").first()
    if not event:return
    try:
        title,body,category=TEMPLATES.get(event.event_type,(event.event_type,"An operational update is available.","system"));recipients=event.payload.get("recipient_ids",[])
        for user_id in recipients:
            note,_=Notification.objects.get_or_create(recipient_id=user_id,event=event,defaults={"event_type":event.event_type,"title":title,"body":body.format(**event.payload),"priority":event.payload.get("priority","NORMAL"),"related_type":event.object_type,"related_id":event.object_id,"link":event.payload.get("link","")});NotificationDelivery.objects.get_or_create(notification=note,channel="IN_APP",defaults={"status":"DELIVERED","sent_at":timezone.now()})
        event.status="PROCESSED";event.processed_at=timezone.now();event.save(update_fields=["status","processed_at"])
    except Exception as exc:event.status="FAILED";event.retry_count+=1;event.last_error=str(exc)[:500];event.save(update_fields=["status","retry_count","last_error"])
