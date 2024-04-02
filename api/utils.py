import aiolimiter
import requests
import httpx
import re
from urllib3.util import parse_url
from typing import List
import asyncio
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, URLValidator
from PIL import Image
from django.conf import settings
import threading
from bs4_web_scraper.utils import slice_iterable


from .dowell.user import DowellUser
from .dowell.credits import DeductUserCreditsOnServiceUse

email_api_url = lambda api_key: f"https://100085.pythonanywhere.com/api/v1/mail/{api_key}/"
_async_client = httpx.AsyncClient(timeout=30.0)


def resize_image(path: str, size: str=(300, 300)):
    """
    Resize image to specified size

    :param path: Path to image
    :param size: New size. A tuple of (width, height)
    :return: Path to resized image
    """
    if not isinstance(size, tuple):
        raise TypeError("`size` should be of type tuple(int, int)")
    img = Image.open(path)
    if img.width > size[0] or img.height > size[1]:
        img.thumbnail(size)
        img.save(path)
    return path


async def _get_city_coords(client: httpx.AsyncClient, city_name: str, dowell_api_key: str):
    """
    Async function to get the coordinates of a city using Dowell Coordinates API

    :param city_name: Name of the city.
    :param dowell_api_key: user's dowell client admin api key.
    :return: Tuple of latitude and longitude if city exists, None otherwise
    """
    response = await client.post(
        url=settings.DOWELL_GET_COORDINATES_URL, 
        data={
            "region": city_name,
            "api_key": dowell_api_key,
        }
    )
    if response.status_code == 200:
        coords = response.json()['data']['location']
        return convert_dms_location_to_decimal(coords['lat'], coords['lng'])
    return None


async def _get_cities_coords(cities: List[str], dowell_api_key: str):
    """
    Async function to get the coordinates of a list of cities using Dowell Coordinates API

    :param cities: List of cities.
    :param dowell_api_key: user's dowell client admin api key.
    :return: List of tuples of latitude and longitude if city exists, None otherwise
    """
    async with _async_client as client:
        tasks = [ _get_city_coords(client, city, dowell_api_key) for city in cities ]
        cities_coords = await asyncio.gather(*tasks)
        return cities_coords


def get_cities_coordinates(cities: List[str], dowell_api_key: str):
    """
    Gets the coordinates of a list of cities using Dowell Coordinates API.

    Credit deduction is inbuilt from the API.

    :param cities: List of cities.
    :param dowell_api_key: user's dowell client admin api key.
    :return: List of tuples of latitude and longitude if city exists, None otherwise
    """
    return asyncio.run(_get_cities_coords(cities, dowell_api_key))


def convert_dms_coord_to_decimal(dms_value):
    """
    Convert DMS coordinate to decimal coordinate
    
    :param dms_value: DMS coordinate
    :return: Decimal coordinate
    """
    # Use regular expression to extract degrees, minutes, and direction from the input string
    match = re.match(r'([\d.]+)°\s?(\d+)?[\s\']?([NSEW]?)', dms_value)
    if match:
        degrees = float(match.group(1))
        minutes = float(match.group(2) or 0)
        direction = match.group(3) or ''

        decimal_degrees = degrees + minutes / 60.0

        if direction.upper() in ('S', 'W'):
            decimal_degrees *= -1

        return decimal_degrees
    else:
        raise ValueError("Invalid DMS coordinate format")


def convert_dms_location_to_decimal(latitude, longitude):
    """
    Convert DMS location to decimal location
    
    :param latitude: Latitude in DMS format
    :param longitude: Longitude in DMS format
    :return: Tuple of latitude and longitude in decimal format
    """
    lat_decimal = convert_dms_coord_to_decimal(latitude)
    lon_decimal = convert_dms_coord_to_decimal(longitude)
    return lat_decimal, lon_decimal


def is_email(address: str):
    """
    Checks if the address provided is a valid email address

    :param address: email address to be checked
    :return: True if address is an email address else false
    """
    try:
        EmailValidator()(address)
        return True
    except ValidationError:
        return False


def is_phonenumber(phone_number: str):
    """
    Checks if the phone number provided is a valid phone number

    :param phone_number: phone number to be checked
    :return: True if phone number is valid else false
    """
    match = re.match(
        pattern=r'(?:(?:\+|00)(\d{1,4}))?[\s\-]?(?:(\d{2,4})[\s\-]?(\d{2,4}))[\s\-]?(\d{2,4})', 
        string=phone_number
    )
    return match != None


