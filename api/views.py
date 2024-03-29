from django.conf import settings
from rest_framework import exceptions, views, status, response
from django.core.exceptions import ValidationError as DjangoValidationError


from . import utils
from .dowell.user import DowellUser
from .dowell.exceptions import UserNotFound
from .objects.exceptions import DoesNotExist, MultipleObjectsReturned
from campaigns.dbobjects import Campaign, CampaignList


class SamanthaCampaignsAPIView(views.APIView):
    """
    Handles all Samantha Campaigns API requests.

    Catches all exceptions and returns a error response
    in a consistent format.
    """

    def handle_exception(self, exc):
        """
        Handle all exceptions and return a consistent error response
        """
        if isinstance(exc, UserNotFound):
            exc = exceptions.NotFound(exc)

        elif isinstance(exc, (DjangoValidationError, exceptions.ValidationError)):
            try:
                exc = exc.message_dict
            except:
                exc = {
                    "detail": exc.args[0] if exc.args else "Validation error. Invalid data."
                }
            exc = exceptions.ValidationError(exc)

        elif isinstance(exc, DoesNotExist):
            exc = exceptions.NotFound(exc)

        elif isinstance(exc, MultipleObjectsReturned):
            exc = exceptions.ValidationError(exc)

        return super().handle_exception(exc)


class AudienceListSortAPIView(SamanthaCampaignsAPIView):
    """Audiences List Sort API View"""

    def post(self, request, *args, **kwargs):
        """
        Sort audience emails by validity and return the result

        Request Body Format:
        ```
        {
            "emails": []
        }
        ```
        """
        workspace_id = request.query_params.get("workspace_id", None)
        data = request.data
        if not isinstance(data, dict):
            raise exceptions.NotAcceptable("Request body must be a dictionary.")
        emails = data.get("emails", None)
        if not emails:
            raise exceptions.NotAcceptable("Emails must be provided.")
        
        user = DowellUser(workspace_id=workspace_id)
        valid_emails, invalid_emails = utils.sort_emails_by_validity(emails, user=user)

        return response.Response(
            data={
                "valid_emails": valid_emails,
                "invalid_emails": invalid_emails,
            }, 
            status=status.HTTP_200_OK
        )


    def get(self, request, *args, **kwargs):
        """
        Get all campaign audiences added by the user
        """
        workspace_id = request.query_params.get("workspace_id", None)
        user = DowellUser(workspace_id=workspace_id)
        campaign_list: CampaignList = Campaign.manager.filter(
            creator_id=workspace_id, 
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id
        )

        emails = []
        phonenumbers = []
        if campaign_list:
            for values in campaign_list.filter(broadcast_type__iexact="email").values_list("audiences"):
                audiences = values[0]
                values_list = audiences.values_list("email")
                emails.extend([ values[0] for values in values_list ])
            for values in campaign_list.filter(broadcast_type__iexact="sms").values_list("audiences"):
                audiences = values[0]
                values_list = audiences.values_list("phonenumber")
                phonenumbers.extend([ values[0] for values in values_list ])
        
        return response.Response(
            data={
                "emails": set(emails),
                "phonenumbers": set(phonenumbers),
            }, 
            status=status.HTTP_200_OK
        )



audience_list_sort_api_view = AudienceListSortAPIView.as_view()
