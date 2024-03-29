from rest_framework import exceptions, response, status, views

from api.views import SamanthaCampaignsAPIView
from .utils import check_webhook_passkey
from .tasks import register as campaign_task_register



class CampaignTasksWebHook(SamanthaCampaignsAPIView):
    """Webhook for handling requests to run a specified campaign task."""
    
    def post(self, request, *args, **kwargs):
        """
        Sample Request Body Format:
        ```
        {
            "event": "task_due",
            "task_name": "run_due_campaigns",
            "passkey": "<passkey>"
        }
        ```
        """
        workspace_id = request.query_params.get("workspace_id", None)
        data = request.data
        if not isinstance(data, dict):
            raise exceptions.NotAcceptable("Request body must be a dictionary.")

        event = data.get("event", None)
        msg = None,
        if not event:
            raise exceptions.ValidationError("An event must be specified")
        
        if event == "task_due":
            task_name = data.get("task_name", None)
            passkey = data.get("passkey", None)
            if not task_name:
                raise exceptions.ValidationError("task_name must be specified")
            
            check_webhook_passkey(passkey)
            task = campaign_task_register.get(task_name, None)
            if not task:
                raise exceptions.NotFound(f"Task with name '{task_name}' does not exist")
            # run task
            task(workspace_id=workspace_id)
            msg = f"Task '{task_name}' ran successfully"

        else:
            raise exceptions.ValidationError("Invalid event!")

        return response.Response(
            data={
                "detail": msg
            },
            status=status.HTTP_200_OK
        )



campaign_tasks_webhook = CampaignTasksWebHook.as_view()
