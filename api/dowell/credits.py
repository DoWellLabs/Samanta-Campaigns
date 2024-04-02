from typing import List
import requests
from django.conf import settings

from .user import DowellUser
from .services import DowellService, DowellSubService
from .exceptions import (
    ServiceNotActive,
    SubServiceNotActive,
    SubservicesRequired,
    SubServiceNotFound,
    InsufficientCredits,
    ServiceNotfound,
)



class DeductUserCreditsOnServiceUse:
    """
    #### Context manager for deducting DowellUser credits on usage of DowellService in the context block.
    
    #### Usage:
    There are two ways to use this context manager:
    ```
    def function_that_uses_a_dowell_service(*args, **kwargs):
        # Use service
        pass

    # Here the required amount of credits for the service and/or subservice is deducted on exiting the context manager if the function runs successfully and no exception is raised
    with DeductUserCreditsOnServiceUse(user, service, subservices, count):
        function_that_uses_a_dowell_service(*args, **kwargs)
    
    # Here the required amount of credits for the service and/or subservice is deducted manually
    with DeductUserCreditsOnServiceUse(user, service, subservices, auto_deduct=False) as user_credits_manager:
        try:
            function_that_uses_a_dowell_service(*args, **kwargs)
            # Deduct credits manually
            credit_balance = user_credits_manager.deduct_credits()
            user.credits = credit_balance
        except:
            # Do not deduct credits if an exception is raised
            pass
    ```

    Alternatively, you can use the async version of the context manager:
    ```
    async def function_that_uses_a_dowell_service(*args, **kwargs):
        # Use service
        pass
    
    async with DeductUserCreditsOnServiceUse(user, service, subservices, count):
        await function_that_uses_a_dowell_service(*args, **kwargs)
    ```

    You can also use the context manager as a means to check if all prerequisites for using a service are met before using the service:
    ```
    ensure_prerequisites_are_met_before_service_use = dowell.DeductUserCreditsOnServiceUse(
        user=user, 
        service=service, 
        auto_deduct=False, 
    )
    with ensure_prerequisites_are_met_before_service_use:
        # Use service
        pass
    ```
    """

    def __init__(
            self, 
            user: DowellUser | str, 
            service: DowellService | str, 
            subservices: List[DowellSubService | str] = None, 
            count: int = 1,
            auto_deduct: bool = True,
            exempted_users: List[DowellUser | str] = None,
            suppress_exc: bool = False,
        ) -> None:
        """
        Initializes a DeductUserCreditsOnServiceUse object.

        :param user: The DowellUser object or workspace ID of the user.
        :param service: The DowellService object or name/id of the service.
        :param subservices: The list of DowellSubService objects or names/ids of the subservices used. Optional. Only required for services with subservices.
        :param count: The number of times the service is to be used in the context manager.
        :param auto_deduct: Whether to deduct credits automatically on exiting the context manager.
        :param exempted_users: The list of DowellUser objects or workspace IDs of users exempted from credit deduction. If a user is in this list, credits are not deducted.
        :param suppress_exc: Whether to suppress exceptions that occur in context manager. If True, Credits are not deducted in the event of an exception, and the exception is suppressed.
        :return: If auto_deduct is True, then it returns True if credits were deducted successfully, else False.
        """
        self.user = user if isinstance(user, DowellUser) else DowellUser(workspace_id=user)
        self.service = service if isinstance(service, DowellService) else self.user.get_service(service)
        if not self.service:
            raise ServiceNotfound(service)
        self.subservices = subservices
        if not isinstance(count, int):
            raise ValueError("Count must be an integer.")
        if count < 1:
            raise ValueError("Count must be greater than 0.")
        self.count = count
        self.auto = auto_deduct
        self.suppress_exc = suppress_exc
        self.exempted_users = exempted_users if exempted_users else []
        return None
    
    
    def __enter__(self):
        # Check that all service and subservice objects are active and that the user has enough credits.
        if not self.service.active_status:
            raise ServiceNotActive(self.service)
        
        for index, exempted_user in enumerate(self.exempted_users):
            if not isinstance(exempted_user, DowellUser):
                if isinstance(exempted_user, str):
                    self.exempted_users[index] = DowellUser(workspace_id=exempted_user)
                else:
                    raise ValueError("Exempted users must be a list of DowellUser objects or workspace IDs.")
        
        if self.service.subservices:
            if not self.subservices:
                raise SubservicesRequired(self.service)
            if not isinstance(self.subservices, list):
                raise TypeError("`subservices` should be of type list[DowellSubService | str]")
            for subserv in self.subservices:
                if not isinstance(subserv, DowellSubService):
                    subservice = self.service.get_subservice(subserv)
                    if not subservice:
                        raise SubServiceNotFound(self.service, subserv)
                    if not subservice.check_active_status_for_user(self.user):
                        raise SubServiceNotActive(self.service, subservice)
                    # Replace the subservice name/id with the subservice object
                    self.subservices.remove(subserv)
                    self.subservices.append(subservice)

        if self.auto and (self.user not in self.exempted_users) and not self.user.has_enough_credits_for(service=self.service, subservices=self.subservices, count=self.count):
            remaining_credits = self.user.credits_required_for(
                service=self.service, 
                subservices=self.subservices, 
                count=self.count
            ) - self.user.credits
            raise InsufficientCredits(self.user, remaining_credits)
        return self
    

    async def __aenter__(self):
        return self.__enter__()


    def deduct_credits(self) -> int:
        """
        Deducts credits from the user's account based on initialized parameters.

        If `self.user` is in `self.exempted_users`, then no credits are deducted.
        `self.count` does not affect the number of credits deducted if you are using this method directly. 
        Only one credit unit is deducted.

        :return: The user's remaining credits after deduction.
        """
        if self.user in self.exempted_users:
            return self.user.credits

        if not self.auto and not self.user.has_enough_credits_for(service=self.service, subservices=self.subservices):
            remaining_credits = self.user.credits_required_for(
                service=self.service, 
                subservices=self.subservices
            ) - self.user.credits
            raise InsufficientCredits(self.user, remaining_credits)
        
        payload = {"service_id": self.service.id}
        if self.service.subservices and self.subservices:
            subservice_ids = [ subservice.id for subservice in self.subservices ]
            payload.update({"sub_service_ids": subservice_ids})

        response = requests.post(
            url=settings.DOWELL_PROCESS_SERVICES_URL,
            params={
                "type": f"{self.service.type.lower().replace(' ', '_')}_service",
                "api_key": self.settings.PROJECT_API_KEY,
            },
            json=payload
        )
        if response.status_code != 200:
            response.raise_for_status()
        if not response.json()["success"]:
            raise Exception(response.json()["message"])
        try:
            return response.json()["remaining_credits"]
        except KeyError:
            return response.json()["total_credits"]
    

    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self.auto:
            if exc_type and not self.suppress_exc:
                return False
            if not exc_type and self.user not in self.exempted_users:
                for _ in range(self.count):
                    try:
                        self.user.credits = self.deduct_credits()
                    except:
                        # If exception occurs, update the user for any changes that might have occurred and suppress the exception
                        self.user.update()
            return True
        self.user.update()
        if self.suppress_exc:
            return True
        return False
    

    async def __aexit__(self, exc_type, exc_value, exc_traceback):
        return self.__exit__(exc_type, exc_value, exc_traceback)



# Testing Context Manager

# def get_dowell_user(workspace_id: str):
#     """
#     Returns a DowellUser object for the user with the workspace ID provided.

#     :param workspace_id: The Dowell workspace ID of the user.
#     """
#     # raise Exception("This is a test function. Please do not use it in production.")
#     return DowellUser(workspace_id=workspace_id)

# user = DowellUser("6487201679229a4f3ad648b")
# service = DowellService(service_id="DOWELL10042", workspace_id=user.workspace_id)

# print(f"User credits before service use: {user.credits}\n")

# with DeductUserCreditsOnServiceUse(user=user, service=service, subservices=[service.subservices[5]], count=1, auto_deduct=True) as user_credits_manager:
#     print(get_dowell_user(user.workspace_id))
#     # user_credits_manager.deduct_credits()

# print(f"User credits after service use: {user.credits}\n")
