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
import requests
from django.core.exceptions import ValidationError


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


class SendEmail():
    def sendmail(self, workspace_id):
        user = DowellUser(workspace_id=workspace_id)
        subject = "Crawling lead links done"
        body_message = (
            "Dear User,\n\n"
            "We're pleased to inform you that the lead links have been successfully crawled. "
            "You can now return to the application to launch your campaigns with confidence. "
            "This significant milestone ensures that your campaigns are built upon the latest and most accurate data, "
            "empowering you to make informed decisions and drive impactful results. "
            "We appreciate your patience throughout this process and look forward to seeing the positive outcomes of your campaigns. "
            "Should you have any questions or require further assistance, please don't hesitate to reach out to our support team. "
            "Thank you for choosing our platform.\n\n"
        )
        toemail = user.email
        fromemail = settings.PROJECT_EMAIL
        toname = user.username
        fromname = settings.PROJECT_NAME
        res = self.send_mail(
            subject=subject,
            body=self.construct_dowell_email_template(subject=subject, body=body_message),
            sender_address=fromemail,
            recipient_address=toemail,
            sender_name=fromname,
            recipient_name=toname
        )
        print(res)
        return res

    def send_mail(
        subject: str, 
        body: str, 
        sender_address: str, 
        recipient_address: str, 
        sender_name: str,
        recipient_name: str, 
        ):
        """
        Sends mail using Dowell Email API.

        #### Private method. Use responsibly.
        """
        for address in (recipient_address, sender_address):
            if not is_email(address):
                raise ValidationError(f"{address} is not a valid email address!")
        if not body:
            raise ValueError("body of mail cannot be empty")
        if not subject:
            raise ValueError("subject of mail cannot be empty")
        if not sender_name:
            raise ValueError("sender_name must be provided")
        if not recipient_name:
            raise ValueError("recipient_name must be provided")
        
        response = requests.post(
            url=settings.DOWELL_MAIL_URL,
            data={
                "toname": recipient_name,
                "toemail": recipient_address,
                "fromname": sender_name,
                "fromemail": sender_address,
                "subject": subject,
                "email_content": body
            },
        )
        if response.status_code != 200:
            response.raise_for_status()
        if not response.json()["success"]:
            raise Exception(response.json()["message"])
        return None
    def construct_dowell_email_template(
        self,
        subject: str,
        body: str,
    ):
        """
        Convert a text to an samantha campaigns email template

        :param subject: The subject of the email
        :param body: The body of the email. (Can be html too)
        :param recipient: The recipient of the email
        :param image_url: The url of the image to include in the email
        :param unsubscribe_link: The link to unsubscribe from the email
        """
        if not isinstance(subject, str):
            raise TypeError("subject should be of type str")
        if not isinstance(body, str):
            raise TypeError("body should be of type str")
        
        template = """
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <title>{subject}</title>
        </head>
        <body
            style="
            font-family: Arial, sans-serif;
            background-color: #ffffff;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            "
        >
            <div style="width: 100%; background-color: #ffffff">
            <header
                style="
                color: #fff;
                display: flex;
                text-align: center;
                justify-content: center;
                padding: 5px;
                "
            >
            </header>
            <article style="margin-top: 20px; text-align: center">
                <h2>{subject}</h2>
            </article>

            <main style="padding: 20px">
                <section style="margin: 20px">
                <p
                    style="font-size: 14px; 
                    font-weight: 600;"
                >
                </p>
                {body}  <!-- Body is inserted here -->
                </section>
            </main>
            </div>
        </body>
        </html>
        """
        

        # Wrap each paragraph in <p> tags
        body_paragraphs = "\n".join(f"<p style='font-size: 14px'>{paragraph.strip()}</p>" for paragraph in body.split("\n\n"))

        return template.format(
            subject=subject.title(),
            body=body_paragraphs
        )