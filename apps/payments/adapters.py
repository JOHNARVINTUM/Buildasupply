import hashlib,hmac,json,os,sys,time,uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from django.conf import settings
class DemoAdapter:
    code="demo"
    def create_payment(self, *, payment, idempotency_key, return_url=""): return {"provider_reference":f"demo-{payment.id.hex[:16]}","attempt_reference":f"att-{uuid.uuid4().hex[:16]}","status":"PENDING","instruction_url":f"/shop/payments/{payment.id}/"}
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


class PesoWayAdapter:
    """Small backend-only client for PesoWay's local simulation API."""
    code = "pesoway"
    webhook_tolerance_seconds = 300

    def _settings(self):
        base_url = os.environ.get("PESOWAY_BASE_URL", "").rstrip("/")
        api_key = os.environ.get("PESOWAY_API_KEY", "")
        if not base_url or not api_key:
            raise ValueError("PesoWay is not configured.")
        return base_url, api_key

    def _request_json(self, *, method, path, payload=None, idempotency_key=""):
        base_url, api_key = self._settings()
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = Request(urljoin(f"{base_url}/", path.lstrip("/")), data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("PesoWay request failed.") from error

    def create_payment(self, *, payment, idempotency_key, return_url=""):
        merchant_reference = payment.provider_merchant_reference or f"buildasupply-order-{payment.master_order_id}"
        response = self._request_json(
            method="POST",
            path="/api/v1/payment-intents/",
            idempotency_key=f"buildasupply-order-{payment.master_order_id}-payment-create",
            payload={
                "amount_centavos": payment.amount_minor,
                "currency": payment.currency,
                "merchant_reference": merchant_reference,
                "description": f"BuildASupply order {payment.master_order.order_number}",
                "return_url": return_url,
            },
        )
        try:
            data = response["data"]
            intent_id = str(data["id"])
            checkout_url = urljoin(f"{self._settings()[0]}/", data["checkout_url"].lstrip("/"))
            if data["amount_centavos"] != payment.amount_minor or data["currency"] != payment.currency or data["merchant_reference"] != merchant_reference:
                raise ValueError("PesoWay response did not match the payment.")
        except (KeyError, TypeError, ValueError):
            raise ValueError("PesoWay returned an invalid payment intent.")
        return {"provider_reference": intent_id, "attempt_reference": intent_id, "status": "PENDING", "instruction_url": checkout_url, "merchant_reference": merchant_reference, "provider_status": data.get("status", "")}

    def retrieve_payment_intent(self, provider_reference):
        response = self._request_json(method="GET", path=f"/api/v1/payment-intents/{provider_reference}/")
        try:
            return response["data"]
        except (KeyError, TypeError):
            raise ValueError("PesoWay returned an invalid payment status.")

    def checkout_url(self, provider_reference):
        base_url, _ = self._settings()
        return urljoin(f"{base_url}/", f"checkout/{provider_reference}/")

    def verify_webhook(self, *, raw_body, headers):
        secret = os.environ.get("PESOWAY_WEBHOOK_SECRET", "")
        event_id = headers.get("X-PesoWay-Event", "")
        timestamp_text = headers.get("X-PesoWay-Timestamp", "")
        signature = headers.get("X-PesoWay-Signature", "")
        if not secret or not event_id or not timestamp_text or not signature.startswith("v1="):
            return None
        try:
            timestamp = int(timestamp_text)
        except (TypeError, ValueError):
            return None
        if abs(time.time() - timestamp) > self.webhook_tolerance_seconds:
            return None
        expected = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("ascii") + raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature[3:], expected):
            return None
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            if payload["id"] != event_id or payload["type"] not in {"payment_intent.created", "payment_intent.succeeded", "payment_intent.canceled"}:
                return None
            return {"event_id": event_id, "event_type": payload["type"], "provider_reference": str(payload["data"]["payment_intent"]), "provider_status": payload["data"]["status"]}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None


ADAPTERS={"demo":DemoAdapter(), "pesoway":PesoWayAdapter()}
def _demo_allowed(): return settings.DEBUG or "test" in sys.argv
def get_adapter(code):
    if code == "demo" and not _demo_allowed(): raise ValueError("Demo payments are unavailable outside development.")
    try:return ADAPTERS[code]
    except KeyError:raise ValueError("Unsupported payment provider.")
