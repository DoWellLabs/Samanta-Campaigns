import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def get_workspace_ids():
    print("Getting workspaces")
    try:
        with open("workspace_ids.txt", "r") as file:
            workspace_ids = file.read().splitlines()
            print(workspace_ids)
        return workspace_ids
    except FileNotFoundError:
        print("workspace_ids.txt file not found")
        return []


def send_request(session, workspace_id):
    url = f"https://samanta100111.pythonanywhere.com/samanta-campaigns/api/v1/campaignsV2/webhooks/tasks/?workspace_id={workspace_id}"
    data = {
        "event": "task_due",
        "task_name": "crawl_campaigns_leads_links",
        "passkey": "1eb$fyirun-gh2j3go1n4u12@i",
    }
    try:
        response = session.post(url, json=data)
        response.raise_for_status()
        if response.status_code == 200:
            print(response.json())
            # Send email if response is 200
            # mail = SendEmail().sendmail(workspace_id)
            # print(mail)
        else:
            print(
                f"Request failed for workspace {workspace_id} with status code: {response.status_code}"
            )
    except requests.RequestException as e:
        print(f"Request failed for workspace {workspace_id} with error: {e}")


def request_task_run():
    print("hello world")
    session = requests.Session()
    workspace_ids = get_workspace_ids()

    if not workspace_ids:
        print("No workspace IDs found.")
        return

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {
            executor.submit(send_request, session, workspace_id): workspace_id
            for workspace_id in workspace_ids
        }

        for future in as_completed(futures):
            workspace_id = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"Error occurred for workspace {workspace_id}: {e}")


if __name__ == "__main__":
    while True:
        request_task_run()
        time.sleep(60 * 10)
