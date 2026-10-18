from django.template import Context, Template
from django.test import SimpleTestCase


class CurrencyFormattingTests(SimpleTestCase):
    def test_php_formats_centavos_as_pesos(self):
        self.assertEqual(Template("{% load currency %}{{ amount|php }}").render(Context({"amount": 125000})), "₱1,250.00")