def is_valid_url(url):
    """
    Check if the url is valid
    """
    try:
        URLValidator()(url)
        return True
    except Exception:
        return False


def get_verified_email(name: str, website: str, dowell_api_key: str):
    """
    Gets and returns a verified email address for the name and website's domain given
    using Dowell Email API.

    Credit deduction is inbuilt from the API.
    
    :param name: name of company whose email is to be gotten
    :param website: company's website url
    :param dowell_api_key: user's dowell client admin api key.
    :return: email if found else None
    """
    if not name:
        raise ValueError("name argument cannot be empty")
    domain = parse_url(website).netloc
    if not domain:
        raise ValueError("Invalid value for website")
    response = requests.post(
        url=email_api_url(dowell_api_key),
        data={
            "name": name,
            "domain": domain,
        }, 
        params={"type": "email-finder"}
    )
    if response.status_code == 200:
        resp_data = response.json()
        if resp_data["success"] == True:
            return resp_data["result"]
    return None


def validate_email(email_address: str, user: DowellUser) -> bool:
    """
    Check is the email address provided is a valid and active email address using Dowell Email API.

    Credit deduction is inbuilt from the API.

    :param email_address: email address to validate
    :param dowell_api_key: user's dowell client admin api key.
    :return: True if valid else False
    """
    if not is_email(email_address):
        raise ValueError("email_address value is not valid")
    
    def validate():
        response = requests.post(
            url=settings.DOWELL_EMAIL_VALIDATOR_URL,
            json={"email": email_address}, 
        )
        if response.status_code == 200:
            return response.json()["success"]
        return False
    
    with DeductUserCreditsOnServiceUse(
        user=user,
        service=settings.DOWELL_SAMANTHA_CAMPAIGNS_SERVICE_ID, 
        subservices=[settings.DOWELL_SAMANTHA_CAMPAIGNS_EMAIL_VALIDATOR_SUBSERVICE_ID], 
        count=1, 
        auto_deduct=not getattr(settings, "DISABLE_DOWELL_AUTO_DEDUCT_CREDITS", False)
    ):
        return validate()
        

def sort_emails_by_validity(emails: List[str], user: DowellUser):
    """
    Sorts a list of emails into two lists of valid and invalid emails using Dowell Email API.
    Duplicate emails are removed before sorting.

    :param emails: list of emails to be sorted
    :param user: DowellUser object representing the user
    :return: Tuple of list of valid emails and list of invalid emails
    """
    if not isinstance(emails, list):
        raise TypeError("`emails` should be of type list[str]")
    emails = list(filter(lambda email: bool(email), emails))
    if not emails:
        raise ValueError("`emails` cannot be empty")
    result = asyncio.run(
        async_sort_emails_by_validity(
            emails=list(set(emails)), 
            user=user, 
            rps=20,
        )
    )
    return result


