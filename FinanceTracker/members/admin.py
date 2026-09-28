from django.contrib import admin
from .models import AccountType, Account, Category, Payee, Tag, Transaction, Budget

admin.site.register([
    AccountType,
    Account,
    Category,
    Payee,
    Tag,
    Transaction,
    Budget,
])

#ILikeTurtles