from django.urls import path
from . import views

app_name = 'residents'

urlpatterns = [
    path('management/', views.management, name='management'),
]