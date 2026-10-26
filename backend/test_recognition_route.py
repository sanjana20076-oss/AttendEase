"""Optional manual API smoke test. Not executed at import/pytest collection time.

python backend/test_recognition_route.py --image /path/to/face.jpg --session-id 1 --username admin
The selected session must already be started and inside its scheduled time.
"""
import argparse
import getpass
from pathlib import Path
import re


def main():
    import requests
    parser = argparse.ArgumentParser(description="Send one real face image to a selected active class.")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--session-id", type=int, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    args = parser.parse_args()
    if not args.image.is_file() or args.session_id <= 0:
        parser.error("Use an existing image and a positive session ID.")
    password = getpass.getpass("Admin password: ")
    client = requests.Session()
    base_url = args.base_url.rstrip("/")
    response = client.get(base_url + "/login", timeout=15)
    response.raise_for_status()
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    if not match:
        raise RuntimeError("CSRF field missing. Check that the updated app is running.")
    response = client.post(base_url + "/login", data={"username":args.username,"password":password,
                            "csrf_token":match.group(1)}, allow_redirects=False, timeout=30)
    if response.status_code != 302:
        print("Login failed:", response.status_code)
        return 1
    camera = client.get(base_url + "/attendance-camera", params={"session_id":args.session_id}, timeout=30)
    token = re.search(r'data-csrf-token="([^"]+)"', camera.text)
    if camera.status_code != 200 or not token:
        print("Selected camera unavailable. Start the class and check its owner, date, and time.")
        return 1
    with args.image.open("rb") as image:
        response = client.post(base_url + "/recognize-face", data={"session_id":str(args.session_id)},
                               files={"frame":(args.image.name,image,"image/jpeg")},
                               headers={"X-CSRF-Token":token.group(1)}, timeout=120)
    print("Recognition status:", response.status_code)
    print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
