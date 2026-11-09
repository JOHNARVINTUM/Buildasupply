from django.db import transaction
from django.utils import timezone
from .models import DomainEvent,Notification,NotificationDelivery,NotificationPreference
TEMPLATES={
"payment.succeeded":("Payment confirmed","Payment confirmed for order {order_number}.","payment"),"payment.failed":("Payment failed","Payment failed for order {order_number}; its payment hold was released.","payment"),
"order.created":("Order created","Order {order_number} was created. Select a payment method to continue.","order"),"supplier.order_assigned":("New order assigned","A new supplier order is awaiting action for order {order_number}.","order"),
"cod.selected":("Cash on delivery selected","Cash on delivery was selected for order {order_number}. Payment is collected upon delivery.","order"),"cod.supplier_accepted":("Supplier accepted order","{supplier_name} accepted its part of order {order_number}.","order"),
"order.preparing":("Order is being prepared","{supplier_name} is preparing its part of order {order_number}.","order"),"order.ready":("Order ready for delivery","{supplier_name} has prepared its part of order {order_number} for delivery.","order"),"order.dispatched":("Order dispatched","{supplier_name} dispatched its part of order {order_number}.","order"),"order.delivered":("Order delivered","{supplier_name} marked its part of order {order_number} as delivered.","order"),
"cod.collection_recorded":("Cash collection recorded","Cash collection was recorded for {supplier_name}'s part of order {order_number}.","order"),"cod.receipt_confirmed":("Receipt confirmed","Customer receipt was confirmed for order {order_number}.","order"),"cod.cancelled":("COD order cancelled","Order {order_number} was cancelled before supplier acceptance.","order"),
"cod.return_verified":("Return verified","A returned delivery was verified for order {order_number}.","order"),
"cod.failed_delivery":("COD failed delivery requires review","A failed delivery was reported for order {order_number}.","operations"),"cod.collection_disputed":("COD collection dispute requires review","A collection dispute was reported for order {order_number}.","operations"),"settlement.released":("Supplier funds available","Settlement for order {order_number} is now available.","finance"),"refund.approved":("Refund approved","Your refund for order {order_number} was approved.","payment"),"refund.processing":("Refund processing","Your refund for order {order_number} is processing.","payment"),"refund.completed":("Refund completed","Your refund for order {order_number} was completed.","payment"),"refund.failed":("Refund failed","Your refund for order {order_number} could not be completed.","payment"),"refund.reversal_held":("Refund reversal held","A refund reversal requires finance review for order {order_number}.","finance"),"payment.reconciliation_required":("Payment reconciliation required","A payment for order {order_number} requires administrative review.","operations"),"payout.completed":("Payout completed","Your payout has been completed.","payout")}

def supplier_recipient_ids(supplier):
    return [str(row.user_id) for row in supplier.staff_memberships.filter(status="ACTIVE").exclude(user__account_status__in=["SUSPENDED","DEACTIVATED"])]

def superadmin_recipient_ids():
    from apps.accounts.models import User
    return [str(value) for value in User.objects.filter(primary_role="SUPERADMIN",account_status="ACTIVE").values_list("id",flat=True)]
def emit(event_type,obj,payload):
    event=DomainEvent.objects.create(event_type=event_type,object_type=obj._meta.label,object_id=obj.pk,payload=payload)
    transaction.on_commit(lambda: process(event.id));return event
def process(event_id):
    event=DomainEvent.objects.filter(pk=event_id,status="PENDING").first()
    if not event:return
    try:
        title,body,category=TEMPLATES.get(event.event_type,(event.event_type,"An operational update is available.","system"));recipients=event.payload.get("recipient_ids",[])
        for user_id in recipients:
            preference=event.payload.get("respect_preferences",True)
            if preference and NotificationPreference.objects.filter(recipient_id=user_id,category=category,in_app=False).exists():continue
            note,_=Notification.objects.get_or_create(recipient_id=user_id,event=event,defaults={"event_type":event.event_type,"title":title,"body":body.format(**event.payload),"priority":event.payload.get("priority","NORMAL"),"related_type":event.object_type,"related_id":event.object_id,"link":event.payload.get("link","")});NotificationDelivery.objects.get_or_create(notification=note,channel="IN_APP",defaults={"status":"DELIVERED","sent_at":timezone.now()})
        event.status="PROCESSED";event.processed_at=timezone.now();event.save(update_fields=["status","processed_at"])
    except Exception as exc:event.status="FAILED";event.retry_count+=1;event.last_error=str(exc)[:500];event.save(update_fields=["status","retry_count","last_error"])
