import secrets

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import MasterOrder


class RealEstateOrderDeliveryStatusView(APIView):
    """Expose only a linked order's delivery state to RealEstateDemo.

    This intentionally returns no buyer, item, payment, supplier, or address data.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, order_number):
        expected_token = settings.REALESTATE_STATUS_API_TOKEN
        supplied_token = request.headers.get("X-RealEstate-Status-Token", "")
        if not expected_token or not secrets.compare_digest(supplied_token, expected_token):
            return Response({"detail": "Not found."}, status=404)

        order = (
            MasterOrder.objects.filter(order_number=order_number)
            .prefetch_related("supplier_orders__delivery")
            .first()
        )
        if not order:
            return Response({"detail": "Not found."}, status=404)

        supplier_orders = list(order.supplier_orders.all())
        delivery_states = [getattr(supplier_order.delivery, "status", "PENDING") for supplier_order in supplier_orders]
        if supplier_orders and all(status == "DELIVERED" for status in delivery_states):
            delivery_status = "DELIVERED"
        elif "SHIPPED" in delivery_states:
            delivery_status = "SHIPPED"
        elif any(status in {"PREPARING", "READY_FOR_DELIVERY"} for status in [item.status for item in supplier_orders]):
            delivery_status = "PREPARING"
        elif any(status == "CANCELLED" for status in [item.status for item in supplier_orders]):
            delivery_status = "CANCELLED"
        else:
            delivery_status = "PENDING"

        return Response({"order_number": order.order_number, "delivery_status": delivery_status})
