from django.urls import path, include

from . import webhooks, _views

app_name = "campaigns"

urlpatterns = [
    #VERSION 2 URLS
    path("", _views.campaign_list_create_api_view, name="campaign-list-create"),
    path("<str:campaign_id>/", _views.campaign_retreive_update_delete_api_view, name="campaign-retrieve-update-delete"),
    path("register/user-registration/", _views.user_registration_view, name="user_registration_view"),
    path("test/test-email/", _views.test_email_view, name="test-email"),
    path("<str:campaign_id>/activate-deactivate/", _views.campaign_activate_deactivate_api_view, name="campaign-activate-deactivate"),
    path("<str:campaign_id>/message/", _views.campaign_message_create_retrieve_api_view, name="campaign-message-create-retreive"),
    path("<str:campaign_id>/message/<str:message_id>/", _views.campaign_message_update_delete_api_view, name="campaign-message-update-delete"),
    path("<str:campaign_id>/audiences/", _views.campaign_audience_list_add_api_view, name="campaign-audience-list-add"),
    path("<str:campaign_id>/audiences/unsubscribe/", _views.campaign_audience_unsubscribe_view, name="campaign-audience-unsubscribe"),
    path("<str:campaign_id>/launch/", _views.campaign_launch_api_view, name="campaign-launch"),
    path("<str:campaign_id>/reports/", include("reports.urls"), name="campaign-run-reports"),
    path("webhooks/tasks/", webhooks.campaign_tasks_webhook, name="campaign-tasks-webhook"),

]

