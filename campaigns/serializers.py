from django.conf import settings
from rest_framework import serializers, exceptions

from .dbobjects import (
    Campaign, 
    CampaignMessage, 
) 
from api.dowell.user import DowellUser
from api.validators import validate_email_or_phone_number, validate_not_in_past
from api.utils import is_email, is_phonenumber
from api.fields import CaseInsensitiveChoiceField


class CampaignSerializer(serializers.Serializer):
    """Campaign Serializer"""
    type = serializers.CharField(min_length=3, max_length=255)
    broadcast_type = CaseInsensitiveChoiceField(choices=Campaign.config.choices["broadcast_type"], default=Campaign.config.defaults.get("broadcast_type", "EMAIL"))
    title = serializers.CharField(min_length=3, max_length=255)
    purpose = serializers.CharField(min_length=5, max_length=2000, allow_null=True, required=False)
    keyword = serializers.CharField(min_length=3, max_length=255, required=False, allow_null=True)
    target_city = serializers.CharField(max_length=255, required=False, allow_null=True)
    range = serializers.IntegerField(min_value=0, max_value=5000, required=False, allow_null=True)
    frequency = CaseInsensitiveChoiceField(choices=Campaign.config.choices["frequency"], default=Campaign.config.defaults.get("frequency", "DAILY"))
    start_date = serializers.DateField(validators=[validate_not_in_past], input_formats=["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"])
    end_date = serializers.DateField(validators=[validate_not_in_past], input_formats=["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"])
    audiences = serializers.ListField(child=serializers.CharField(max_length=255, validators=[validate_email_or_phone_number]), allow_empty=True, required=False)
    leads_links = serializers.ListField(child=serializers.URLField(), allow_empty=True, required=False)
    image = serializers.URLField(required=False, allow_null=True)
    default_message = serializers.BooleanField(default=False, required=False)


    def to_representation(self, campaign):
        return campaign.data
    
    
    def create(self, validated_data):
        dowell_api_key = self.context.get("dowell_api_key", None)
        creator = self.context.get("creator", None)
        if not creator:
            raise serializers.ValidationError("serializer context must contain 'creator'")
        if not isinstance(creator, DowellUser):
            raise serializers.ValidationError("Invalid type for creator")
        
        audiences = validated_data.pop("audiences", [])
        leads_links = validated_data.pop("leads_links", [])
        validated_data["creator_id"] = creator.workspace_id
        campaign: Campaign = Campaign.manager.create(save=False, **validated_data)

        for audience in audiences:
            campaign.add_audience(audience)
        for link in leads_links:
            campaign.add_leads_link(link)

        campaign.save(dowell_api_key=dowell_api_key)
        return campaign

    
    def update(self, campaign: Campaign, validated_data):
        dowell_api_key = self.context.get("dowell_api_key", None)
        validated_data.pop("broadcast_type", None)
        validated_data.pop("audiences", None)
        validated_data.pop("leads_links", None)

        for attr, value in validated_data.items():
            setattr(campaign, attr, value)

        campaign.save(dowell_api_key=dowell_api_key)
        return campaign



class CampaignMessageSerializer(serializers.Serializer):
    """Campaign Message Serializer"""
    subject = serializers.CharField(min_length=5, max_length=255)
    body = serializers.CharField(min_length=10, max_length=5000)
    sender = serializers.CharField(max_length=255, validators=[validate_email_or_phone_number], required=False)
    is_default = serializers.BooleanField(default=False, required=False)
    is_html_email = serializers.BooleanField(default=False, required=False)
    html_email_link = serializers.URLField(required=False, allow_null=True)

    def to_representation(self, campaign_message):
        return campaign_message.data
    
    
    def create(self, validated_data):
        campaign = self.context.get("campaign", None)
        dowell_api_key = self.context.get("dowell_api_key", None)
        if not campaign:
            raise exceptions.ValidationError("serializer context must contain 'campaign'")
        if not isinstance(campaign, Campaign):
            raise exceptions.ValidationError("Invalid type for campaign")
        # if campaign.get_message(dowell_api_key=settings.PROJECT_API_KEY):
        #     raise exceptions.ValidationError(f"Campaign '{campaign.title}', already has a message")
        
        validated_data["type"] = campaign.broadcast_type
        validated_data["campaign_id"] = campaign.pkey
        # print("validated data is", validated_data)
        sender = validated_data.get("sender", None)
        if campaign.broadcast_type.lower() == "email":
            if not sender:
                validated_data["sender"] = campaign.creator.email
            if not is_email(validated_data["sender"]):
                raise exceptions.ValidationError("sender must be a valid email address")
        else:
            if not sender:
                validated_data["sender"] = campaign.creator.phonenumber
            if not is_phonenumber(validated_data["sender"]):
                raise exceptions.ValidationError("sender must be a valid phone number")
        collection_name = f"{campaign.creator_id}_samantha_campaign"
        return CampaignMessage.manager.create(dowell_api_key=dowell_api_key, **validated_data, collection_name=collection_name)
    

    def update(self, campaign_message: CampaignMessage, validated_data):
        dowell_api_key = self.context.get("dowell_api_key", None)
        workspace_id = self.context.get("workspace_id", None)
        sender = validated_data.get("sender", None)

        if sender is not None:
            if campaign_message.type.lower() == "email":
                if not is_email(sender):
                    raise exceptions.ValidationError("sender must be a valid email address")
            else:
                if not is_phonenumber(sender):
                    raise exceptions.ValidationError("sender must be a valid phone number")
        for attr, value in validated_data.items():
            setattr(campaign_message, attr, value)
        campaign_message.is_default = False
        print("serialiezer workspce_id",workspace_id)
        campaign_message.save(dowell_api_key=dowell_api_key,workspace_id=workspace_id)
        return campaign_message