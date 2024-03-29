from django.utils import timezone
import string
import random
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
import httpx
import requests

from api.validators import is_valid_url
from api.objects.utils import async_ttl_cache

from api.dowell.user import DowellUser



# DOES NOT YET TAKE INTO CONSIDERATION THAT USER MAY HAVE OTHER SCHEDULED CAMPAIGNS THAT WILL ACCESS THE AVAILABLE CREDITS LATER
def check_campaign_creator_has_sufficient_credits_to_run_campaign_once(broadcast_type,no_of_audiences,campaign_creator):
    """
    Check that campaign has enough credits to send campaign to all its audiences

    :param campaign: Campaign to perform check for
    """    
    if broadcast_type == "SMS":
        subservice_id = settings.DOWELL_SAMANTHA_CAMPAIGNS_SMS_SUBSERVICE_ID
    elif broadcast_type == "EMAIL":
        subservice_id = settings.DOWELL_SAMANTHA_CAMPAIGNS_MAIL_SUBSERVICE_ID
    else:
        raise ValueError(f"Unsupported Campaign broadcast type: '{broadcast_type}'.")

    return campaign_creator.has_enough_credits_for(
        service=settings.DOWELL_SAMANTHA_CAMPAIGNS_SERVICE_ID, 
        subservices=[subservice_id],
        count=no_of_audiences
    )



def construct_dowell_email_template(
    subject: str,
    body: str,  
    image_url: str = None,
    unsubscribe_link: str = None
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
    if image_url and not is_valid_url(image_url):
        raise ValueError("image_url should be a valid url")
    if unsubscribe_link and not is_valid_url(unsubscribe_link):
        raise ValueError("unsubscribe_link should be a valid url")
    
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
    body_paragraphs = "\n".join(f"<p style='font-size: 14px'>{paragraph.strip()}</p>" for paragraph in body.split("\n\n"))

    return template.format(
        subject=subject.title(),
        body=body_paragraphs,  # Replaced body with paragraphs 
        image_url=image_url or "https://dowellfileuploader.uxlivinglab.online/hr/logo-2-min-min.png",
        unsubscribe_section=unsubscribe_section,
    )


def fetch_email(link: string):
    html_content_data = ''
    try:
        response = requests.get(link)
        response.raise_for_status()
        html_content_data = response.content
        return html_content_data.decode('utf-8')
    except requests.exceptions.RequestException as e:
        return False    


def generate_random_string(length: int = 10):
    """
    Generate a random string of length `length`

    :param length: The length of the string to generate
    """
    if not isinstance(length, int):
        raise TypeError("length should be of type int")
    if length < 1:
        raise ValueError("length should be greater than 0")
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))



# Cache the result of this function for 24 hours since
# it takes a long time to run and there may be duplications
@async_ttl_cache(maxsize=128, ttl_seconds=60*60*24) # cache for 24 hours
async def crawl_url_for_emails_and_phonenumbers(
      url: str,
      crawl_depth: int = 0,
    ):
    """
    Crawl a url for emails and phone numbers 
    using the Dowell Website Crawler API

    :param url: The url to crawl
    :param crawl_depth: The depth to crawl to
    """
    client = httpx.AsyncClient(timeout=60, max_redirects=10)
    response = await client.post(
        url=settings.DOWELL_WEBSITE_CRAWLER_URL,
        json={
            "web_url": url,
            "max_search_depth": crawl_depth,
            "info_request": {
                "phone_numbers": True,
                "emails": True,
            },
        }
    )
    if response.status_code != 200:
        # if response is not 200, return a dictionary with empty phone_numbers and emails
        return {
            "phone_numbers": [],
            "emails": [],
        }
    return response.json()["meta_data"]



def check_webhook_passkey(passkey: str):
    """
    Check if webhook passkey provided is correct
    
    :raises `django.core.exceptions.ValidationError`: if passkey is incorrect
    """
    if passkey != settings.WEBHOOK_PASSKEY:
        raise DjangoValidationError("Incorrect webhook passkey!")
    return None


