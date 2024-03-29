from django.urls import path, include

from . import views, webhooks

app_name = "campaigns"

urlpatterns = [
    path("", views.campaign_list_create_api_view, name="campaign-list-create"),
    path("<str:campaign_id>/", views.campaign_retreive_update_delete_api_view, name="campaign-retrieve-update-delete"),
    path("<str:campaign_id>/activate-deactivate/", views.campaign_activate_deactivate_api_view, name="campaign-activate-deactivate"),
    path("<str:campaign_id>/message/", views.campaign_message_create_retrieve_api_view, name="campaign-message-create-retreive"),
    path("<str:campaign_id>/message/<str:message_id>/", views.campaign_message_update_delete_api_view, name="campaign-message-update-delete"),
    path("<str:campaign_id>/audiences/", views.campaign_audience_list_add_api_view, name="campaign-audience-list-add"),
    path("<str:campaign_id>/audiences/unsubscribe/", views.campaign_audience_unsubscribe_view, name="campaign-audience-unsubscribe"),
    path("<str:campaign_id>/launch/", views.campaign_launch_api_view, name="campaign-launch"),
    path("<str:campaign_id>/reports/", include("reports.urls"), name="campaign-run-reports"),
    path("webhooks/tasks/", webhooks.campaign_tasks_webhook, name="campaign-tasks-webhook"),
]