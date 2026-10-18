from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.orders.models import MasterOrder
from .models import Payment
from .services import PaymentFailure, initiate_payment, process_webhook
class OrderPaymentView(APIView):
    def post(self,request,order_id):
        if not hasattr(request.user,"customer_profile"):return Response({"detail":"Customer access required."},status=403)
        order=MasterOrder.objects.filter(pk=order_id,customer=request.user.customer_profile).first()
        if not order:return Response({"detail":"Not found."},status=404)
        try:return Response(initiate_payment(customer=request.user.customer_profile,order=order,provider_code=request.data.get("provider","demo"),method_category=request.data.get("method_category","EWALLET"),idempotency_key=request.headers.get("Idempotency-Key")),status=201)
        except (PaymentFailure,ValueError) as exc:return Response(getattr(exc,"message_dict",{"detail":str(exc)}),status=400)
class PaymentDetailView(APIView):
    def get(self,request,pk):
        payment=Payment.objects.select_related("master_order").filter(pk=pk,master_order__customer=getattr(request.user,"customer_profile",None)).first()
        if not payment:return Response({"detail":"Not found."},status=404)
        return Response({"id":str(payment.id),"order_number":payment.master_order.order_number,"amount_minor":payment.amount_minor,"currency":payment.currency,"status":payment.status})
class PaymentWebhookView(APIView):
    authentication_classes=[];permission_classes=[]
    def post(self,request,provider):
        try:return Response(process_webhook(provider_code=provider,raw_body=request.body,headers=request.headers))
        except PaymentFailure as exc:return Response(exc.message_dict,status=400)
        except ValueError:return Response({"detail":"Malformed webhook."},status=400)
