import sys
from typing import List
from django.utils import timezone, functional
import datetime
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
import os
import traceback
import math
import aiolimiter
import httpx
import asyncio
from urllib.parse import urljoin


from api.datacube.objects import DatacubeObject
from api.objects.objectlist import ObjectList, as_manager
from api.objects.signals import ObjectSignal
from api.dowell.user import DowellUser
from api.dowell.credits import DeductUserCreditsOnServiceUse
from api.validators import (
    validate_url, validate_not_blank, 
    validate_email_or_phone_number,
    is_email, is_phonenumber,
    MinMaxLengthValidator
)
from api.objects.utils import ttl_cache, get_logger
from api.utils import async_send_mail, async_send_sms, _send_mail
from api.objects.db import ObjectDatabase
from .objectlists import CampaignList, CampaignAudienceList, CampaignAudienceLeadsLinkList
from reports.dbobjects import CampaignRunReport
from .utils import (
    construct_dowell_email_template, 
    crawl_url_for_emails_and_phonenumbers,
    fetch_email, 
    generate_random_string,
    check_campaign_creator_has_sufficient_credits_to_run_campaign_once
)


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


@as_manager(CampaignList)
class Campaign(DatacubeObject):
    """Campaign Object"""
    config = DatacubeObject.new_config()
    config.attributes = {
        "type": (str,),
        "broadcast_type": (str,),
        "title": (str,),
        "purpose": (str,),
        "image": (str,),
        "creator_id": (str,), # workspace ID of DowellUser
        "keyword": (str,),
        "target_city": (str,),
        "range": (int, float),
        "frequency": (str,),
        "audiences": (CampaignAudienceList,),
        "leads_links": (CampaignAudienceLeadsLinkList,),
        "is_active": (bool,),
        "start_date": (datetime.date,),
        "end_date": (datetime.date,),
        "last_due_date": (datetime.date,),
        "created_at": (datetime.datetime,),
        "updated_at": (datetime.datetime,),
        "launched_at": (datetime.datetime,),
        "last_ran_at": (datetime.datetime,),
        "is_running": (bool,),
        "default_message": (bool,),
    }
    config.choices = {
        "broadcast_type": ("EMAIL", "SMS"),
        "frequency": ("DAILY", "WEEKLY", "FORTNIGHTLY", "MONTHLY", "QUARTERLY", "HOURLY"),
    }
    config.required = (
        "title",
        "creator_id",
        "start_date",
        "end_date",
        # "keyword", # Not required for now till living lab maps is available
    )
    config.defaults = {
        "broadcast_type": "EMAIL",
        "frequency": "HOURLY",
        "created_at": timezone.now,
        "is_active": False,
        "is_running": False,
    }
    config.validators = {
        "title": [validate_not_blank, min_max(min_length=3, max_length=255)],
        "type": [validate_not_blank, min_max(min_length=3, max_length=100)],
        "broadcast_type": [validate_not_blank, min_max(min_length=3, max_length=5)],
        "image": [validate_url],
        "keyword": [validate_not_blank, min_max(min_length=3, max_length=100)],
        "purpose": [validate_not_blank, min_max(min_length=5, max_length=2000)],
        "creator_id": [validate_not_blank], # is_valid_workspace_id - will slow down object creation, retrieval and update
    }
    config.ordering = ("-created_at",)
    config.auto_now_datetimes = ("updated_at",)

    def __init__(self, **attrs):
        super().__init__(**attrs)
        if not self.audiences:
            self.audiences = CampaignAudienceList(object_class="campaigns.dbobjects.CampaignAudience")
        if not self.leads_links:
            self.leads_links = CampaignAudienceLeadsLinkList(object_class="campaigns.dbobjects.CampaignAudienceLeadsLink")
        return None

    # Cache the campaign creator object. Since the creator_id will most likely not change, we can cache the first result
    # and then use it for subsequent calls
    @functional.cached_property
    def creator(self):
        """DowellUser object that created this campaign"""
        return DowellUser(workspace_id=self.creator_id)
    
    @property
    def no_of_audiences(self) -> int:
        """Returns number of audiences for this campaign"""
        return len(self.audiences)
    
    @property
    def has_audiences(self) -> bool:
        """Returns True if campaign has audiences"""
        return self.no_of_audiences > 0

    @property
    def has_launched(self):
        """Check if campaign has been launched"""
        return bool(self.launched_at)

    @property
    def timedelta(self):
        """Returns the timedelta object for the campaign frequency"""
        return self.get_timedelta_from_type(self.frequency)
    
    @property
    def next_due_date(self):
        """Returns the next date when an active campaign is due"""
        # If campaign has never been due before, then return today's date
        if not self.last_due_date:
            return timezone.now().date()
        return self.last_due_date + self.timedelta

    @classmethod
    def get_timedelta_from_type(cls, frequency: str):
        """Returns the timedelta object for the campaign"""
        if frequency not in cls.config.choices["frequency"]:
            raise ValueError(f"Campaign frequency must be one of {cls.choices['frequency']}")
    
        if frequency == "DAILY":
            return datetime.timedelta(days=1)
        elif frequency == "WEEKLY":
            return datetime.timedelta(weeks=1)
        elif frequency == "FORTNIGHTLY":
            return datetime.timedelta(weeks=2)
        elif frequency == "MONTHLY":
            return datetime.timedelta(weeks=4)
        elif frequency == "QUARTERLY":
            return datetime.timedelta(weeks=12)
        return None
    

    def is_launchable(self, dowell_api_key: str = None):
        """
        Returns True if campaign can be launched, gives reason why or why not
        and percentage of readiness to launch

        :param dowell_api_key: Optional Dowell API key to use for check, 
        if not provided, the campaign creator's API key is used.
        """
        ans = not self.has_launched
        if not ans:
            return ans, "Campaign has already been launched", 100
        
        percentage_ready = 0.000
        ans = self.get_message(dowell_api_key=dowell_api_key) is not None
        if not ans:
            return ans, "Campaign has no message", math.ceil(percentage_ready)
        percentage_ready += 25.000
        
        service_id = settings.DOWELL_MAIL_SERVICE_ID if self.broadcast_type == "EMAIL" else settings.DOWELL_SMS_SERVICE_ID
        campaign_creator = self.creator
        ans = campaign_creator.check_service_active(service_id)
        service = campaign_creator.get_service(service_id)
        if not ans:
            return ans, f"DowellService '{service}' is not active.", math.ceil(percentage_ready)
        percentage_ready += 25.000
        
        if not self.leads_links.uncrawled().empty:
            return False, "Some leads links have not been crawled", math.ceil(percentage_ready)
        percentage_ready += 25.000

        ans = check_campaign_creator_has_sufficient_credits_to_run_campaign_once(self.broadcast_type,self.no_of_audiences,campaign_creator)
        if not ans:
            return ans, "You do not have sufficient credits to run this campaign. Please top up.", math.ceil(percentage_ready)
        percentage_ready += 25.000

        return ans, "Campaign can be launched", math.ceil(percentage_ready)
    

    def is_runnable(self, dowell_api_key: str = None):
        """
        Returns True if campaign can be run and give reason why or why not

        :param dowell_api_key: Optional Dowell API key to use for check,
        if not provided, the campaign creator's API key is used.
        """
        ans = not self.is_running
        if not ans:
            return ans, "Campaign is already running"
        
        ans = self.is_active
        if not ans:
            return ans, "Campaign is not active"

        ans = self.has_launched
        if not ans:
            return ans, "Campaign has not been launched"
        
        service_id = settings.DOWELL_MAIL_SERVICE_ID if self.broadcast_type == "EMAIL" else settings.DOWELL_SMS_SERVICE_ID
        campaign_creator = self.creator 
        ans = campaign_creator.check_service_active(service_id)
        service = campaign_creator.get_service(service_id)
        if not ans:
            return ans, f"DowellService '{service}' is not active."
        
        ans = check_campaign_creator_has_sufficient_credits_to_run_campaign_once(self)
        if not ans:
            return ans, "You do not have sufficient credits to run this campaign. Please top up."
        return ans, "Campaign can be run"
    

    def is_due(self, *, padding: int | float | None = None):
        """
        Returns True if campaign is due. That is, if the current date is the next due date
        
        :param padding: The number of days to add to the current date to get the due date. 
        This is useful for checking if a campaign is due at a future or past date (negative padding).
        """
        if padding is None:
            padding = 0
        todays_date_plus_padding = timezone.now().date() + timezone.timedelta(days=padding)
        return self.next_due_date == todays_date_plus_padding
    

    def is_expired(self):
        """Returns True if campaign has expired"""
        return self.end_date < timezone.now().date()
    

    def due_today(self, *, save: bool = True, dowell_api_key: str = None):
        """
        Set campaign's `last_due_date` attribute to today's date if campaign is due today

        :param save: whether to save the campaign after setting last due date
        :param dowell_api_key: Optional Dowell API key to use for check,
        if not provided, the campaign creator's API key is used.
        """
        if self.is_due():
            self.last_due_date = timezone.now().date()

        if save:
            dowell_api_key = dowell_api_key if dowell_api_key else self.creator.api_key
            self.save(dowell_api_key=dowell_api_key)
        return None
    

    @ttl_cache(maxsize=12, ttl_seconds=60*60*24)
    def get_message(self, dowell_api_key: str = None) -> "CampaignMessage":
        """
        Campaign message object associated with this campaign

        :param dowell_api_key: Optional Dowell API key to use for retrieving campaign message. 
        If not provided, the campaign creator's API key is used.
        :returns: Campaign message object associated with this campaign 
        or None if no message is associated with this campaign
        """
        workspace_id = self.creator_id
        dowell_api_key = dowell_api_key if dowell_api_key else self.creator.api_key
        msg = CampaignMessage.manager.filter(campaign_id=self.pkey, dowell_api_key=dowell_api_key,workspace_id=workspace_id, wanted="message").first()
        return msg
    

    def get_reports(self, dowell_api_key: str = None) -> ObjectList["CampaignRunReport"]:
        """
        Returns a list of reports for this campaign.

        :param dowell_api_key: Optional Dowell API key to use for retrieving campaign reports.
        If not provided, the campaign creator's API key is used.
        """
        dowell_api_key = dowell_api_key if dowell_api_key else self.creator.api_key
        reports = CampaignRunReport.manager.filter(campaign_id=self.pkey, dowell_api_key=dowell_api_key)
        return reports
    
    
    def save(self, dowell_api_key: str = None, using: ObjectDatabase = None):
        if self.saved:
            try:
                #todo change this
                workspace_id=self.creator_id
                print("id before getting old",workspace_id)
                workspace_id=self.creator_id
                old_instance = Campaign.manager.get(pkey=self.pkey, dowell_api_key=settings.PROJECT_API_KEY,workspace_id=workspace_id)
            except Campaign.DoesNotExist:
                old_instance = None
            if old_instance:
                # Ensure that launch date is not changed after campaign has been launched
                if old_instance.has_launched and old_instance.launched_at != self.launched_at:
                    raise DjangoValidationError("You cannot change the launch date of a campaign after it has launched")
                # If a new start date is specified then reset last_due_date
                if old_instance.start_date != self.start_date:
                    self.last_due_date = None

        if self.is_expired(): # if campaign end date is in the past, deactivate campaign
            try:
                self.deactivate(save=False)
            except:
                pass
        print("the id workspace id",workspace_id)
        # get creator_id to use to save a campaign to creator's collection
        # If no api is not provided use campaign creator's api key
        dowell_api_key = dowell_api_key if dowell_api_key else self.creator.api_key
        return super().save(using=using, dowell_api_key=dowell_api_key , workspace_id=workspace_id)
    

    def delete(self, dowell_api_key: str = None, using: ObjectList = None):
        """
        Delete campaign and all related objects

        :param dowell_api_key: Optional Dowell API key to use for deleting campaign.
        If not provided, the campaign creator's API key is used.
        """
        workspace_id = self.creator_id
        dowell_api_key = dowell_api_key if dowell_api_key else self.creator.api_key
        message = self.get_message(dowell_api_key=settings.PROJECT_API_KEY)
        if message:
            message.delete(using=using, dowell_api_key=dowell_api_key,workspace_id=workspace_id)
        return super().delete(using=using, dowell_api_key=dowell_api_key,workspace_id=workspace_id)
    

    def validate(self):
        if self.start_date > self.end_date:
            raise DjangoValidationError(
                "`start_date` cannot be greater that `end_date`. You cannot schedule a campaign to start after it has ended"
            )
        if self.timedelta and (self.end_date - self.start_date) < self.timedelta:
            raise DjangoValidationError(
                f"You cannot schedule this to run {self.frequency.lower()} because the difference between `start_date` and `end_date` is less than a {self.frequency.replace('LY', '').lower()}."
            )
        return super().validate()
    

    def serialize(self):
        serialized = super().serialize()
        serialized["id"] = serialized.pop("pkey")
        # Convert audiences to their dictionary representation
        serialized["audiences"] = [ audience.data for audience in self.audiences ]
        serialized["leads_links"] = [ leads_link.data for leads_link in self.leads_links ]
        serialized["has_launched"] = self.has_launched
        return serialized


    def activate(self, save: bool = True, dowell_api_key: str = None):
        """
        Activate campaign. The campaign must have been launched.
        Activating a campaign means that the campaign is now allowed to run when due
        
        :param save: whether to save campaign after activating it
        :param dowell_api_key: Optional Dowell API key to use for activating campaign.
        If not provided, the campaign creator's API key is used.
        """
        if self.is_active:
            raise DjangoValidationError("Campaign is already active")
        if not self.has_audiences:
            raise DjangoValidationError("Campaign cannot be activated because it has no audiences")
        if not self.has_launched:
            raise DjangoValidationError("Campaign cannot be activated because it has not been launched")
        if self.end_date < timezone.now().date():
            raise DjangoValidationError("Campaign cannot be activated because it has already ended")
        
        self.is_active = True
        if save:
            dowell_api_key = dowell_api_key if dowell_api_key else self.creator.api_key
            self.save(dowell_api_key=dowell_api_key)

        campaign_activated.send(sender=self.__class__, instance=self)
        return None
    

    def deactivate(self, save: bool = True, dowell_api_key: str = None):
        """
        Deactivate campaign. The campaign must have been launched.
        Deactivating a campaign means that the campaign is not allowed to run when due
        
        :param save: whether to save campaign after deactivating it
        :param dowell_api_key: Optional Dowell API key to use for deactivating campaign.
        If not provided, the campaign creator's API key is used.
        """
        if not self.is_active:
            raise DjangoValidationError("Campaign is already inactive")
        
        self.is_active = False
        if save:
            dowell_api_key = dowell_api_key if dowell_api_key else self.creator.api_key
            self.save(dowell_api_key=dowell_api_key)

        campaign_deactivated.send(sender=self.__class__, instance=self)
        return None
    

    def launch(self, dowell_api_key: str = None):
        """
        Launch campaign. 
        
        Launching a campaign means giving a campaign initial permission to run when the set schedule is due. 
        The campaign is automatically activated after launch.

        :param dowell_api_key: Optional Dowell API key to use for launching campaign.
        If not provided, the campaign creator's API key is used.
        """
        dowell_api_key = dowell_api_key if dowell_api_key else self.creator.api_key
        self.creator.credits = 12345678 # TODO: Remove this line
        can_launch, reason, _ = self.is_launchable(dowell_api_key=settings.PROJECT_API_KEY)
        if not can_launch:
            raise DjangoValidationError(f"Campaign cannot be launched. {reason}")
        
        self.launched_at = timezone.now() # Set time of launch
        self.activate(save=False)
        self.save(dowell_api_key=dowell_api_key)

        campaign_launched.send(sender=self.__class__, instance=self)
        return None
    
    
    def _prerun(self):
        """Runs necessary checks before running campaign"""
        self.creator.credits = 12345678 # TODO: Remove this line
        can_run, reason = self.is_runnable(dowell_api_key=settings.PROJECT_API_KEY)

        if not can_run:
            # Send email to campaign creator to notify them that campaign cannot be run
            try:
                _send_mail(
                    subject=f"Campaign Run Failed for '{self.title.title()}'",
                    body=construct_dowell_email_template(
                        subject="Campaign Update",
                        body=f"Your campaign, '{self.title}', cannot run.<br><br><b>Reason:</b> {reason}",
                        recipient=self.creator.email
                    ),
                    sender_address=settings.PROJECT_EMAIL,
                    recipient_address=self.creator.email,
                    sender_name=settings.PROJECT_NAME,
                    recipient_name=self.creator.username,
                )
            except:
                pass
            raise DjangoValidationError(f"Campaign cannot be run. {reason}")
        return None
    

    def _started_running(self):
        """
        Called when the campaign starts running. 
        Just about when the campaign's message is broadcasted to all subscribers(audiences).

        :return: `CampaignRunReport` to be used while the campaign runs
        """
        # Send campaign started running signal before campaign messages are sent
        self.is_running = True
        self.last_ran_at = timezone.now()
        self.save(dowell_api_key=settings.PROJECT_API_KEY)
        # Create a new run report for campaign but do not save it yet
        run_report: CampaignRunReport = CampaignRunReport.manager.create(
            campaign_id=self.pkey, 
            title=f"New Run Report for Campaign: '{self.title.title()}'",
            save=False
        )
        event_data = {
            "detail": f"Campaign: '{self.title.title()}', started running.",
        }
        run_report.add_event(event_type="INFO", data=event_data)
        # Do not save the report yet until campaign has finished running
        campaign_started_running.send(
            sender=self.__class__, 
            instance=self, 
            run_report=run_report
        )
        return run_report


    def _stopped_running(self, run_report: CampaignRunReport, exc: Exception = None):
        """
        Called when the campaign stops running. 
        After the campaign's message has been broadcasted to all subscribers(audiences).

        :param run_report: `CampaignRunReport` used while the campaign was running.
        :param exc: Exception that occurred while the campaign was running.
        """
        self.is_running = False
        try:
            event_data = {
                "detail": f"Campaign: '{self.title.title()}', stopped running.",
                "error": str(exc),
            }
            run_report.add_event(event_type="ERROR", data=event_data)
            # Save the report used while running
            run_report.save(dowell_api_key=settings.PROJECT_API_KEY)
        except:
            raise
        finally:
            # Ensure that campaign is saved even if an error occurs
            self.save(dowell_api_key=settings.PROJECT_API_KEY)

        # Finally, Send campaign stopped running signal 
        # irrespective of whether an error occurred or not
        campaign_stopped_running.send(
            sender=self.__class__, 
            instance=self,
            run_report=run_report, 
            exception=exc
        )
        return None


    def run(
            self, 
            raise_exception: bool = False, 
            log_errors: bool = True,
            dowell_api_key: str = None
        ):
        """
        Run campaign. Send messages to campaign audiences
        
        :param raise_exception: whether to raise exception if an error occurs while sending campaign message
        :param log_errors: whether to log errors that occur while running campaign
        :param dowell_api_key: Optional Dowell API key to use for running campaign.
        If not provided, the campaign creator's API key is used.
        """
        self._prerun()
        dowell_api_key = dowell_api_key if dowell_api_key else self.creator.api_key

        logger = get_logger(
            name="campaigns", 
            logfile_path=os.path.join(settings.LOG_PATH, f"run_campaigns_{timezone.now().date().isoformat()}.log"),
            base_level="ERROR"
        ) # Logs campaign run errors

        e = None
        run_report = self._started_running()
        try:
            message = self.get_message(dowell_api_key=dowell_api_key)
            subscribers = self.audiences.subscribed()
            message.send(to=subscribers, report=run_report)

        except Exception as exc:
            e = exc
            if log_errors:
                logger.error(traceback.format_exc())
            if raise_exception:
                raise exc
            
        finally:
            self._stopped_running(exc=e, run_report=run_report)
        return None
    

    def add_audience(self, contact: str):
        """
        Add audience to campaign
        
        :param contact: email or phone number of audience to add
        """
        if self.broadcast_type.lower() == "sms":
            audience = CampaignAudience(phonenumber=contact)
        else:
            audience = CampaignAudience(email=contact)

        self.audiences.append(audience)
        return None

    
    def add_leads_link(self, url: str):
        """
        Add leads link to campaign
        
        :param url: link to leads page
        """
        leads_link = CampaignAudienceLeadsLink(url=url)
        self.leads_links.append(leads_link)
        return None
    

    def crawl_leads_links_and_update_audiences(self, crawl_depth: int = 0):
        """
        Crawl leads links for audiences. Add audiences found to campaign audiences. 
        Do not forget to save after calling this method.

        :param crawl_depth: The depth to crawl the links
        """
        results = self.leads_links.crawl(
            campaign_creator=self.creator, 
            crawl_depth=crawl_depth
        )
        for result in results:
            if self.broadcast_type.lower() == "sms":
                phonenumbers = result.get("phone_numbers", [])
                for phonenumber in phonenumbers:
                    self.add_audience(contact=phonenumber)

            elif self.broadcast_type.lower() == "email":
                emails = result.get("emails", [])
                for email in emails:
                    self.add_audience(contact=email)
        return None



