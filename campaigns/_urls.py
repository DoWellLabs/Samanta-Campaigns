from django.urls import path, include

from . import webhooks, _views

app_name = "campaignsV2"

urlpatterns = [
    # VERSION 2 URLS
    path("", _views.campaign_list_create_api_view, name="campaign-list-create"),
    path(
        "<str:campaign_id>/",
        _views.campaign_retreive_update_delete_api_view,
        name="campaign-retrieve-update-delete",
    ),
    path(
        "register/user-registration/",
        _views.user_registration_view,
        name="user_registration_view",
    ),
    path("get/link-data/", _views.get_link_data_view, name="get-link-data"),
    path(
        "submit/contact-us-form/",
        _views.submit_contact_us_view,
        name="submit-contact-us-form",
    ),
    path("test/test-email/", _views.test_email_view, name="test-email"),
    path("test/test-sms/", _views.test_sms_view, name="test-sms"),
    path("test/run/",_views.test_run,name="test-run"),
    path("contact/contact_us/", _views.contact_us, name="contact_us"),
    path("scrape/contact_us/", _views.scrape_contact_us, name="scrape_contact_us"),
    path("upload/upload_data/", _views.data_upload, name="data_upload"),
    path(
        "<str:campaign_id>/activate-deactivate/",
        _views.campaign_activate_deactivate_api_view,
        name="campaign-activate-deactivate",
    ),
    path(
        "<str:campaign_id>/message/",
        _views.campaign_message_create_retrieve_api_view,
        name="campaign-message-create-retreive",
    ),
    path(
        "<str:campaign_id>/message/<str:message_id>/",
        _views.campaign_message_update_delete_api_view,
        name="campaign-message-update-delete",
    ),
    path(
        "<str:campaign_id>/audiences/",
        _views.campaign_audience_list_add_api_view,
        name="campaign-audience-list-add",
    ),
    path(
        "<str:campaign_id>/audiences/unsubscribe/",
        _views.campaign_audience_unsubscribe_view,
        name="campaign-audience-unsubscribe",
    ),
    path(
        "<str:campaign_id>/launch/",
        _views.campaign_launch_api_view,
        name="campaign-launch",
    ),
    path(
        "<str:campaign_id>/reports/",
        include("reports.urls"),
        name="campaign-run-reports",
    ),
    path(
        "webhooks/tasks/",
        webhooks.campaign_tasks_webhook,
        name="campaign-tasks-webhook",
    ),
]
