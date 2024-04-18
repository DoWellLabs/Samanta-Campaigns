import requests
from typing import Any, List

from .services import DowellService, DowellSubService
from .mixins import DowellObjectEqualityMixin, DowellObjectMetaDataValidationMixin
from .exceptions import (
    UserNotFound,
    MetaDataNotFoundError,
    ServiceNotfound,
    SubServiceNotFound,
    SubservicesRequired,
    SubservicesNotRequired,
)



class DowellUser(DowellObjectEqualityMixin, DowellObjectMetaDataValidationMixin):
    """Class for representing a Dowell user."""

    def __init__(self, workspace_id: str):
        """
        Initializes a DowellUser object.

        :param workspace_id: The Dowell workspace ID of the user.
        """
        if not workspace_id:
            raise ValueError("Please provide a workspace ID.")
        self.workspace_id = workspace_id
        self.update()


    def __getmeta__(self):
        """Returns the metadata of the user."""
        from .utils import get_dowell_user_info
        try:
            return get_dowell_user_info(self.workspace_id)
        except requests.exceptions.HTTPError:
            raise UserNotFound(self.workspace_id)
    

    def __setattr__(self, __name: str, __value: Any) -> None:
        obj = super().__setattr__(__name, __value)
        # Update user details if metadata is updated
        if __name == "metadata":
            self.__update__()
        return obj
    

    def __repr__(self):
        return f"<DowellUser: {self.username}>"
    

    def __str__(self) -> str:
        return self.username
    

    @property
    def fullname(self):
        """User's full name"""
        return f"{self.firstname.title()} {self.lastname.title()}"
    

    def __update__(self):
        """Updates the user's details from the metadata."""
        if not self.metadata:
            raise MetaDataNotFoundError("Cannot update details without metadata. Call the update() method ")
        self.id: str = self.metadata["_id"]
        self.username: str = self.metadata["username"]
        self.email: str = self.metadata["email"]
        self.api_key: str = self.metadata["api_key"]
        self.firstname: str = self.metadata['userDetails']["first_name"]
        self.lastname: str = self.metadata['userDetails']["last_name"]
        self.phonenumber: str = self.metadata['userDetails']["phone"]
        self.image_url: str = self.metadata['userDetails']["profile_img"]
        self.active_status: bool = self.metadata["is_active"]
        self.services: List[DowellService] = [ DowellService(metadata=service) for service in self.metadata["services"] ]
        self.has_paid_account: bool = self.metadata["is_paid"]
        self.credits: int = self.metadata["total_credits"]
        self.api_key_active_status: bool = self.metadata["disable_key"]
        return None
    

    def update(self):
        """Updates the user"""
        try:
            self.metadata = self.__getmeta__()
        except MetaDataNotFoundError:
            raise MetaDataNotFoundError("Invalid workspace ID.")
        return None


    @property
    def has_credits(self):
        """Returns whether the user has credits."""
        return self.credits > 0
    
    @property
    def active_services(self):
        """Returns a list of active services."""
        return [ service for service in self.services if service.active_status ]
    

    def check_service_active(self, service):
        """
        Returns whether a service is active for the user.

        :param service: The service ID of the service, service name or the service object.
        """
        serv = self.get_service(service)
        if not serv:
            raise ServiceNotfound(service)
        return serv.active_status


    def has_enough_credits_for(self, service, subservices: List = None, count: int = 1):
        """
        Returns whether the user has enough credits for a service.

        :param service: The service ID of the service, service name or the service object.
        :param count: The number of times the service is to be used.
        """
        return self.credits >= self.credits_required_for(service=service, subservices=subservices, count=count)
    

    def credits_required_for(self, service, subservices: List = None, count: int = 1):
        """
        Returns the number of credits required for a service.

        Subservices must be provided if the service has subservices as in the case of "PRODUCT" type services.

        :param service: The service ID of the service, service name or the service object.
        :param subservices: The list of subservices used under the service, if required.
        :param count: The number of times the service is to be used.
        """
        if not isinstance(count, int):
            raise ValueError("Count must be an integer.")
        if count < 1:
            count = 1  # Set count to 1 if it's less than 1
        
        if not isinstance(service, DowellService):
            serv = self.get_service(service)
            if not serv:
                raise ServiceNotfound(service)
            service = serv
            
        cr = service.credits_required
        if service.subservices:
            if not subservices:
                raise SubservicesRequired(service)
            if not isinstance(subservices, list):
                raise TypeError("`subservices` should be of type list[DowellSubService | str]")
            subservs = []
            for subserv in subservices:
                if not isinstance(subserv, DowellSubService):
                    subservice = service.get_subservice(subserv)
                    if not subservice:
                        raise SubServiceNotFound(service, subserv)
                    subserv = subservice
                subservs.append(subserv)
            cr = sum([ subservice.credits_required for subservice in subservs if subservice ])
        else:
            if subservices is not None:
                raise SubservicesNotRequired(service)
        return cr * count


    def get_service(self, service):
        """
        Returns a service object for the user.

        :param service: The service ID of the service, service name or the service object.
        """
        if isinstance(service, str):
            return next((serv for serv in self.services if serv.id == service or serv.name.lower() == service.lower()), None)
        elif isinstance(service, DowellService):
            return next((serv for serv in self.services if serv.id == service.id), None)
        else:
            raise ValueError("Service must be a service ID, service name or a DowellService object.")


