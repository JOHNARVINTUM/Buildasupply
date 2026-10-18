from django.contrib import admin
from .models import MembershipAssignment, MembershipBenefit, MembershipTier
admin.site.register((MembershipTier, MembershipBenefit, MembershipAssignment))
