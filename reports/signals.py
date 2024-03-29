from django.conf import settings
from django.dispatch import receiver

from .dbobjects import CampaignRunReport
from campaigns.dbobjects import Campaign
from api.objects.signals import pre_delete



@receiver(pre_delete, sender=Campaign)
def pre_campaign_delete(sender: type[Campaign], **kwargs):
    campaign = kwargs.get("instance")
    workspace_id = campaign.creator_id
    print("workspace id inside the delete report",workspace_id)
    run_reports = CampaignRunReport.manager.filter(
        campaign_id=campaign.pkey,
        dowell_api_key=settings.PROJECT_API_KEY,
        workspace_id=workspace_id,
        wanted = "reports"
    )
    run_reports.delete(dowell_api_key=settings.PROJECT_API_KEY)
    pass