def _send_mail(
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


def send_mail(
        subject: str, 
        body: str, 
        sender_address: str, 
        recipient_address: str, 
        user: DowellUser,
        sender_name: str = None,
        recipient_name: str = None, 
    ):
    """
    Sends mail using Dowell Email API.

    Credit deduction implemented manually.
    
    :param subject: subject of mail
    :param body: body of mail
    :param sender_address: sender's email address
    :param recipient_address: recipient's email address
    :param user: DowellUser object representing the user
    :param sender_name: sender's name. Defaults to the user's username
    :param recipient_name: recipient's name. Defaults to "Recipient"
    :return: None
    """
    if not isinstance(user, DowellUser):
        raise TypeError("`user` should be of type DowellUser")
        
    # Send and deduct credit if no exception is raised
    with DeductUserCreditsOnServiceUse(
        user=user,
        service=settings.DOWELL_SAMANTHA_CAMPAIGNS_SERVICE_ID, 
        subservices=[settings.DOWELL_SAMANTHA_CAMPAIGNS_MAIL_SUBSERVICE_ID], 
        count=1, 
        auto_deduct=not getattr(settings, "DISABLE_DOWELL_AUTO_DEDUCT_CREDITS", False)
    ):
        return _send_mail(
            subject=subject,
            body=body,
            sender_address=sender_address,
            recipient_address=recipient_address,
            sender_name=sender_name or user.username,
            recipient_name=recipient_name or "Recipient"
        )


def send_mails(
        subject: str,
        body: str,
        sender_address: str,
        recipient_addresses: List[str],
        user: DowellUser,
        sender_name: str = None,
        recipient_names: List[str] = None,
        rps: int = 10,
    ):
    """
    Sends multiple mails using Dowell Email API.

    :param subject: subject of mail
    :param body: body of mail
    :param sender_address: sender's email address
    :param recipient_addresses: list of recipient's email addresses
    :param user: DowellUser object representing the user
    :param sender_name: sender's name
    :param recipient_names: list of recipient's name
    :param rps: rate limit for requests per second. Defaults to 10.
    """
    asyncio.run(
        async_send_mails(
            subject=subject,
            body=body,
            sender_address=sender_address,
            recipient_addresses=recipient_addresses,
            user=user,
            sender_name=sender_name,
            recipient_names=recipient_names,
            rps=rps,
        )
    )
    return None


def send_mails_in_background(
        subject: str,
        body: str,
        sender_address: str,
        recipient_addresses: List[str],
        user: DowellUser,
        sender_name: str = None,
        recipient_names: List[str] = None,
        rps: int = 10,
    ):
    """
    Sends multiple mails using Dowell EMAIL API in a separate Thread in the background.

    :param subject: subject of mail
    :param body: body of mail
    :param sender_address: sender's email address
    :param recipient_addresses: list of recipient's email addresses
    :param user: DowellUser object representing the user
    :param sender_name: sender's name
    :param recipient_names: list of recipient's name. recipient_names[i] is the name of recipient_addresses[i]
    :param rps: rate limit for requests per second. Defaults to 10.
    :return: the Thread object for the thread on which the mails are being sent
    """
    kwargs = {
        "subject": subject,
        "body": body,
        "sender_address": sender_address,
        "recipient_addresses": recipient_addresses,
        "user": user,
        "sender_name": sender_name,
        "recipient_names": recipient_names,
        "rps": rps,
    }
    thread = threading.Thread(target=send_mails, kwargs=kwargs)
    thread.start()
    return thread


def get_data_from_placeids(place_id_list: List[str], dowell_api_key: str):
    """
    Scrapes data using Dowell Maps API from the provided place ids.

    :param place_id_list: a list of place ids for places whose data is to be scraped and returned.
    :param dowell_api_key: user's dowell client admin api key.
    :return: List of dictionaries each containing data scraped.
    """
    if not isinstance(place_id_list, list):
        raise TypeError("Expected type for `place_id_list` is list")
    if place_id_list:
        payload = {
            "place_id_list": place_id_list,
            "api_key": dowell_api_key,
        }
        if payload:
            response = requests.post(
                url="https://100086.pythonanywhere.com/accounts/get-details-list-stage1/", 
                json=payload,
            )
            if response.status_code == 200:
                return response.json()["succesful_results"]
            else:
                response.raise_for_status()
    return []


def send_sms(
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
            "sender" : recipient_name,
            "recipient" : recipient_phone_number,
            "content" : message,
            "created_by" : sender_name
        }
    )
    if response.status_code != 200:
        response.raise_for_status()
    if not response.json()["success"]:
        raise Exception(response.json()["message"])
    return None


def send_multiple_sms(
    message: str,
    sender_phonenumber: str,  
    recipient_phonenumbers: str,
    user: DowellUser, 
    sender_name: str = None,
    recipient_names: str = None,
    rps: int = 10,
):
    """
    Sends multiple SMS using Dowell SMS API.

    Credit deduction is inbuilt from the API.

    :param message: message to be sent
    :param sender_phonenumber: sender's phone number
    :param recipient_phonenumber: recipient's phone number
    :param user: DowellUser object representing the user
    :param sender_name: sender's name
    :param recipient_names: list of recipient's name. recipient_names[i] is the name of recipient_phonenumbers[i]
    :param rps: rate limit for requests per second. Defaults to 10.
    """
    asyncio.run(
        async_send_multiple_sms(
            message=message,
            sender_phonenumber=sender_phonenumber,
            recipient_phonenumbers=recipient_phonenumbers,
            user=user,
            sender_name=sender_name,
            recipient_names=recipient_names,
            rps=rps,
        )
    )
    return None


