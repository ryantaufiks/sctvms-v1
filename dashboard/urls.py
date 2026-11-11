from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.index, name='index'),
    path('door-control/', views.door_control_api, name='door_control_api'),
    path('gate-control/', views.gate_control_api, name='gate_control_api'),
    path('occurrence/add/', views.add_occurrence, name='add_occurrence'),
    path('occurrence/officers/', views.get_recent_officers_api, name='get_recent_officers_api'),
]