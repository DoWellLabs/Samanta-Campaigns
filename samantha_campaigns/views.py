from rest_framework import status, response
from django.views.decorators import csrf
from rest_framework.views import APIView
from django.utils.decorators import method_decorator
from rest_framework.decorators import api_view
import requests
import time
from rest_framework.response import Response



@method_decorator(csrf.csrf_exempt, name='dispatch')
class HealthCheckAPIView(APIView):
    """API Status"""
    def get(self, request, *args, **kwargs):
        return response.Response(
            data={"detail": "If you are seeing this, The backend server is running @v1.0.5"}, 
            status=status.HTTP_200_OK
        )

health_check_api_view = HealthCheckAPIView.as_view()


# @method_decorator(csrf.csrf_exempt, name='dispatch')
@api_view(['GET'])
def request_task_run(request):
    print("hello world")
    session = requests.Session()
    response = session.post(
        url="https://samanta100111.pythonanywhere.com/api/v1/campaigns/webhooks/tasks/",
        # url="http://localhost:8000/api/v1/campaigns/webhooks/tasks/",
        json={
            "event": "task_due",
            "task_name": "crawl_campaigns_leads_links",
            "passkey": "1eb$fyirun-gh2j3go1n4u12@i"
        }
    )
    if response.status_code < 500:
        print(response.json())
        return Response(response.json())
    print(response.raise_for_status())
    return Response({"error": "problem when running tasks"})
    # response.raise_for_status()

