"""
URL configuration for samantha_campaigns project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
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
from django.urls import path, include

from . import views


urlpatterns = [
    path('samanta-campaigns/', views.health_check_api_view, name="health-check"),
    path('samanta-campaigns/admin/', admin.site.urls),
    path("samanta-campaigns/api/v1/", include("api.urls"), name="api"),
    path("samanta-campaigns/scrape", views.request_task_run, name="scrape-task" )
]
