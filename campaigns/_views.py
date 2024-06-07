from attr import filters
from django.conf import settings
from django.http.response import HttpResponse
from django.views.decorators.http import require_http_methods
from rest_framework import exceptions, status, response

from api.views import SamanthaCampaignsAPIView
from api.dowell.user import DowellUser
from .dbobjects import Campaign, CampaignMessage
from .utils import construct_dowell_email_template
from .serializers import (
    CampaignSerializer,
    CampaignMessageSerializer,
    ContactUsSerializer,
)
from api.utils import _send_mail

from api.database import SamanthaCampaignsDB
from api.dowell.datacube import DowellDatacube
from .datacube import DowellDatacubeV2
from rest_framework.response import Response
from .helpers import CustomResponse, CampaignHelper, ContactUs
import requests
import time
from datetime import datetime
import os
import csv
from django.utils.crypto import get_random_string
from .utils import fetch_email
from rest_framework.exceptions import APIException
from .helpers import Scrape_contact_us
from django.core.exceptions import ValidationError
import concurrent.futures
from api.utils import is_phonenumber
from concurrent.futures import ThreadPoolExecutor
from .crawl import crawl


class UserRegistrationView(SamanthaCampaignsAPIView):
    """
    Endpoint for user registration related operations to create a new users collection.
    """

    def append_workspace_id(self, workspace_id):
        """
        Append workspace ID to a text file if it does not already exist.

        :param workspace_id: The workspace ID to be appended.
        """
        workspace_ids = self.get_workspace_ids()  # Retrieve existing workspace IDs
        if workspace_id not in workspace_ids:  # Check if the ID does not already exist
            with open("workspace_ids.txt", "a") as file:
                file.write(workspace_id + "\n")

    def get_workspace_ids(self):
        """
        Retrieve workspace IDs from the text file.

        :return: A list of workspace IDs.
        """
        if os.path.exists("workspace_ids.txt"):
            with open("workspace_ids.txt", "r") as file:
                workspace_ids = file.read().splitlines()
            return workspace_ids
        else:
            # Create the file if it doesn't exist
            with open("workspace_ids.txt", "a"):
                pass
            return []

    def get(self, request):
        """
        Get all collections and check if there's a collection created by the user.

        This method retrieves collections from the database and checks if collections created by the user exist.
        If all collections exist, it updates the user_info collection with the user data if there are any differences.

        :param request: The HTTP request object.
        :return: A response containing collection data or a message indicating the status of the operation.
        """
        print("called")
        workspace_id = request.query_params.get("workspace_id", None)
        if not workspace_id:
            return Response({"message": "workspace_id is required"}, status=400)

        database_name = f"{workspace_id}_samanta_campaign_db"
        add_workspace_id = self.append_workspace_id(workspace_id)
        collections = {
            "campaign_details": f"{workspace_id}_campaign_details",
            "contact_us": f"{workspace_id}_contact_us",
            "user_info": f"{workspace_id}_user_info",
            "emails": f"{workspace_id}_emails",
            "links": f"{workspace_id}_links",
        }

        try:
            dowell_datacube = DowellDatacubeV2(
                db_name=database_name, dowell_api_key=settings.PROJECT_API_KEY
            )
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=500)

        all_collections_exist = True

        for collection_name, collection in collections.items():
            response = dowell_datacube.fetch(_from=collection)
            message = response.get("message")
            print(f"Checking collection {collection}: {message}")

            if message == "database does not exist in datacube":
                return Response(
                    {"message": "database does not exist, please create"}, status=404
                )
            elif (
                f"Collection '{collection}' does not exist in Datacube database"
                in message
            ):
                dowell_datacube.create_collection(name=collection)
                print("Inserted collection", collection)
                if collection == collections["user_info"]:
                    print("Creating user info")
                    user = DowellUser(workspace_id=workspace_id)
                    user_info_data = {
                        "workspace_id": workspace_id,
                        "username": user.username,
                        "email": user.email,
                        "api_key": user.api_key,
                        "firstname": user.firstname,
                        "lastname": user.lastname,
                        "phonenumber": user.phonenumber,
                        "image_url": user.image_url,
                        "active_status": user.active_status,
                        "has_paid_account": user.has_paid_account,
                        "credits": user.credits,
                        "api_key_active_status": user.api_key_active_status,
                    }
                    dowell_datacube.insert(_into=collection, data=user_info_data)
            elif message in ["Data found!", "No data exists for this query/collection"]:
                continue
            else:
                return Response(
                    {"Success": False, "message": f"Unexpected response: {message}"},
                    status=500,
                )

        # Fetch the existing user data from user_info collection
        dowell_user = DowellUser(workspace_id=workspace_id)
        filters = {"email": dowell_user.email}
        fetch_response = dowell_datacube.fetch(
            _from=collections["user_info"], filters=filters
        )
        print(fetch_response)

        if fetch_response["success"] and fetch_response["message"] == "Data found!":
            existing_user_data = fetch_response["data"][0]

            # Create a dictionary of the new user data
            new_user_data = {
                "workspace_id": workspace_id,
                "username": dowell_user.username,
                "email": dowell_user.email,
                "api_key": dowell_user.api_key,
                "firstname": dowell_user.firstname,
                "lastname": dowell_user.lastname,
                "phonenumber": dowell_user.phonenumber,
                "image_url": dowell_user.image_url,
                "active_status": dowell_user.active_status,
                "has_paid_account": dowell_user.has_paid_account,
                "credits": dowell_user.credits,
                "api_key_active_status": dowell_user.api_key_active_status,
            }

            # Determine the fields that need updating
            update_data = {
                key: value
                for key, value in new_user_data.items()
                if existing_user_data.get(key) != value
            }
            print(update_data)

            if update_data:
                res = dowell_datacube.update(
                    _in=collections["user_info"], filter=filters, data=update_data
                )
                print(res)
            else:
                print("No updates needed")

        else:
            # If no existing data is found, insert new user data
            print("Inserting new user info")
            user = DowellUser(workspace_id=workspace_id)
            user_info_data = {
                "workspace_id": workspace_id,
                "username": user.username,
                "email": user.email,
                "api_key": user.api_key,
                "firstname": user.firstname,
                "lastname": user.lastname,
                "phonenumber": user.phonenumber,
                "image_url": user.image_url,
                "active_status": user.active_status,
                "has_paid_account": user.has_paid_account,
                "credits": user.credits,
                "api_key_active_status": user.api_key_active_status,
            }
            res = dowell_datacube.insert(
                _into=collections["user_info"], data=user_info_data
            )
            print(res)

        return Response(
            {"Success": True, "message": "User Database exists"}, status=200
        )


