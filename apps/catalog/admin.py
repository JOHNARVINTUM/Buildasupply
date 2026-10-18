from django.contrib import admin
from .models import Category, Product, ProductImage, ProductPrice
admin.site.register((Category, Product, ProductPrice, ProductImage))
