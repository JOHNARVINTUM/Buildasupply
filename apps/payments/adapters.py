import hashlib,hmac,json,os,sys,uuid
from django.conf import settings
class DemoAdapter:
    code="demo"
    def create_payment(self, *, payment, idempotency_key): return {"provider_reference":f"demo-{payment.id.hex[:16]}","attempt_reference":f"att-{uuid.uuid4().hex[:16]}","status":"PENDING","instruction_url":f"/shop/payments/{payment.id}/"}
    def verify_webhook(self, *, raw_body, headers):
        secret=os.environ.get("BUILTASUPPLY_DEMO_WEBHOOK_SECRET")
        if not _demo_allowed() or not secret: return None
        signature=headers.get("X-Builtasupply-Signature",""); expected=hmac.new(secret.encode(),raw_body,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature,expected): return None
        try:
            payload=json.loads(raw_body.decode()); status={"SUCCESS":"PAID","FAILED":"FAILED","EXPIRED":"FAILED"}.get(payload["status"],"PENDING")
            result={"event_id":payload["event_id"],"provider_reference":payload["provider_reference"],"merchant_reference":payload["merchant_reference"],"status":status,"event_type":payload["status"]}
            if status == "PAID":
                amount=payload["amount_minor"];currency=payload["currency"]
                if isinstance(amount,bool) or not isinstance(amount,int) or amount<=0 or not isinstance(currency,str) or len(currency)!=3: return None
                result.update({"amount_minor":amount,"currency":currency.upper()})
            return result
        except (KeyError, TypeError, ValueError, json.JSONDecodeError): return None
    def create_refund(self, *, refund, idempotency_key):
        if not _demo_allowed(): raise ValueError("Demo refunds are unavailable outside development.")
        return {"provider_reference":f"demo-refund-{refund.id.hex[:16]}","status":"PENDING","response":{"mode":"demo","idempotency_key":idempotency_key}}
    def verify_refund_webhook(self, *, raw_body, headers):
        secret=os.environ.get("BUILTASUPPLY_DEMO_WEBHOOK_SECRET")
        if not _demo_allowed() or not secret: return None
        signature=headers.get("X-Builtasupply-Signature",""); expected=hmac.new(secret.encode(),raw_body,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature,expected): return None
        payload=json.loads(raw_body.decode())
        if payload.get("kind") != "REFUND": return None
        return {"event_id":payload["event_id"],"provider_reference":payload["provider_reference"],"status":{"SUCCESS":"COMPLETED","FAILED":"FAILED"}.get(payload["status"],"PENDING"),"event_type":payload["status"],"amount_minor":payload.get("amount_minor"),"currency":payload.get("currency")}
ADAPTERS={"demo":DemoAdapter()}
def _demo_allowed(): return settings.DEBUG or "test" in sys.argv
def get_adapter(code):
    if code == "demo" and not _demo_allowed(): raise ValueError("Demo payments are unavailable outside development.")
    try:return ADAPTERS[code]
    except KeyError:raise ValueError("Unsupported payment provider.")
