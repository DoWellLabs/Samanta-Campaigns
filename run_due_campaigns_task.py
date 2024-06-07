import requests
import time


def get_workspace_ids():
    print("Getting workspaces")
    try:
        url="https://www.uxlive.me/samanta-campaigns/api/v1/campaignsV2/get/workspace_id/"
        res = requests.get(url)
        print(res)
        return res.json()
    except FileNotFoundError:
        print("workspace_ids.txt file not found")
        return []


def request_task_run():
    session = requests.Session()
    workspace_ids = get_workspace_ids()
    for workspace_id in workspace_ids:
        print(workspace_id)
        response = session.post(
            # url=f"https://www.uxlive.me/samanta-campaigns/api/v1/campaignsV2/webhooks/tasks/?workspace_id={workspace_id}",
            url=f"https://samanta100111.pythonanywhere.com/samanta-campaigns/api/v1/campaignsV2/webhooks/tasks/?workspace_id={workspace_id}",
            json={
                "event": "task_due",
                "task_name": "run_due_campaigns",
                "passkey": "1eb$fyirun-gh2j3go1n4u12@i",
            },
        )
        if response.status_code < 500:
            print(response.json())
        response.raise_for_status()


if __name__ == "__main__":
    while True:
        request_task_run()
        time.sleep(3600)

# RUN THIS TASK HOURLY
