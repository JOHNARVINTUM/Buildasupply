from decimal import Decimal
from django import template

register = template.Library()

@register.filter
def php(value):
    try:
        return f"₱{Decimal(value) / Decimal('100'):,.2f}"
    except (ArithmeticError, TypeError, ValueError):
        return "₱0.00"