@as_manager(CampaignAudienceList)
class CampaignAudience(DatacubeObject):
    """
    Campaign Audience Object

    This is not meant to be saved in the database but to be used to represent
    audiences in a campaign so actions can be performed on them just like any
    other Object.
    """
    config = DatacubeObject.new_config()
    # Do not migrate this Object class to the datacube database
    config.migrate = False

    config.attributes = {
        "id": (str,),
        "phonenumber": (str,),
        "email": (str,),
        "is_subscribed": (bool,),
        "added_at": (datetime.datetime,),
    }
    config.defaults = {
        "id": generate_random_string,
        "added_at": timezone.now,
        "is_subscribed": True,
    }
    config.validators = {
        "phonenumber": [validate_not_blank, is_phonenumber],
        "email": [validate_not_blank, is_email],
    }
    config.ordering = ("-added_at",)
    
    def serialize(self):
        serialized = super().serialize()
        serialized.pop("pkey", None)
        return serialized
    

    def subscribe(self):
        """Subscribe audience to campaign"""
        if self.is_subscribed:
            raise DjangoValidationError("Audience is already subscribed")
        self.is_subscribed = True
        return None

    
    def unsubscribe(self):
        """Unsubscribe audience from campaign"""
        if not self.is_subscribed:
            raise DjangoValidationError("Audience is already unsubscribed")
        self.is_subscribed = False
        return None


    def save(self, dowell_api_key: str = None, using = None):
        raise Exception("CampaignAudience objects cannot be saved")

    def delete(self, *, dowell_api_key: str, using = None):
        raise Exception("CampaignAudience objects cannot be deleted")