def send_multiple_sms_in_background(
    message: str,
    sender_phonenumber: str,  
    recipient_phonenumbers: str,
    user: DowellUser, 
    sender_name: str = None,
    recipient_names: str = None,
    rps: int = 10,
):
    """
    Sends multiple SMS using Dowell SMS API in a separate Thread in the background.

    Credit deduction is inbuilt from the API.

    :param message: message to be sent
    :param sender_phonenumber: sender's phone number
    :param recipient_phonenumber: recipient's phone number
    :param user: DowellUser object representing the user
    :param sender_name: sender's name
    :param recipient_names: list of recipient's name. recipient_names[i] is the name of recipient_phonenumbers[i]
    :param rps: rate limit for requests per second. Defaults to 10.
    :return: the Thread object for the thread on which sms are being sent
    """
    kwargs = {
        "message": message,
        "sender_phonenumber": sender_phonenumber,
        "recipient_phonenumbers": recipient_phonenumbers,
        "user": user,
        "sender_name": sender_name,
        "recipient_names": recipient_names,
        "rps": rps,
    }
    thread = threading.Thread(target=send_multiple_sms, kwargs=kwargs)
    thread.start()
    return thread


# ----------------- ASYNCHRONOUS FUNCTIONS --------------------------- #

async def async_get_verified_email(
        name: str, 
        website: str, 
        dowell_api_key: str, 
        client: httpx.AsyncClient = None
    ):
    """
    Gets and returns a verified email address for the name and website's domain given
    using Dowell Email API.

    Credit deduction is inbuilt from the API.
    
    :param name: name of company whose email is to be gotten
    :param website: company's website url
    :param dowell_api_key: user's dowell client admin api key.
    :param client: httpx.AsyncClient instance
    :return: email if found else None
    """
    if not name:
        raise ValueError("name argument cannot be empty")
    domain = parse_url(website).netloc
    if not domain:
        raise ValueError("Invalid value for website")
    if not client:
        client = _async_client
    response = await client.post(
        url=email_api_url(dowell_api_key),
        data={
            "name": name,
            "domain": domain,
        }, 
        params={"type": "email-finder"}
    )
    if response.status_code == 200:
        resp_data = response.json()
        if resp_data["success"] == True:
            return resp_data["result"]
    return None


async def async_validate_email(
        email_address: str, 
        client: httpx.AsyncClient = None,
    ):
    """
    Check is the email address provided is a valid and active email address using Dowell Email API.

    Credit deduction is not implemented here. It is implemented in the function that calls this function.

    :param email_address: email address to validate
    :param user: DowellUser object representing the user
    :param client: httpx.AsyncClient instance
    :return: True if valid else False.
    """
    if not is_email(email_address):
        return False
    if not client:
        client = _async_client
    
    response = await client.post(
        url=settings.DOWELL_EMAIL_VALIDATOR_URL,
        json={"email": email_address}, 
    )
    if response.status_code == 200:
        return response.json()["success"]
    return False


async def async_sort_emails_by_validity(emails: List[str], user: DowellUser, rps: int = 10):
    """
    Async function to sort a list of emails into two lists of valid and invalid emails using Dowell Email API

    Deducts a subservice credit unit for every 100 emails validated

    :param emails: list of emails to be sorted
    :param dowell_api_key: user's dowell client admin api key.
    :param rps: rate limit for requests per second. Defaults to 10.
    """
    limiter = aiolimiter.AsyncLimiter(rps)
    async with limiter:
        async with httpx.AsyncClient() as client:
            tasks = [ async_validate_email(email_address=email, client=client) for email in emails ]
            tasks_batches = slice_iterable(tasks, 100)
            valid = []
            invalid = []
            for tasks_batch in tasks_batches:
                # Deduct a subservice credit unit for every 100 emails validated
                async with DeductUserCreditsOnServiceUse(
                    user=user,
                    service=settings.DOWELL_SAMANTHA_CAMPAIGNS_SERVICE_ID, 
                    subservices=[settings.DOWELL_SAMANTHA_CAMPAIGNS_EMAIL_VALIDATOR_SUBSERVICE_ID], 
                    count=1, 
                    auto_deduct=not getattr(settings, "DISABLE_DOWELL_AUTO_DEDUCT_CREDITS", False)
                ):
                    results = await asyncio.gather(*tasks_batch)
                    for email, result in zip(emails, results):
                        if result:
                            valid.append(email)
                        else:
                            invalid.append(email)
            return valid, invalid


