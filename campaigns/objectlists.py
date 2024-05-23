from django.utils import timezone
import aiolimiter
import asyncio
from typing import List, Dict

from api.objects.objectlist import ObjectList
from api.dowell.user import DowellUser



class CampaignList(ObjectList):
    """Custom ObjectList for Campaigns"""

    def active(self):
        """Return an ObjectList of active campaigns"""
        return self.filter(is_active=True)
    

    def inactive(self):
        """Return an ObjectList of inactive campaigns"""
        return self.filter(is_active=False)


    def due(self, *, padding: int | float | None = None):
        """
        Get campaigns that are due today (Both active and inactive campaigns)
        
        :param padding: The number of days to add to the current date to get the due date. 
        This is useful for getting campaigns that are due at a future date.
        :return: A ObjectList of Campaigns that are due today
        """
        due_campaigns = filter(lambda campaign: campaign.is_due(padding=padding), self.all())
        clone = self.clone()
        clone.extend(list(due_campaigns))
        return clone


    def expired(self):
        """
        Get campaigns whose end date has passed (Both active and inactive campaigns)
        
        :return: A ObjectList of Campaigns whose end date has passed
        """
        expired_campaigns = filter(lambda campaign: campaign.is_expired(), self.all())
        clone = self.clone()
        clone.extend(list(expired_campaigns))
        return clone


class CampaignAudienceList(ObjectList):
    """Custom ObjectList for CampaignAudiences"""

    def subscribed(self):
        """Returns an ObjectList of subscribed CampaignAudience objects"""
        return self.filter(is_subscribed=True)
    

    def unsubscribed(self):
        """Returns an ObjectList of unsubscribed CampaignAudience objects"""
        return self.filter(is_subscribed=False)



class CampaignAudienceLeadsLinkList(ObjectList):
    """Custom ObjectList for `CampaignAudienceLeadsLink`s"""
    
    def crawled(self):
        """Returns and ObjectList of crawled `CampaignAudienceLeadsLink`s"""
        return self.filter(is_crawled=True)
    

    def uncrawled(self):
        """Returns an ObjectList of uncrawled `CampaignAudienceLeadsLink`s"""
        return self.filter(is_crawled=False)


    def crawl(self, *, campaign_creator: str | DowellUser, crawl_depth: int = 0) -> List[Dict]:
        """
        Crawl all uncrawled `CampaignAudienceLeadsLink`s

        :param campaign_creator: Workspace ID of or DowellUser object of 
        creator of the campaign this leads link belongs to.
        :return: A list of dictionaries containing the crawled data
        """
        print("this is self.uncrawled",self.uncrawled())
        async def acrawl():
            limiter = aiolimiter.AsyncLimiter(20)
            async with limiter:
                tasks = [ 
                    link.acrawl(
                        campaign_creator=campaign_creator, 
                        crawl_depth=crawl_depth
                    ) 
                    for link in self.uncrawled() 
                ]
                return await asyncio.gather(*tasks)

        return asyncio.run(acrawl())