class TestEmail(SamanthaCampaignsAPIView):
    def post(self, request, *args, **kwargs):
        try:
            workspace_id = request.query_params.get("workspace_id")
            user = DowellUser(workspace_id=workspace_id)

            campaign_id = request.data.get("campaign_id")
            recipient_address = request.data.get("recipient_address")
            sender_address = request.data.get("sender_address")
            sender_name = sender_address
            recipient_name = request.data.get("recipient_name")

            message = CampaignMessage.manager.get(
                campaign_id=campaign_id,
                dowell_api_key=settings.PROJECT_API_KEY,
                workspace_id=workspace_id,
                wanted="message",
            )

            if message:
                subject = message.subject
                body = message.body

                if message.is_html_email:
                    # If the message is HTML, fetch HTML body
                    html_body = fetch_email(message.html_email_link)
                    if html_body:
                        body = html_body

                _send_mail(
                    subject=subject,
                    body=self.construct_dowell_email_template(
                        subject=subject,
                        body=body,
                        unsubscribe_link="https://samanta-campaigns.flutterflow.app/",
                    ),
                    sender_address=sender_address,
                    recipient_address=recipient_address,
                    sender_name=sender_name,
                    recipient_name=recipient_name,
                )
                return response.Response(
                    {"success": True, "message": "Email sent"}, status=200
                )
            else:
                return response.Response(
                    {"success": False, "message": "No message found for the campaign."},
                    status=400,
                )

        except Exception as e:
            return response.Response(
                {"success": False, "message": f"Failed to send email. Error: {str(e)}"},
                status=500,
            )

    def construct_dowell_email_template(
        self,
        subject: str,
        body: str,
        image_url: str = None,
        unsubscribe_link: str = None,
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
                <img
                src="{image_url}"
                height="140px"
                width="140px"
                style="display: block; margin: 0 auto"
                />
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

                {unsubscribe_section}
            </main>
            </div>
        </body>
        </html>
        """
        if unsubscribe_link:
            unsubscribe_section = f"""
            <footer
            style="
                background-color: #005733;
                color: #fff;
                text-align: center;
                padding: 10px;
            "
            >
            <a 
                href="{unsubscribe_link}" 
                style="
                text-decoration: none;
                color: white;
                margin-bottom: 10px;
                display: block;
                "
            >
                Unsubscribe
            </a>
            </footer>
            """
        else:
            unsubscribe_section = ""

        # Wrap each paragraph in <p> tags
        body_paragraphs = "\n".join(
            f"<p style='font-size: 14px'>{paragraph.strip()}</p>"
            for paragraph in body.split("\n\n")
        )

        return template.format(
            subject=subject.title(),
            body=body_paragraphs,  # Replaced body with paragraphs
            image_url=image_url
            or "https://dowellfileuploader.uxlivinglab.online/hr/logo-2-min-min.png",
            unsubscribe_section=unsubscribe_section,
        )


class TestSmS(SamanthaCampaignsAPIView):
    def post(self, request):
        workspace_id = request.query_params.get("workspace_id")
        campaign_id = request.data.get("campaign_id")
        recipient_phone_number = request.data.get("recipient_phone_number")
        sender_phone_number = request.data.get("sender_phone_number")
        sender_name = sender_phone_number
        recipient_name = request.data.get("recipient_name")

        message = CampaignMessage.manager.get(
            campaign_id=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
            wanted="message",
        )
        if message:
            body = message.body

            # res = self.send_sms(
            #   message=body,
            #  recipient_name=recipient_name,
            # recipient_phone_number=recipient_phone_number,
            # sender_name=sender_name,
            # sender_phone_number=sender_phone_number,
            # dowell_api_key=settings.PROJECT_API_KEY,
            # )
            # print(res)
            return Response({"success": True, "message": "Sms sent"})

        else:
            return Response(
                {"success": False, "message": "No message found in the campaign"}
            )

    def send_sms(
        self,
        message: str,
        recipient_name: str,
        recipient_phone_number: str,
        sender_name: str,
        sender_phone_number: str,
        dowell_api_key: str,
    ):
        """
        Sends SMS using Dowell SMS API. Credit deduction is inbuilt from the API.

        :param message: message to be sent
        :param recipient_phone_number: recipient's phone number
        :param sender_phone_number: sender's phone number
        :param dowell_api_key: user's dowell client admin api key.
        :return: None
        """
        if not message:
            raise ValueError("message cannot be empty")
        if not recipient_phone_number:
            raise ValueError("recipient_phone_number cannot be empty")
        if not sender_phone_number:
            raise ValueError("sender_phone_number cannot be empty")
        if not dowell_api_key:
            raise ValueError("dowell_api_key cannot be empty")

        for number in (recipient_phone_number, sender_phone_number):
            if not is_phonenumber(number):
                raise ValidationError(f"{number} is not a valid phone number!")
        response = requests.post(
            url=f"https://100085.pythonanywhere.com/api/v1/dowell-sms/{dowell_api_key}/",
            data={
                "sender": recipient_name,
                "recipient": recipient_phone_number,
                "content": message,
                "created_by": sender_name,
            },
        )
        print(response.json())
        if response.status_code != 200:
            response.raise_for_status()
        if not response.json()["success"]:
            raise Exception(response.json()["message"])
        return None


class CampaignListCreateAPIView(SamanthaCampaignsAPIView):
    def get(self, request, *args, **kwargs):
        """
        Get all campaigns created by the user
        """
        workspace_id = request.query_params.get("workspace_id", None)
        page_size = request.query_params.get("page_size", 16)
        page_number = request.query_params.get("page_number", 1)
        user = DowellUser(workspace_id=workspace_id)
        try:
            page_number = int(page_number)
            page_size = int(page_size)
        except ValueError:
            raise exceptions.NotAcceptable("Invalid page number or page size.")

        user = DowellUser(workspace_id=workspace_id)
        print("called")
        campaigns = Campaign.manager.filter(
            creator_id=workspace_id,
            dowell_api_key="1b834e07-c68b-4bf6-96dd-ab7cdc62f07f",
            limit=page_size,
            offset=(page_number - 1) * page_size,
            workspace_id=workspace_id,
        )
        data = []

        necessities = (
            "id",
            "title",
            "type",
            "image",
            "broadcast_type",
            "start_date",
            "end_date",
            "is_active",
            "has_launched",
        )
        for campaign in campaigns:
            campaign_data = campaign.data
            campaign_data = {key: campaign_data[key] for key in necessities}
            data.append(campaign_data)

        response_data = {
            "count": len(data),
            "page_size": page_size,
            "page_number": page_number,
            "results": data,
        }
        if page_number > 1:
            response_data["previous_page"] = (
                f"{request.path}?workspace_id={workspace_id}&page_size={page_size}&page_number={page_number - 1}"
            )
        if len(data) == page_size:
            response_data["next_page"] = (
                f"{request.path}?workspace_id={workspace_id}&page_size={page_size}&page_number={page_number + 1}"
            )

        return response.Response(data=response_data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        """
        Create a new campaign

        Request Body Format:
        ```
        {
            "type": "",
            "broadcast_type": "",
            "title": "",
            "purpose": "",
            "image": "",
            "keyword": "",
            "target_city": "",
            "target_audience": "",
            "range": 100,
            "frequency": "",
            "start_date": "",
            "end_date": "",
            "audiences": [],
            "leads_links": []
        }
        ```
        """
        start_time = time.time()
        workspace_id = request.query_params.get("workspace_id", None)
        user = DowellUser(workspace_id=workspace_id)
        data = request.data
        unverified_emails = data.get("unverified_emails")
        print("this is unverified emails")
        if not isinstance(data, dict):
            raise exceptions.NotAcceptable("Request body must be a dictionary.")
        user = DowellUser(workspace_id=workspace_id)
        data["default_message"] = True
        serializer = CampaignSerializer(
            data=data,
            context={"creator": user, "dowell_api_key": settings.PROJECT_API_KEY},
        )
        serializer.is_valid(raise_exception=True)
        campaign = serializer.save()

        default_message = {
            "subject": campaign.title,
            "body": campaign.purpose,
            "is_default": True,
        }
        message_serializer = CampaignMessageSerializer(
            data=default_message,
            context={
                "campaign": campaign,
                "workspace_id": workspace_id,
                "dowell_api_key": settings.PROJECT_API_KEY,
            },
        )
        message_serializer.is_valid(raise_exception=True)

        message_serializer.save()

        print("save is okay")

        updated_campaign: Campaign = Campaign.manager.get(
            creator_id=workspace_id,
            pkey=campaign.pkey,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
        )
        print("update is also okay")
        serializer = CampaignSerializer(
            instance=updated_campaign,
            context={"dowell_api_key": settings.PROJECT_API_KEY},
        )

        can_launch, reason, percentage_ready = updated_campaign.is_launchable(
            dowell_api_key=settings.PROJECT_API_KEY
        )
        # Insert unverified emails only if they are not None
        if unverified_emails is not None:
            dowell_datacube = DowellDatacubeV2(
                db_name=f"{workspace_id}_samanta_campaign_db",
                dowell_api_key=settings.PROJECT_API_KEY,
            )

            def insert_email(email):
                unverified_data = {
                    "creator_id": workspace_id,
                    "campaign_id": campaign.pkey,
                    "is_verified": False,
                    "email": email,  # Assuming each email is a link or a dictionary containing the link
                }
                return dowell_datacube.insert(
                    _into=f"{workspace_id}_emails", data=unverified_data
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = {
                    executor.submit(insert_email, email): email
                    for email in unverified_emails
                }
                for future in concurrent.futures.as_completed(futures):
                    email = futures[future]
                    try:
                        res_unverified = future.result()
                        print(f"Unverified email inserted: {res_unverified}")
                    except Exception as e:
                        print(f"Error inserting email {email}: {e}")
        # updated_campaign = Campaign.manager.get(

        # )

        # can_launch, reason, percentage_ready = campaign.is_launchable(dowell_api_key=settings.PROJECT_API_KEY)
        data = {
            **updated_campaign.data,
            "launch_status": {
                "can_launch": can_launch,
                "reason": reason,
                "percentage_ready": percentage_ready,
            },
        }

        end_time = time.time()

        print(f"Campaign View: {end_time-start_time}")

        return response.Response(data=data, status=status.HTTP_200_OK)


class CampaignRetrieveUpdateDeleteAPIView(SamanthaCampaignsAPIView):
    """Campaign Retrieve and Update API View"""

    def get(self, request, *args, **kwargs):
        """
        Retrieve a campaign by id
        """
        workspace_id = request.query_params.get("workspace_id", None)
        campaign_id = kwargs.get("campaign_id", None)
        user = DowellUser(workspace_id=workspace_id)
        if not campaign_id:
            raise exceptions.NotAcceptable("Campaign id must be provided.")

        user = DowellUser(workspace_id=workspace_id)
        campaign: Campaign = Campaign.manager.get(
            creator_id=workspace_id,
            pkey=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
        )
        serializer = CampaignSerializer(
            instance=campaign, context={"dowell_api_key": settings.PROJECT_API_KEY}
        )

        can_launch, reason, percentage_ready = campaign.is_launchable(
            dowell_api_key=settings.PROJECT_API_KEY
        )
        data = {
            **serializer.data,
            "next_due_date": campaign.next_due_date,
            "has_audiences": campaign.has_audiences,
            "has_message": campaign.get_message(dowell_api_key=settings.PROJECT_API_KEY)
            is not None,
            "launch_status": {
                "can_launch": can_launch,
                "reason": reason,
                "percentage_ready": percentage_ready,
            },
        }
        return response.Response(data=data, status=status.HTTP_200_OK)

    def put(self, request, *args, **kwargs):
        """
        Update a campaign
        """
        workspace_id = request.query_params.get("workspace_id", None)
        campaign_id = kwargs.get("campaign_id", None)
        user = DowellUser(workspace_id=workspace_id)
        data = request.data
        if not isinstance(data, dict):
            raise exceptions.NotAcceptable("Request body must be a dictionary.")
        if not campaign_id:
            raise exceptions.NotAcceptable("Campaign id must be provided.")

        user = DowellUser(workspace_id=workspace_id)
        campaign: Campaign = Campaign.manager.get(
            creator_id=workspace_id,
            pkey=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
        )
        print("getting campaign worked")
        serializer = CampaignSerializer(
            instance=campaign,
            data=data,
            context={"dowell_api_key": settings.PROJECT_API_KEY},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        print("after saving")
        return response.Response(data=serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        """
        Partially update a campaign
        """
        workspace_id = request.query_params.get("workspace_id", None)
        campaign_id = kwargs.get("campaign_id", None)
        user = DowellUser(workspace_id=workspace_id)
        data = request.data
        if not isinstance(data, dict):
            raise exceptions.NotAcceptable("Request body must be a dictionary.")
        if not campaign_id:
            raise exceptions.NotAcceptable("Campaign id must be provided.")

        user = DowellUser(workspace_id=workspace_id)
        campaign: Campaign = Campaign.manager.get(
            creator_id=workspace_id,
            pkey=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
        )

        serializer = CampaignSerializer(
            instance=campaign,
            data=data,
            partial=True,
            context={
                "dowell_api_key": settings.PROJECT_API_KEY,
                "workspace_id": workspace_id,
            },
        )
        serializer.is_valid(raise_exception=True)
        campaign = serializer.save()

        can_launch, reason, percentage_ready = campaign.is_launchable(
            dowell_api_key=settings.PROJECT_API_KEY
        )
        data = {
            **campaign.data,
            "launch_status": {
                "can_launch": can_launch,
                "reason": reason,
                "percentage_ready": percentage_ready,
            },
        }
        return response.Response(data=data, status=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        """
        Delete a campaign
        """
        workspace_id = request.query_params.get("workspace_id", None)
        campaign_id = kwargs.get("campaign_id", None)
        user = DowellUser(workspace_id=workspace_id)
        if not campaign_id:
            raise exceptions.NotAcceptable("Campaign id must be provided.")

        user = DowellUser(workspace_id=workspace_id)
        campaign: Campaign = Campaign.manager.get(
            creator_id=workspace_id,
            pkey=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
        )
        campaign.delete(dowell_api_key=settings.PROJECT_API_KEY)

        return response.Response(
            data={"detail": "Campaign deleted successfully."}, status=status.HTTP_200_OK
        )


class CampaignActivateDeactivateAPIView(SamanthaCampaignsAPIView):
    """Campaign Activate and Deactivate API View"""

    def get(self, request, *args, **kwargs):
        """
        Activate or deactivate campaign
        """
        workspace_id = request.query_params.get("workspace_id", None)
        campaign_id = kwargs.get("campaign_id", None)
        user = DowellUser(workspace_id=workspace_id)

        if not campaign_id:
            raise exceptions.NotAcceptable("Campaign id must be provided.")

        user = DowellUser(workspace_id=workspace_id)
        campaign: Campaign = Campaign.manager.get(
            creator_id=workspace_id,
            pkey=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
        )

        if campaign.is_active:
            campaign.deactivate(dowell_api_key=settings.PROJECT_API_KEY)
            msg = f"Campaign: '{campaign.title}', has been deactivated."
        else:
            campaign.activate(dowell_api_key=settings.PROJECT_API_KEY)
            msg = f"Campaign: '{campaign.title}', has been activated."

        return response.Response(data={"detail": msg}, status=status.HTTP_200_OK)


class CampaignAudienceListAddAPIView(SamanthaCampaignsAPIView):
    """Campaign Audience List API View"""

    def get(self, request, *args, **kwargs):
        """
        Get all campaign audiences
        """
        workspace_id = request.query_params.get("workspace_id", None)
        campaign_id = kwargs.get("campaign_id", None)
        user = DowellUser(workspace_id=workspace_id)
        if not campaign_id:
            raise exceptions.NotAcceptable("Campaign id must be provided.")

        user = DowellUser(workspace_id=workspace_id)
        campaign = Campaign.manager.get(
            creator_id=workspace_id,
            pkey=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
        )

        return response.Response(
            data=campaign.data["audiences"], status=status.HTTP_200_OK
        )

    def post(self, request, *args, **kwargs):
        """
        Add audiences to a campaign

        Request Body Format:
        ```
        {
            "audiences": []
        }
        ```
        """
        workspace_id = request.query_params.get("workspace_id", None)
        campaign_id = kwargs.get("campaign_id", None)
        user = DowellUser(workspace_id=workspace_id)
        data = request.data
        if not isinstance(data, dict):
            raise exceptions.NotAcceptable("Request body must be a dictionary.")
        if not campaign_id:
            raise exceptions.NotAcceptable("Campaign id must be provided.")

        audiences = data.get("audiences", [])
        if not isinstance(audiences, list):
            raise exceptions.NotAcceptable("Audiences must be a list")
        if not audiences:
            raise exceptions.NotAcceptable("Audiences must be provided.")

        user = DowellUser(workspace_id=workspace_id)
        campaign = Campaign.manager.get(
            creator_id=workspace_id,
            pkey=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
        )

        for audience in audiences:
            campaign.add_audience(audience)
        campaign.save(dowell_api_key=settings.PROJECT_API_KEY)

        return response.Response(
            data=campaign.data["audiences"], status=status.HTTP_200_OK
        )


# todo add workspace_id
# todo add workspace_id
class campaign_audience_unsubscribe_view(SamanthaCampaignsAPIView):
    def get(self, request, *args, **kwargs):
        """
        Unsubscribes an audience from a campaign
        """
        campaign_id = kwargs.get("campaign_id", None)
        audience_id = request.GET.get("audience_id", None)
        workspace_id = request.GET.get("workspace_id", None)
        msg = "You have successfully unsubscribed from this campaign."
        try:
            if not campaign_id:
                raise exceptions.NotAcceptable("Campaign id must be provided.")
            if not audience_id:
                raise exceptions.NotAcceptable("Audience id must be provided.")
            campaign: Campaign = Campaign.manager.get(
                creator_id=workspace_id,
                pkey=campaign_id,
                dowell_api_key=settings.PROJECT_API_KEY,
                workspace_id=workspace_id,
            )
            print("got campaign", campaign)
            audience = campaign.audiences.get(id=audience_id)
            try:
                audience.unsubscribe()
            except:
                msg = "You have already been unsubscribed from this campaign."
            finally:
                campaign.save(dowell_api_key=settings.PROJECT_API_KEY)

        except:
            msg = "<h3>Something went wrong! Please check the link and try again. part 2</h3>"
            return HttpResponse(msg, status=400)

        html_response = construct_dowell_email_template(
            subject=f"Unsubscribe from Campaign: '{campaign.title}'", body=msg
        )
        return HttpResponse(html_response, status=200)


class CampaignMessageCreateRetreiveAPIView(SamanthaCampaignsAPIView):
    """Campaign Message Create and Retrieve API View"""

    def get(self, request, *args, **kwargs):
        """
        Get campaign message
        """
        workspace_id = request.query_params.get("workspace_id", None)
        campaign_id = kwargs.get("campaign_id", None)
        user = DowellUser(workspace_id=workspace_id)
        if not campaign_id:
            raise exceptions.NotAcceptable("Campaign id must be provided.")

        user = DowellUser(workspace_id=workspace_id)
        message = CampaignMessage.manager.get(
            campaign_id=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
            wanted="message",
        )

        return response.Response(data=message.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        """
        Add a message to a campaign

        Request Body Format:
        ```
        {
            "subject": "",
            "body": "",
            "sender": ""
            "is_default": "",
            "is_html_email: "",
            "html_email_link": "",
        }
        ```
        """
        workspace_id = request.query_params.get("workspace_id", None)
        user = DowellUser(workspace_id=workspace_id)
        data = request.data
        if not isinstance(data, dict):
            raise exceptions.NotAcceptable("Request body must be a dictionary.")

        campaign_id = kwargs.get("campaign_id", None)
        if not campaign_id:
            raise exceptions.NotAcceptable("Campaign id must be provided.")

        user = DowellUser(workspace_id=workspace_id)
        campaign = Campaign.manager.get(
            creator_id=workspace_id,
            pkey=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
        )

        serializer = CampaignMessageSerializer(
            data=data,
            context={"campaign": campaign, "dowell_api_key": settings.PROJECT_API_KEY},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return response.Response(data=serializer.data, status=status.HTTP_200_OK)


class CampaignMessageUpdateDeleteAPIView(SamanthaCampaignsAPIView):
    """Update and Delete Campaign Message API View"""

    def put(self, request, *args, **kwargs):
        """
        Update campaign message
        """
        workspace_id = request.query_params.get("workspace_id", None)
        campaign_id = kwargs.get("campaign_id", None)
        message_id = kwargs.get("message_id", None)
        user = DowellUser(workspace_id=workspace_id)
        data = request.data
        if not isinstance(data, dict):
            raise exceptions.NotAcceptable("Request body must be a dictionary.")
        if not campaign_id:
            raise exceptions.NotAcceptable("Campaign id must be provided.")
        if not message_id:
            raise exceptions.NotAcceptable("Message id must be provided.")

        user = DowellUser(workspace_id=workspace_id)
        message = CampaignMessage.manager.get(
            pkey=message_id,
            campaign_id=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
            wanted="message",
        )

        serializer = CampaignMessageSerializer(
            instance=message,
            data=data,
            context={
                "dowell_api_key": settings.PROJECT_API_KEY,
                "workspace_id": workspace_id,
            },
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        campaign: Campaign = Campaign.manager.get(
            creator_id=workspace_id,
            pkey=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
        )

        campaign.default_message = False
        campaign.save(dowell_api_key=settings.PROJECT_API_KEY)

        return response.Response(data=serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        """
        Partially update campaign message
        """
        workspace_id = request.query_params.get("workspace_id", None)
        campaign_id = kwargs.get("campaign_id", None)
        message_id = kwargs.get("message_id", None)
        user = DowellUser(workspace_id=workspace_id)
        data = request.data
        if not isinstance(data, dict):
            raise exceptions.NotAcceptable("Request body must be a dictionary.")
        if not campaign_id:
            raise exceptions.NotAcceptable("Campaign id must be provided.")
        if not message_id:
            raise exceptions.NotAcceptable("Message id must be provided.")

        user = DowellUser(workspace_id=workspace_id)
        message = CampaignMessage.manager.get(
            pkey=message_id,
            campaign_id=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
            wanted="message",
        )

        serializer = CampaignMessageSerializer(
            instance=message,
            data=data,
            partial=True,
            context={
                "dowell_api_key": settings.PROJECT_API_KEY,
                "workspace_id": workspace_id,
            },
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        campaign: Campaign = Campaign.manager.get(
            creator_id=workspace_id,
            pkey=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
        )

        campaign.default_message = False
        campaign.save(dowell_api_key=settings.PROJECT_API_KEY)

        return response.Response(data=serializer.data, status=status.HTTP_200_OK)


class CampaignLaunchAPIView(SamanthaCampaignsAPIView):
    def get(self, request, *args, **kwargs):
        """
        Launch a campaign
        """
        workspace_id = request.query_params.get("workspace_id", None)
        campaign_id = kwargs.get("campaign_id", None)
        user = DowellUser(workspace_id=workspace_id)
        if not campaign_id:
            raise exceptions.NotAcceptable("Campaign id must be provided.")

        user = DowellUser(workspace_id=workspace_id)
        campaign = Campaign.manager.get(
            pkey=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
        )
        campaign.launch(dowell_api_key=settings.PROJECT_API_KEY)

        return response.Response(
            data={"detail": "Campaign launched successfully."},
            status=status.HTTP_200_OK,
        )


class GetScrapingLink(SamanthaCampaignsAPIView):
    """Payload for fetching link data"""

    """
        {
            "links": [ "https://preview.colorlib.com/theme/bootstrap/contact-form-03/", "https://giantmillers.co.ke/contact/"]
        }
    """

    def post(self, request, *args, **kwargs):
        # Get the 'links' data from the request
        links = request.data.get("links", [])

        # Check if 'links' data is empty
        if not links:
            # Return an error response if 'links' data is not present
            return Response(
                {"error": "No links provided"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Call the link extractor method with the provided links
        request_response = ContactUs().link_extractor(links)

        # Check the response status
        if request_response.get("status") == 200:
            # If successful, return the data with the same status
            return Response(
                {"data": request_response.get("data")},
                status=request_response.get("status"),
            )
        else:
            # If failed, return an error response with the received status
            return Response(
                {"error": "Request failed"}, status=request_response.get("status")
            )


class SumitContactUsForm(SamanthaCampaignsAPIView):
    """payload for SumitContactUs"""

    """
        "links": [
            "https://preview.colorlib.com/theme/bootstrap/contact-form-03/", 
            "https://giantmillers.co.ke/contact/"
        ],
        data: {
            "name": "text",
            "email": "email@gmail.com",
            "subject": "text",
            "message": "textarea",
            "s": "text",
            "your-name": "text",
            "your-email": "email@gmail.com",
            "phonenumber": "tel",
            "your-subject": "text",
            "your-message": "textarea"
        }
    """

    def post(self, request, *args, **kwargs):
        data = request.data.get("form_data", [])

        links = request.data.get("page_links", [])

        # Check if 'data' or 'links' data is empty
        if not data or not links:
            # Return an error response if either 'data' or 'links' data is not present
            return Response(
                {"error": "Data or links not provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        url = "https://uxlivinglab100106.pythonanywhere.com/api/contact-us-extractor/"
        payload = {
            "page_links": links,
            "data": data,
        }
        response = requests.post(url, json=payload)
        print(response.json())

        if response.status_code == 200:
            return Response({"success": True, "data": "Request sent successfully"})
        else:
            return Response({"success": False, "data": "Request failed"})


class ContactUsView(SamanthaCampaignsAPIView):
    def get(self, request):
        try:
            workspace_id = request.query_params.get("workspace_id", None)
            if not workspace_id:
                raise APIException("Workspace ID is required.")

            collection_name = f"{workspace_id}_contact_us"
            database_name = f"{workspace_id}_samanta_campaign_db"
            dowell_datacube = DowellDatacube(
                db_name=database_name, dowell_api_key=settings.PROJECT_API_KEY
            )
            filters = {"page_links": {"$exists": True}}
            result = dowell_datacube.fetch(collection_name, filters=filters)
            print(result)
            return Response({"success": True, "contact_us": result})

        except Exception as e:
            return Response({"error": str(e)}, status=500)

    def post(self, request):
        try:
            # Extract workspace_id from query parameters
            try:
                workspace_id = request.query_params.get("workspace_id", None)
                if not workspace_id:
                    raise APIException("Workspace ID is required.")
            except Exception as e:
                return Response(
                    {"error": f"Failed to extract workspace_id: {str(e)}"}, status=400
                )

            # Extract links from request data
            try:
                links = request.data.get("links")
                if not links:
                    raise APIException("Links data is required.")
            except Exception as e:
                return Response(
                    {"error": f"Failed to extract links: {str(e)}"}, status=400
                )

            form_fields = []
            collection_name = f"{workspace_id}_contact_us"
            database_name = f"{workspace_id}_samanta_campaign_db"

            try:
                dowell_datacube = DowellDatacubeV2(
                    db_name=database_name, dowell_api_key=settings.PROJECT_API_KEY
                )
            except Exception as e:
                return Response(
                    {"error": f"Failed to initialize DowellDatacubeV2: {str(e)}"},
                    status=500,
                )

            title = request.data.get("title")
            purpose = request.data.get("purpose")
            image = request.data.get("image")

            # Validate the links data
            try:
                serializer = ContactUsSerializer(data={"page_links": links})
                serializer.is_valid(raise_exception=True)
            except Exception as e:
                return Response(
                    {"error": f"Failed to validate links data: {str(e)}"}, status=400
                )

            # Prepare data for insertion
            try:
                serialized_data = serializer.validated_data
                serialized_data["is_crawled"] = False  # Add is_crawled attribute
                serialized_data["form_fields"] = (
                    form_fields  # Add form_fields attribute
                )
                serialized_data["title"] = title
                serialized_data["purpose"] = purpose
                serialized_data["created_at"] = (
                    datetime.now().isoformat()
                )  # Convert to ISO format
                serialized_data["image"] = image
            except Exception as e:
                return Response(
                    {"error": f"Failed to prepare data for insertion: {str(e)}"},
                    status=500,
                )

            # Insert data into the database
            try:
                result = dowell_datacube.insert(
                    _into=collection_name, data=serialized_data
                )
                print("this is result ", result)
            except Exception as e:
                return Response(
                    {"error": f"Failed to insert data into database: {str(e)}"},
                    status=500,
                )

            # Fetch the updated data
            try:
                id = result.get("inserted_id")
                filters = {"_id": id}
                updated_contact_us = dowell_datacube.fetch(
                    _from=collection_name, filters=filters
                )
            except Exception as e:
                return Response(
                    {"error": f"Failed to fetch updated data: {str(e)}"}, status=500
                )

            return Response(updated_contact_us["data"])

        except APIException as e:
            return Response({"error": str(e)}, status=400)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"}, status=500
            )


class GetContactUs(SamanthaCampaignsAPIView):
    def get(self, request):
        try:
            workspace_id = request.query_params.get("workspace_id")
            if not workspace_id:
                raise APIException("Workspace ID is required.")

            campaign_id = request.query_params.get("campaign_id")
            if not campaign_id:
                raise APIException("Campaign ID is required.")

            collection_name = f"{workspace_id}_contact_us"
            database_name = f"{workspace_id}_samanta_campaign_db"

            try:
                dowell_datacube = DowellDatacube(
                    db_name=database_name, dowell_api_key=settings.PROJECT_API_KEY
                )
            except Exception as e:
                return Response(
                    {"error": f"Failed to initialize DowellDatacube: {str(e)}"},
                    status=500,
                )

            filters = {"_id": campaign_id}
            try:
                result = dowell_datacube.fetch(_from=collection_name, filters=filters)
                if not result:
                    raise APIException("No data found for the given campaign ID.")
            except Exception as e:
                return Response(
                    {"error": f"Failed to fetch data: {str(e)}"}, status=500
                )

            return Response({"success": True, "contact_us": result})

        except APIException as e:
            return Response({"error": str(e)}, status=400)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"}, status=500
            )

    def put(self, request):
        try:
            workspace_id = request.query_params.get("workspace_id")
            if not workspace_id:
                raise APIException("Workspace ID is required.")

            campaign_id = request.query_params.get("campaign_id")
            if not campaign_id:
                raise APIException("Campaign ID is required.")

            data = request.data
            if not data:
                raise APIException("Update data is required.")

            collection_name = f"{workspace_id}_contact_us"
            database_name = f"{workspace_id}_samanta_campaign_db"

            try:
                dowell_datacube = DowellDatacubeV2(
                    db_name=database_name, dowell_api_key=settings.PROJECT_API_KEY
                )
            except Exception as e:
                return Response(
                    {"error": f"Failed to initialize DowellDatacube: {str(e)}"},
                    status=500,
                )

            filter = {"_id": campaign_id}
            try:
                result = dowell_datacube.update(
                    _in=collection_name, filter=filter, data=data
                )
                if not result:
                    raise APIException("Failed to update the contact us data.")
            except Exception as e:
                return Response(
                    {"error": f"Failed to update data: {str(e)}"}, status=500
                )

            return Response(
                {"success": True, "message": "Contact us updated successfully"}
            )

        except APIException as e:
            return Response({"error": str(e)}, status=400)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"}, status=500
            )


class CrawlLinks(SamanthaCampaignsAPIView):
    def post(self, request):
        workspace_id = request.query_params.get("workspace_id")
        print(workspace_id)
        scrape_result = Scrape_contact_us.scrape(workspace_id=workspace_id)

        if scrape_result is None:
            return Response(
                {"message": "Form data already crawled or an error occurred."},
                status=200,
            )
        else:
            return Response(
                {"message": "Done crawling form data.", "data": scrape_result},
                status=200,
            )


class DataUpload(SamanthaCampaignsAPIView):
    def post(self, request):
        data_list = request.data.get("list")
        workspace_id = request.query_params.get("workspace_id")
        print(workspace_id)

        # Generate a unique filename for the CSV file
        csv_filename = "data_" + get_random_string(length=6) + ".csv"
        csv_file_path = os.path.join(
            "/tmp", csv_filename
        )  # Use /tmp directory for temporary storage

        # Write data to the CSV file
        with open(csv_file_path, "w", newline="") as f:
            writer = csv.writer(f)
            for row in data_list:
                writer.writerow(row)

        # Serve the file as a download response
        with open(csv_file_path, "rb") as f:
            response = HttpResponse(f, content_type="text/csv")
            response["Content-Disposition"] = f"attachment; filename={csv_filename}"

        return response


class TestingRun(SamanthaCampaignsAPIView):
    def post(self, request):
        workspace_id = request.query_params.get("workspace_id")
        campaign_id = request.data.get("campaign_id")
        user = DowellUser(workspace_id=workspace_id)
        campaign: Campaign = Campaign.manager.get(
            creator_id=workspace_id,
            pkey=campaign_id,
            dowell_api_key=settings.PROJECT_API_KEY,
            workspace_id=workspace_id,
            wanted="campaign",
        )
        res = campaign.run(
            raise_exception=False,
            log_errors=True,
            dowell_api_key=settings.PROJECT_API_KEY,
        )
        return Response(res)

class WorkspaceIDsView(SamanthaCampaignsAPIView):
    def get(self, request):
        file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'workspace_ids.txt')
        
        if not os.path.exists(file_path):
            return Response({"error": "File not found."}, status=404)

        try:
            with open(file_path, 'r') as file:
                ids = file.read().splitlines()
            return Response(ids, status=200)
        except Exception as e:
            return Response({"error": str(e)}, status=500)


campaign_list_create_api_view = CampaignListCreateAPIView.as_view()
get_link_data_view = GetScrapingLink.as_view()
submit_contact_us_view = SumitContactUsForm.as_view()
campaign_retreive_update_delete_api_view = CampaignRetrieveUpdateDeleteAPIView.as_view()
campaign_activate_deactivate_api_view = CampaignActivateDeactivateAPIView.as_view()
campaign_audience_list_add_api_view = CampaignAudienceListAddAPIView.as_view()
campaign_message_create_retrieve_api_view = (
    CampaignMessageCreateRetreiveAPIView.as_view()
)
campaign_message_update_delete_api_view = CampaignMessageUpdateDeleteAPIView.as_view()
campaign_launch_api_view = CampaignLaunchAPIView.as_view()
user_registration_view = UserRegistrationView.as_view()
test_email_view = TestEmail.as_view()
contact_us = ContactUsView.as_view()
scrape_contact_us = CrawlLinks.as_view()
data_upload = DataUpload.as_view()
test_sms_view = TestSmS.as_view()
test_run = TestingRun.as_view()
get_contact_us = GetContactUs.as_view()
get_workspace_ids = WorkspaceIDsView.as_view()
