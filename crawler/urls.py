from django.urls import path
from .views import CrawlView

urlpatterns = [
    path("crawl/", CrawlView.as_view(), name="crawl-view"),
]
