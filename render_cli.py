import os
import sys
import argparse
import requests
import json

RENDER_API_BASE = "https://api.render.com/v1"

def get_headers(api_key: str):
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

def get_owner_id(api_key: str):
    """Lấy User/Workspace ID của tài khoản Render."""
    url = f"{RENDER_API_BASE}/owners"
    res = requests.get(url, headers=get_headers(api_key))
    if res.status_code != 200:
        print(f"❌ Lỗi xác thực API Key ({res.status_code}): {res.text}")
        sys.exit(1)
    owners = res.json()
    if not owners:
        print("❌ Không tìm thấy thông tin Owner/Workspace.")
        sys.exit(1)
    owner = owners[0]["owner"]
    print(f"👤 Tài khoản: {owner.get('name')} ({owner.get('email')}) - ID: {owner.get('id')}")
    return owner["id"]

def create_env_group(api_key: str, name: str, stream_key: str, gdrive_url: str):
    """Tạo Environment Group trên Render qua API."""
    owner_id = get_owner_id(api_key)
    url = f"{RENDER_API_BASE}/env-groups"
    
    payload = {
        "name": name,
        "ownerId": owner_id,
        "envVars": [
            {"key": "YOUTUBE_STREAM_KEY", "value": stream_key},
            {"key": "GDRIVE_URL", "value": gdrive_url},
            {"key": "RTMP_URL", "value": "rtmp://a.rtmp.youtube.com/live2"},
            {"key": "PORT", "value": "10000"}
        ]
    }
    
    print(f"🚀 Đang tạo Environment Group: '{name}' trên Render...")
    res = requests.post(url, headers=get_headers(api_key), json=payload)
    
    if res.status_code in [200, 201]:
        data = res.json()
        print(f"✅ Tạo thành công Environment Group '{name}'!")
        print(f"   Group ID: {data.get('id')}")
        return data.get('id')
    else:
        print(f"❌ Lỗi khi tạo Env Group ({res.status_code}): {res.text}")
        return None

def list_services(api_key: str):
    """Liệt kê danh sách các Service đang chạy trên Render."""
    url = f"{RENDER_API_BASE}/services"
    res = requests.get(url, headers=get_headers(api_key))
    if res.status_code == 200:
        services = res.json()
        print(f"\n📋 Danh sách Services trên Render ({len(services)} services):")
        for s in services:
            svc = s.get("service", {})
            print(f" - [{svc.get('type')}] {svc.get('name')} | Status: {svc.get('status')} | URL: {svc.get('serviceDetails', {}).get('url')}")
    else:
        print(f"❌ Lỗi lấy danh sách services: {res.text}")

def main():
    parser = argparse.ArgumentParser(description="Render CLI - Quản trị và triển khai YouTube Live tự động")
    subparsers = parser.add_subparsers(dest="command")

    # Command: create-env
    env_parser = subparsers.add_parser("create-env", help="Tạo Environment Group trên Render")
    env_parser.add_argument("-k", "--api-key", required=True, help="Render API Key (rnd_...)")
    env_parser.add_argument("-n", "--name", default="Live", help="Tên nhóm Environment Group (Mặc định: Live)")
    env_parser.add_argument("-s", "--stream-key", required=True, help="YouTube Stream Key")
    env_parser.add_argument("-g", "--gdrive-url", required=True, help="Link Google Drive file video")

    # Command: list
    list_parser = subparsers.add_parser("list", help="Xem danh sách Services trên Render")
    list_parser.add_argument("-k", "--api-key", required=True, help="Render API Key")

    args = parser.parse_args()

    if args.command == "create-env":
        create_env_group(args.api_key, args.name, args.stream_key, args.gdrive_url)
    elif args.command == "list":
        list_services(args.api_key)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
