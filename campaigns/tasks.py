import sys
import os
from django.conf import settings
from django.utils import timezone
import traceback

from campaigns.dbobjects import Campaign
from api.objects.utils import get_logger


task_logger = get_logger(
    name="campaign_tasks",
    logfile_path=os.path.join(settings.LOG_PATH, f"campaign_tasks_{timezone.now().date().isoformat()}.log"),
    base_level="ERROR"
)


def crawl_campaigns_leads_links(workspace_id:str):
    """
    Crawl all campaigns' leads links
    """
    print("this is id",workspace_id)
    sys.stdout.write("Crawling lead links...\n")
    all_campaigns = Campaign.manager.all(dowell_api_key=settings.PROJECT_API_KEY,workspace_id=workspace_id)

    for campaign in all_campaigns:
        if not campaign.leads_links:
            continue
        try:
            campaign.crawl_leads_links_and_update_audiences()
        except Exception as exc:
            task_logger.error(
                f"Error crawling campaign(id={campaign.pkey}) leads links: {exc}\n"
                f"Traceback: {traceback.format_exc()}"
            )
        finally:
            campaign.save(dowell_api_key=settings.PROJECT_API_KEY)
            continue
    sys.stdout.write("Done crawling lead links.\n")
    return None



def run_due_campaigns():
    """Run all campaigns that are due"""
    sys.stdout.write("Running due campaigns...\n")
    # Get all campaigns that are due today
    due_campaigns = Campaign.manager.due(dowell_api_key=settings.PROJECT_API_KEY)

    for campaign in due_campaigns:
        # Register all campaign as due today
        campaign.due_today(save=False)

        # Skip inactive campaigns and campaigns that are already running
        if not campaign.is_active or campaign.is_running:
            # But save the campaign to update the database with the changes made by the `due_today` method
            campaign.save(dowell_api_key=settings.PROJECT_API_KEY)
            continue
        try:
            # Run the campaign
            # Changes made to the campaign by the `due_today` method will be saved while running the campaign
            campaign.run(
                raise_exception=False,
                log_errors=True,
                dowell_api_key=settings.PROJECT_API_KEY
            )
        except Exception as exc:
            task_logger.error(
                f"Error running campaign(id={campaign.pkey}): {exc}\n"
                f"Traceback: {traceback.format_exc()}"
            )
            # Make sure to save campaign if any exception occurs
            campaign.save(dowell_api_key=settings.PROJECT_API_KEY)
            continue
    sys.stdout.write("Done running due campaigns.\n")
    return None  



def deactivate_active_but_expired_campaigns():
    """Deactivate all campaigns that have expired"""
    sys.stdout.write("Deactivating active but expired campaigns...\n")
    # Fetch all expired campaigns but only active ones because by default,
    # the inactive ones cannot be activated after they have expired.
    active_but_expired_campaigns = Campaign.manager.expired(dowell_api_key=settings.PROJECT_API_KEY).active()

    for campaign in active_but_expired_campaigns:
        try:
            campaign.deactivate(dowell_api_key=settings.PROJECT_API_KEY)
        except Exception as exc:
            task_logger.error(
                f"Error deactivating expired campaign(id={campaign.pkey}): {exc}\n"
                f"Traceback: {traceback.format_exc()}"
            )
            continue
    sys.stdout.write("Done deactivating active but expired campaigns.\n")
    return None



register = {
    "run_due_campaigns": run_due_campaigns,
    "deactivate_active_but_expired_campaigns": deactivate_active_but_expired_campaigns,
    "crawl_campaigns_leads_links": crawl_campaigns_leads_links
}
