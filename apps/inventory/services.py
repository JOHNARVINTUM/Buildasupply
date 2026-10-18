from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from apps.audit.services import log_action
from .models import Inventory, InventoryMovement
@transaction.atomic
def record_movement(*, inventory_id, actor, movement_type, quantity_delta, reason):
    if movement_type not in {"RESTOCK","ADJUSTMENT","CORRECTION","DAMAGE","RETURN"}: raise ValidationError("Unsupported manual movement type.")
    if not reason or not reason.strip(): raise ValidationError("A reason is required.")
    if not quantity_delta: raise ValidationError("Quantity must not be zero.")
    inventory=Inventory.objects.select_for_update().select_related("product__supplier").get(pk=inventory_id)
    if inventory.status == "DISABLED": raise ValidationError("Disabled inventory cannot be changed.")
    quantity=inventory.available_quantity + quantity_delta
    if quantity < 0: raise ValidationError("Stock cannot become negative.")
    inventory.available_quantity=quantity; inventory.status="ACTIVE" if quantity else "OUT_OF_STOCK"; inventory.save(update_fields=["available_quantity","status","updated_at"])
    movement=InventoryMovement.objects.create(inventory=inventory, movement_type=movement_type, quantity_delta=quantity_delta, reason=reason.strip(), actor=actor)
    log_action(actor=actor, action=f"INVENTORY_{movement_type}", target=inventory, after={"available_quantity":quantity, "movement_id":str(movement.id)})
    return movement
