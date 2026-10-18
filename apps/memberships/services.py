def get_active_membership(customer):
    assignment=customer.membership_assignments.select_related("tier").filter(is_active=True).first()
    return {"tier":assignment.tier.code,"name":assignment.tier.name} if assignment else None
def get_applicable_benefits(customer, product):
    assignment=customer.membership_assignments.select_related("tier").filter(is_active=True).first()
    if not assignment:return []
    return [{"type":benefit.benefit_type,"value":benefit.value} for benefit in assignment.tier.benefits.filter(is_active=True)]
