import requests
import time
from campaigns.helpers import SendEmail

def get_workspace_ids():
    print("Getting workspaces")
    """
    Retrieve workspace IDs from the text file.

    :return: A list of workspace IDs.
    """
    try:
        with open("workspace_ids.txt", "r") as file:
            workspace_ids = file.read().splitlines()
            print(workspace_ids)
        return workspace_ids
    except FileNotFoundError:
        return []

def request_task_run():
    print("hello world")
    session = requests.Session()
    workspace_ids = get_workspace_ids()
    for workspace_id in workspace_ids:
        print(workspace_id)
        response = session.post(
            url=f"https://www.uxlive.me/samanta-campaigns/api/v1/campaignsV2/webhooks/tasks/?workspace_id={workspace_id}",
            #url=f"http://localhost:8000/samanta-campaigns/api/v1/campaignsV2/webhooks/tasks/?workspace_id={workspace_id}",
            json={
                "event": "task_due",
                "task_name": "crawl_campaigns_leads_links",
                "passkey": "1eb$fyirun-gh2j3go1n4u12@i"
            }
        )
        if response.status_code == 200:
            print(response.json())
            # # Send email if response is 200
            # mail = SendEmail().sendmail(workspace_id)
            # print(mail)
        else:
            print("Request failed with status code:", response.status_code)
            # Optionally, handle other status codes here

        response.raise_for_status()


if __name__ == "__main__":
    while True:
        request_task_run()
        time.sleep(60 * 5)