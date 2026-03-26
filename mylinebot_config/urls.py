"""
URL configuration for mylinebot project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path

from mylinebot_code import views, liff_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', views.health, name='health'),
    path('callback/', views.callback, name='callback'),
    path('cron/<str:secret>/', views.cron_scraper, name='cron_scraper'),
    path('clear/<str:secret>/', views.clear_db, name='clear_db'),
    path('debug/<str:secret>/', views.debug_scraper, name='debug_scraper'),
    path('users/<str:secret>/', views.api_users, name='api_users'),
    path('targets/<str:secret>/', views.api_targets, name='api_targets'),
    path('dietary-report/<str:secret>/', views.dietary_report_cron, name='dietary_report_cron'),

    # LIFF web editor
    path('liff/editor/', liff_views.liff_editor, name='liff_editor'),
    path('liff/api/entries/', liff_views.api_entries, name='liff_api_entries'),
    path('liff/api/entries/<int:entry_id>/', liff_views.api_entry_detail, name='liff_api_entry_detail'),
]
