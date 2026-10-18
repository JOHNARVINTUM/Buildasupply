from django.core.exceptions import ValidationError
from django.db import transaction
from apps.audit.services import log_action
from apps.core.models import BusinessConfiguration
@transaction.atomic
def set_configuration(*,actor,key,version,value,effective_from,effective_to=None,activate=False):
    if actor.primary_role!="SUPERADMIN":raise ValidationError("Superadmin required.")
    if effective_to and effective_to<=effective_from:raise ValidationError("Effective end must follow start.")
    if not isinstance(value,dict):raise ValidationError("Configuration must be structured data.")
    if activate:BusinessConfiguration.objects.filter(key=key,is_active=True).update(is_active=False)
    config=BusinessConfiguration.objects.create(key=key,version=version,value=value,is_active=activate,effective_from=effective_from,effective_to=effective_to,updated_by=actor)
    log_action(actor=actor,action="CONFIGURATION_CREATED",target=config,after={"key":key,"version":version,"active":activate});return config
