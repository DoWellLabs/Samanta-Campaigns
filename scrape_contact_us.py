import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_workspace_ids():
    print("Getting workspaces")
    try:
        url = "https://www.uxlive.me/samanta-campaigns/api/v1/campaignsV2/get/workspace_id/"
        # url = "http://127.0.0.1:8001/samanta-campaigns/api/v1/campaignsV2/get/workspace_id/"
        res = requests.get(url)

        # Check if the response is valid (status code 200)
        if res.status_code == 200:
            try:
                # Attempt to parse the JSON content
                return res.json()
            except ValueError as e:
                # Handle JSON decoding errors
                print(f"Error decoding JSON: {e}")
                print(f"Response content: {res.text}")
                return []
        else:
            print(f"Failed to get workspaces, status code: {res.status_code}")
            return []

    except requests.RequestException as e:
        print(f"An error occurred while fetching workspace IDs: {e}")
        return []

def send_request(session, workspace_id):
    url = f"https://samanta100111.pythonanywhere.com/samanta-campaigns/api/v1/campaignsV2/scrape/contact_us/?workspace_id={workspace_id}"
    try:
        response = session.post(url)
        response.raise_for_status()
        if response.status_code == 200:
            print(f"Success for workspace {workspace_id}: {response.json()}")
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
    print("Starting task run")
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
        time.sleep(60 * 10)  # Wait for 10 minutes before the next run