@as_manager(CampaignAudienceLeadsLinkList)
class CampaignAudienceLeadsLink(DatacubeObject):
    """
    Campaign Audience Leads Link Object.

    This is not meant to be saved in the database but to be used to represent
    leads links in a campaign so actions can be performed on them just like any
    other Object.
    """
    config = DatacubeObject.new_config()
    config.migrate = False
    config.attributes = {
        "id": (str,),
        "url": (str,),
        "is_crawled": (bool,),
        "added_at": (datetime.datetime,),
    }
    config.defaults = {
        "id": generate_random_string,
        "added_at": timezone.now,
        "is_crawled": False,
    }
    config.validators = {
        "url": [validate_not_blank, validate_url],
    }
    config.ordering = ("-added_at",)
    
    def serialize(self):
        serialized = super().serialize()
        serialized.pop("pkey", None)
        return serialized
    

    def save(self, dowell_api_key: str = None, using = None):
        raise Exception("CampaignAudienceLeadsLink objects cannot be saved")

    def delete(self, *, dowell_api_key: str, using = None):
        raise Exception("CampaignAudienceLeadsLink objects cannot be deleted")
    

    def crawl(self, *, campaign_creator: str | DowellUser, crawl_depth: int = 0):
        """
        Crawl leads page for audiences if not already crawled

        :param campaign_creator: Workspace ID of or DowellUser object of 
        creator of the campaign this leads link belongs to.
        :param crawl_depth: The depth to crawl the links
        """
        return asyncio.run(
            self.acrawl(
                campaign_creator=campaign_creator,
                crawl_depth=crawl_depth
            )
        )
    

    async def acrawl(self, *, campaign_creator: str | DowellUser, crawl_depth: int = 0):
        """
        Asynchronously crawl leads page for audiences if not already crawled

        :param campaign_creator: Workspace ID of or DowellUser object of 
        creator of the campaign this leads link belongs to.
        :param crawl_depth: The depth to crawl the links
        """
        async with DeductUserCreditsOnServiceUse(
            user=campaign_creator, 
            service=settings.DOWELL_SAMANTHA_CAMPAIGNS_SERVICE_ID,
            subservices=[settings.DOWELL_WEBSITE_CRAWLER_SUBSERVICE_ID],
            count=1,
            auto_deduct=not getattr(settings, "DISABLE_DOWELL_AUTO_DEDUCT_CREDITS", False)
        ):  
            sys.stdout.write(self.url)
            result = await crawl_url_for_emails_and_phonenumbers(url=self.url, crawl_depth=crawl_depth)
            self.is_crawled = True
            return result