async def async_send_mail(
        subject: str, 
        body: str, 
        sender_address: str, 
        recipient_address: str, 
        user: DowellUser,
        sender_name: str = None,
        recipient_name: str = None, 
        client: httpx.AsyncClient = None,
    ):
    """
    Sends mail using Dowell Email API.

    Credit deduction was implemented manually.

    :param subject: subject of mail
    :param body: body of mail
    :param sender_address: sender's email address
    :param recipient_address: recipient's email address
    :param user: DowellUser object representing the user
    :param sender_name: sender's name
    :param recipient_name: recipient's name. Defaults to None.
    :param client: httpx.AsyncClient instance
    :return: None
    """
    for address in (recipient_address, sender_address):
        if not is_email(address):
            raise ValidationError(f"{address} is not a valid email address!")
    if not body:
        raise ValueError("body of mail cannot be empty")
    if not isinstance(user, DowellUser):
        raise TypeError("`user` should be of type DowellUser")
    
    if not client:
        client = _async_client

    async def send():
        response = await client.post(
            url=settings.DOWELL_MAIL_URL,
            data={
                "toname": recipient_name or "Recipient",
                "toemail": recipient_address,
                "fromname": sender_name or user.username,
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
        
    # Send and deduct credit if no exception is raised
    with DeductUserCreditsOnServiceUse(
        user=user,
        service=settings.DOWELL_SAMANTHA_CAMPAIGNS_SERVICE_ID, 
        subservices=[settings.DOWELL_SAMANTHA_CAMPAIGNS_MAIL_SUBSERVICE_ID], 
        count=1, 
        auto_deduct=not getattr(settings, "DISABLE_DOWELL_AUTO_DEDUCT_CREDITS", False)
    ):
        return await send()
    

async def async_send_mails(
        subject: str,
        body: str,
        sender_address: str,
        recipient_addresses: List[str],
        user: DowellUser,
        sender_name: str = None,
        recipient_names: List[str] = None,
        rps: int = 10,
    ):
    """
    Sends mails asynchronously using Dowell Email API.

    Credit deduction was implemented manually.

    :param subject: subject of mail
    :param body: body of mail
    :param sender_address: sender's email address
    :param recipient_addresses: list of recipient's email addresses
    :param user: DowellUser object representing the user
    :param sender_name: sender's name
    :param recipient_names: list of recipient's name. recipient_names[i] is the name of recipient_addresses[i]
    :param rps: rate limit for requests per second. Defaults to 10.
    """
    if not isinstance(recipient_addresses, list):
        raise TypeError("`recipient_addresses` should be of type list[str]")
    if not recipient_addresses:
        raise ValueError("`recipient_addresses` cannot be empty")
    if recipient_names and not isinstance(recipient_names, list):
        raise TypeError("`recipient_names` should be of type list[str]")
    if not isinstance(rps, int):
        raise TypeError("`rps` should be of type int")
    if not rps > 0:
        raise ValueError("`rps` should be greater than 0")
    if not isinstance(user, DowellUser):
        raise TypeError("`user` should be of type DowellUser")
    
    if not recipient_names:
        recipient_names = [None] * len(recipient_addresses)
    
    limiter = aiolimiter.AsyncLimiter(rps)
    async with limiter:
        async with httpx.AsyncClient() as client:
            tasks = [
                async_send_mail(
                    subject=subject,
                    body=body,
                    sender_address=sender_address,
                    recipient_address=recipient_address,
                    sender_name=sender_name,
                    user=user,
                    recipient_name=recipient_name,
                    client=client,
                )
                for recipient_address, recipient_name in zip(recipient_addresses, recipient_names)
            ]
            ensure_prerequisites_met_before_service_use = DeductUserCreditsOnServiceUse(
                user=user, 
                service=settings.DOWELL_SAMANTHA_CAMPAIGNS_SERVICE_ID, 
                subservices=[settings.DOWELL_SAMANTHA_CAMPAIGNS_MAIL_SUBSERVICE_ID],
                count=len(tasks), 
                auto_deduct=False, 
                suppress_exc=False
            )
            # Use the context manager to ensure that all prerequisites are met before continuing
            async with ensure_prerequisites_met_before_service_use:
                return await asyncio.gather(*tasks)


async def async_send_sms(
        message: str,
        sender_phonenumber: str,  
        recipient_phonenumber: str,
        user: DowellUser, 
        sender_name: str = None,
        recipient_name: str = None,
        client: httpx.AsyncClient = None,
    ):
    """
    Sends SMS using Dowell SMS API.

    Credit deduction is inbuilt from the API.

    :param message: message to be sent
    :param sender_phonenumber: sender's phone number
    :param recipient_phonenumber: recipient's phone number
    :param user: DowellUser object representing the user
    :param sender_name: sender's name
    :param recipient_name: recipient's name
    :param client: httpx.AsyncClient instance
    """
    if not message:
        raise ValueError("message cannot be empty")
    if not recipient_phonenumber:
        raise ValueError("recipient_phonenumber cannot be empty")
    if not sender_phonenumber:
        raise ValueError("sender_phonenumber cannot be empty")
    if not isinstance(user, DowellUser):
        raise TypeError("`user` should be of type DowellUser")
    
    for number in (recipient_phonenumber, sender_phonenumber):
        if not is_phonenumber(number):
            raise ValidationError(f"{number} is not a valid phone number!")
    if not client:
        client = _async_client
    response = await client.post(
        url=f"https://100085.pythonanywhere.com/api/v1/dowell-sms/{settings.PROJECT_API_KEY}/", 
        json={
            "sender" : recipient_name or "Recipient",
            "recipient" : recipient_phonenumber,
            "content" : message,
            "created_by" : sender_name or user.username
        }
    )
    if response.status_code != 200:
        response.raise_for_status()
    if not response.json()["success"]:
        raise Exception(response.json()["message"])
    return None


async def async_send_multiple_sms(
        message: str,
        sender_phonenumber: str,  
        recipient_phonenumbers: str,
        user: DowellUser, 
        sender_name: str = None,
        recipient_names: str = None,
        rps: int = 10,
    ):
    """
    Sends multiple SMS asynchronously using Dowell SMS API.

    Credit deduction is inbuilt from the API.

    :param message: message to be sent
    :param sender_phonenumber: sender's phone number
    :param recipient_phonenumber: recipient's phone number
    :param user: DowellUser object representing the user
    :param sender_name: sender's name
    :param recipient_names: list of recipient's name. recipient_names[i] is the name of recipient_phonenumbers[i]
    :param rps: rate limit for requests per second. Defaults to 10.
    """
    if not isinstance(recipient_phonenumbers, list):
        raise TypeError("`recipient_phonenumbers` should be of type list[str]")
    if not recipient_phonenumbers:
        raise ValueError("`recipient_phonenumbers` cannot be empty")
    if recipient_names and not isinstance(recipient_names, list):
        raise TypeError("`recipient_names` should be of type list[str]")
    if not isinstance(rps, int):
        raise TypeError("`rps` should be of type int")
    if not rps > 0:
        raise ValueError("`rps` should be greater than 0")
    if not isinstance(user, DowellUser):
        raise TypeError("`user` should be of type DowellUser")
    
    if not recipient_names:
        recipient_names = [None] * len(recipient_phonenumbers)

    limiter = aiolimiter.AsyncLimiter(rps)
    async with limiter:
        async with httpx.AsyncClient() as client:
            tasks = [
                async_send_sms(
                    message=message,
                    sender_phonenumber=sender_phonenumber,
                    recipient_phonenumber=recipient_phonenumber,
                    user=user,
                    sender_name=sender_name,
                    recipient_name=recipient_name,
                    client=client
                )
                for recipient_phonenumber, recipient_name in zip(recipient_phonenumbers, recipient_names)
            ]
            ensure_prerequisites_met_before_service_use = DeductUserCreditsOnServiceUse(
                user=user, 
                service=settings.DOWELL_SMS_SERVICE_ID, 
                count=len(tasks), 
                auto_deduct=False, 
                suppress_exc=False
            )
            # Use the context manager to ensure that all prerequisites are met before continuing
            async with ensure_prerequisites_met_before_service_use:
                return await asyncio.gather(*tasks)
