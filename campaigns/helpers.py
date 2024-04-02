from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .utils import (
    construct_dowell_email_template, 
    crawl_url_for_emails_and_phonenumbers,
    fetch_email, 
    generate_random_string,
    check_campaign_creator_has_sufficient_credits_to_run_campaign_once
)
from api.database import SamanthaCampaignsDB
from samantha_campaigns.settings import PROJECT_API_KEY
from api.dowell.datacube import DowellDatacube
import math
from api.objects.signals import ObjectSignal
from api.validators import (
    validate_url, validate_not_blank, 
    validate_email_or_phone_number,
    is_email, is_phonenumber,
    MinMaxLengthValidator
)
from api.dowell.user import DowellUser
from .objectlists import CampaignAudienceLeadsLinkList


# CAMPAIGN SIGNALS
# ----------------------------------------------------
campaign_started_running = ObjectSignal("campaign_started_running", use_caching=True) 
# This signal is sent when a campaign starts running
# kwargs: instance, started_at
# ----------------------------------------------------
campaign_stopped_running = ObjectSignal("campaign_stopped_running", use_caching=True) 
# This signal is sent when a campaign stops running, whether it ran successfully or not.
# kwargs: instance, stopped_at, exception
# ----------------------------------------------------
campaign_launched = ObjectSignal("campaign_launched", use_caching=True) 
# This signal is sent when a campaign is launched
# kwargs: instance, launched_at
# ----------------------------------------------------
campaign_activated = ObjectSignal("campaign_activated", use_caching=True) 
# This signal is sent when a campaign is activated
# kwargs: instance
# ----------------------------------------------------
campaign_deactivated = ObjectSignal("campaign_deactivated", use_caching=True) 
# This signal is sent when a campaign is deactivated
# kwargs: instance
# ----------------------------------------------------

# alias to reduce repetition of long name
min_max = MinMaxLengthValidator


def CustomResponse(success=True, message=None, response=None, status_code=None):
    """
    Create a custom response.
    :param success: Whether the operation was successful or not.
    :param message: Any message associated with the response.
    :param data: Data to be included in the response.
    :param status_code: HTTP status code for the response.
    :return: Response object.
    """
    response_data = {"success": success}
    if message is not None:
        response_data["message"] = message
    if response is not None:
        response_data["response"] = response

    return Response(response_data, status=status_code) if status_code else Response(response_data)



def handle_error(self, request): 
        """
        Handle invalid request type.

        This method is called when the requested type is not recognized or supported.

        :param request: The HTTP request object.
        :type request: HttpRequest

        :return: Response indicating failure due to an invalid request type.
        :rtype: Response
        """
        return Response({
            "success": False,
            "message": "Invalid request type"
        }, status=status.HTTP_400_BAD_REQUEST)

class CampaignHelper:
    def __init__(self, workspace_id):
        self.workspace_id = workspace_id
        self.dowell_api_key = PROJECT_API_KEY  # Assuming PROJECT_API_KEY is defined elsewhere
        self.leads_links = CampaignAudienceLeadsLinkList(object_class="campaigns.dbobjects.CampaignAudienceLeadsLink")

    def get_campaign(self, campaign_id):
        collection_name = f"{self.workspace_id}_samantha_campaign"
        dowell_datacube = DowellDatacube(db_name=SamanthaCampaignsDB.name, dowell_api_key=self.dowell_api_key)
        campaign_list = dowell_datacube.fetch(
            _from=collection_name,
            filters={"_id": campaign_id}
        )
        return campaign_list

    def get_message(self, campaign_id):
        campaign_list = self.get_campaign(campaign_id)
        if campaign_list and isinstance(campaign_list, list) and "message" in campaign_list[0]:
            return campaign_list[0]["message"]
        else:
            return None

    def has_launched(self, campaign_id):
        campaign_list = self.get_campaign(campaign_id)
        if campaign_list and isinstance(campaign_list, list) and "launched_at" in campaign_list[0]:
            launched_at = campaign_list[0]["launched_at"]
            return bool(launched_at)

    def is_launchable(self, campaign_id):
        campaign_list = self.get_campaign(campaign_id)
        broadcast_type = campaign_list[0]["broadcast_type"]

        ans = not self.has_launched(campaign_id)
        if not ans:
            return ans, "Campaign has already been launched", 100

        percentage_ready = 0.000
        ans = self.get_message(campaign_id) is not None
        if not ans:
            return ans, "Campaign has no message", math.ceil(percentage_ready)
        percentage_ready += 25.000
        service_id = settings.DOWELL_MAIL_SERVICE_ID if broadcast_type == "EMAIL" else settings.DOWELL_SMS_SERVICE_ID
        campaign_creator = self.creator()
        ans = campaign_creator.check_service_active(service_id)
        service = campaign_creator.get_service(service_id)
        if not ans:
            return ans, f"DowellService '{service}' is not active.", math.ceil(percentage_ready)
        percentage_ready += 25.000
        # lead_links = campaign_list[0].get("lead_links", [])
        #todo check how crawling is done
        if not self.leads_links.uncrawled().empty:
             return False, "Some leads links have not been crawled", math.ceil(percentage_ready)
        percentage_ready += 25.000
        audiences = campaign_list[0].get("audiences", [])
        no_of_audiences = len(audiences)
        ans = check_campaign_creator_has_sufficient_credits_to_run_campaign_once(broadcast_type,no_of_audiences,campaign_creator)
        if not ans:
            return ans, "You do not have sufficient credits to run this campaign. Please top up.", math.ceil(percentage_ready)
        percentage_ready += 25.000

        return ans, "Campaign can be launched", math.ceil(percentage_ready)

    def creator(self):
        return DowellUser(workspace_id=self.workspace_id)