class CampaignMessage(DatacubeObject):
    """Campaign Message Object"""
    config = DatacubeObject.new_config()
    config.attributes = {
        "campaign_id": (str,),
        "type": (str,),
        "subject": (str,),
        "body": (str,),
        "sender": (str,),
        "created_at": (datetime.datetime,),
        "updated_at": (datetime.datetime,),
        "is_default": (bool,),
        "is_html_email": (bool,),
        "html_email_link": (str,),
    }
    config.choices = {
        "type": ("EMAIL", "SMS"),
    }
    config.required = (
        "campaign_id",
        "type",
        "subject",
        "body",
        "sender",
    )
    config.defaults = {
        "created_at": timezone.now,
    }
    config.validators = {
        "campaign_id": [validate_not_blank],
        "type": [validate_not_blank, min_max(min_length=3, max_length=5)],
        "subject": [validate_not_blank, min_max(min_length=3, max_length=255)],
        "body": [validate_not_blank, min_max(min_length=10, max_length=5000)],
        "sender": [validate_email_or_phone_number],
    }
    config.ordering = ("-created_at",)
    config.auto_now_datetimes = ("updated_at",)
    
    # Cache the campaign object. Since the campaign_id will most likely not change,
    #  we can cache the first result and then use it for subsequent calls
    @ttl_cache(maxsize=12, ttl_seconds=60*60*24)
    def get_campaign(self, dowell_api_key: str) -> Campaign:
        """
        Campaign object associated with this message

        :param dowell_api_key: Dowell API key to use for retrieving campaign.
        """
        workspace_id = self.creator_id
        print("Check for campaign GET", workspace_id)
        return Campaign.manager.get(pkey=self.campaign_id, dowell_api_key=dowell_api_key,workspace_id=workspace_id)
    

    def validate(self):
        # validating user data
        if self.type is not None:
            if self.type.lower() == "email":
                # Do not append, replace. This because if the type is changed from email to sms,
                # the sender will still be validated as email and vice versa
                self.config.validators["sender"] = [is_email]
            else:
                self.config.validators["sender"] = [is_phonenumber]
        return super().validate()


    def serialize(self):
        serialized = super().serialize()
        serialized["id"] = serialized.pop("pkey")
        return serialized


    def send(
            self, 
            to: ObjectList[CampaignAudience] | CampaignAudience, 
            *,
            limit: int = 0,
            report: CampaignRunReport = None
        ):    
        """
        Send message to campaign audience(s)

        :param to: campaign audience or ObjectList of campaign audiences to send message to.
        :param limit: maximum number of messaged recipients. Set to 0 to send to all audiences.
        :param report: `CampaignRunReport` to be used to record sending process if provided.
        """

        if not self.sender:
            raise DjangoValidationError("Message sender cannot be empty.")
            
        recipients = list(to)
        if limit > 0:
            recipients = recipients[:limit]

        if report:
            report.add_event(
                event_type="INFO", 
                data={
                    "detail": f"Started {self.type} broadcast to {len(recipients)} audiences."
                }
            )

        asyncio.run(
            getattr(self, f"_send_as_{self.type.lower()}")(
                to=recipients, 
                report=report
            )
        )

        if report:
            failures = len(list(filter(lambda event: event["type"] == "ERROR", report.events)))
            report.add_event(
                event_type="INFO", 
                data={
                    "detail": f"Completed {self.type} broadcast with {len(failures)} failures."
                }
            )
        return None


    async def _send_as_email(
            self, 
            to: List[CampaignAudience], 
            *,
            report: CampaignRunReport,
        ):
        """Send message as email"""
        if not isinstance(to, list):
            raise ValueError("`to` should be of type list")
        
        limiter = aiolimiter.AsyncLimiter(20)
        async with limiter:
            async with httpx.AsyncClient() as client:
                tasks = [ 
                    self._send_email_to_audience(
                        audience=audience, 
                        client=client,
                        report=report
                    ) 
                    for audience in to 
                ]
                await asyncio.gather(*tasks)
        return None


    async def _send_as_sms(
            self, 
            to: List[CampaignAudience], 
            *,
            report: CampaignRunReport = None,
        ):
        """Send message as sms"""
        if not isinstance(to, list):
            raise ValueError("`to` should be of type list")
        
        limiter = aiolimiter.AsyncLimiter(20)
        async with limiter:
            async with httpx.AsyncClient() as client:
                tasks = [ 
                    self._send_sms_to_audience(
                        audience=audience, 
                        client=client, 
                        report=report
                    ) 
                    for audience in to 
                ]
                await asyncio.gather(*tasks)
        return None


    async def _send_email_to_audience(
            self, 
            audience: CampaignAudience,
            *,
            client: httpx.AsyncClient = None, 
            report: CampaignRunReport = None
        ):
        """Send email to audience"""
        if audience.email:
            client = client or httpx.AsyncClient()
            campaign = self.get_campaign(dowell_api_key=settings.PROJECT_API_KEY)
            unsubscribe_url = urljoin(settings.API_BASE_URL, f"campaigns/{campaign.pkey}/audiences/unsubscribe/?audience_id={audience.id}")

            mail_kwargs = {
                "subject": self.subject,
                "user": campaign.creator,
                "sender_name": campaign.creator.username,
                "sender_address": self.sender,
                "recipient_address": audience.email,
                "client": client
            }
            
            if self.is_html_email:
                # if the server is not working send normal body html
                html_body = fetch_email(self.html_email_link)
                if html_body:
                    mail_kwargs["body"] = html_body
                else:
                    # if the fetching email template has a problem we sent normal email
                    mail_kwargs["body"] = construct_dowell_email_template(
                        subject=self.subject,
                        body=self.body, 
                        recipient=audience.email,
                        image_url=campaign.image,
                        unsubscribe_link=unsubscribe_url
                    )
            else:
                mail_kwargs["body"] = construct_dowell_email_template(
                        subject=self.subject,
                        body=self.body, 
                        recipient=audience.email,
                        image_url=campaign.image,
                        unsubscribe_link=unsubscribe_url
                    )
            try:
                await async_send_mail(**mail_kwargs)
                if report:
                    report.add_event(
                        event_type="INFO", 
                        data={
                            "detail": f"Message successfully sent to {audience.email}",
                            "audience_id": audience.pkey
                        }
                    )
            except Exception as exc:
                if report:
                    report.add_event(
                        event_type="ERROR", 
                        data={
                            "detail": f"Message failed to send to {audience.email}",
                            "error": str(exc),
                            "audience_id": audience.pkey
                        }
                    )
        return None
        
    
    async def _send_sms_to_audience(
            self, 
            audience: CampaignAudience, 
            *,
            client: httpx.AsyncClient = None, 
            report: CampaignRunReport = None
        ):
        """Send sms to audience"""
        if audience.phonenumber:
            client = client or httpx.AsyncClient()
            campaign = self.get_campaign(dowell_api_key=settings.PROJECT_API_KEY)

            sms_kwargs = {
                "message": f"{self.subject}\n {self.body}" if self.subject else self.body,
                "sender_name": campaign.creator.username,
                "sender_phonenumber": self.sender,
                "recipient_phonenumber": audience.phonenumber,
                "user": campaign.creator,
                "client": client
            }
            try:
                await async_send_sms(**sms_kwargs)
                if report:
                    report.add_event(
                        event_type="INFO",
                        data={
                            "detail": f"Message successfully sent to {audience.phonenumber}",
                            "audience_id": audience.pkey
                        }
                    )
            except Exception as exc:
                if report:
                    report.add_event(
                        event_type="ERROR", 
                        data={
                            "detail": f"Message failed to send to {audience.phonenumber}",
                            "error": str(exc),
                            "audience_id": audience.pkey
                        }
                    )
        return None
