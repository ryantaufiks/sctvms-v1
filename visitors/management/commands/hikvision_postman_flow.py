import os
import socket
from datetime import datetime, timedelta
import base64
from pathlib import Path

import requests
from requests.auth import HTTPDigestAuth
from django.core.management.base import BaseCommand
from django.conf import settings

from site_settings.models import HikvisionConfiguration


def _compute_public_media_url(local_path: Path) -> str:
    """
    Compute an accessible URL for the device to fetch the image.
    Prefers settings.PUBLIC_BASE_URL, else attempts to use local IP and dev server port.
    """
    rel = local_path.as_posix().split('/media/')[-1]
    if getattr(settings, 'PUBLIC_BASE_URL', None):
        return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/media/{rel}"

    # Fallback: try local IP and known dev server port 8004
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = '127.0.0.1'
    return f"http://{local_ip}:8004/media/{rel}"


class Command(BaseCommand):
    help = "Execute Hikvision Postman-like flow: add visitor, upload face by URL and multipart"

    def add_arguments(self, parser):
        parser.add_argument('--visitor-id', default='V12345')
        parser.add_argument('--visitor-name', default='Guest A')
        parser.add_argument('--password', default='123456')
        parser.add_argument('--begin-time', default=datetime.now().strftime('%Y-%m-%dT00:00:00'))
        parser.add_argument('--end-time', default=(datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT23:59:59'))
        parser.add_argument('--face-file', default=str(Path(settings.MEDIA_ROOT) / 'face_images' / 'visitor_337712.jpg'))
        parser.add_argument('--device-ip', default=None, help='Override device IP; else use HikvisionConfiguration.terminal_url')

    def handle(self, *args, **options):
        cfg = HikvisionConfiguration.objects.first()
        if not cfg:
            self.stderr.write('HikvisionConfiguration not found in DB')
            return

        # Base URL
        if options['device_ip']:
            protocol = 'https' if cfg.use_https else 'http'
            base_url = f"{protocol}://{options['device_ip']}"
            if cfg.use_https and cfg.terminal_port and cfg.terminal_port != 443:
                base_url += f":{cfg.terminal_port}"
            if not cfg.use_https and cfg.terminal_port and cfg.terminal_port != 80:
                base_url += f":{cfg.terminal_port}"
        else:
            base_url = cfg.terminal_url

        auth = HTTPDigestAuth(cfg.username, cfg.password)

        visitor_id = options['visitor_id']
        visitor_name = options['visitor_name']
        password = options['password']
        begin_time = options['begin_time']
        end_time = options['end_time']

        # Prepare image
        face_path = Path(options['face_file'])
        if not face_path.exists():
            self.stderr.write(f'Face file not found: {face_path}')
            return

        # Ensure file is in media for URL serving
        media_face_dir = Path(settings.MEDIA_ROOT) / 'face_images'
        media_face_dir.mkdir(parents=True, exist_ok=True)
        media_target = media_face_dir / f'postman_{visitor_id}.jpg'
        if str(face_path) != str(media_target):
            media_target.write_bytes(Path(face_path).read_bytes())

        face_url = _compute_public_media_url(media_target)

        # 1. Add Visitor (with Password) via XML
        xml_user = f'''<?xml version="1.0" encoding="UTF-8"?>
<UserInfo version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">
  <employeeNo>{visitor_id}</employeeNo>
  <name>{visitor_name}</name>
  <userType>normal</userType>
  <Valid>
    <enable>true</enable>
    <beginTime>{begin_time}</beginTime>
    <endTime>{end_time}</endTime>
  </Valid>
  <doorRight>1</doorRight>
  <RightPlanList>
    <RightPlan>
      <doorNo>1</doorNo>
      <planTemplateNo>1</planTemplateNo>
    </RightPlan>
  </RightPlanList>
  <password>{password}</password>
</UserInfo>'''

        url_user = f"{base_url}/ISAPI/AccessControl/UserInfo/Record"
        self.stdout.write(f"POST {url_user}")
        try:
            r1 = requests.post(url_user, data=xml_user.encode('utf-8'), headers={'Content-Type': 'application/xml'}, auth=auth, timeout=15)
            self.stdout.write(f"Status: {r1.status_code}")
            self.stdout.write(r1.text[:500])
            r1.raise_for_status()
        except requests.HTTPError as e:
            self.stderr.write(f"Add Visitor failed: {e}")
            self.stderr.write(r1.text)

        # 2. Upload Face (by URL) via XML PUT
        xml_face_url = f'''<?xml version="1.0" encoding="UTF-8"?>
<FaceData version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">
  <faceLibType>blackFD</faceLibType>
  <FDID>1</FDID>
  <FPID>{visitor_id}</FPID>
  <faceURL>{face_url}</faceURL>
</FaceData>'''

        url_face_put = f"{base_url}/ISAPI/Intelligent/FDLib/FaceDataRecord/{visitor_id}"
        self.stdout.write(f"PUT {url_face_put}")
        try:
            r2 = requests.put(url_face_put, data=xml_face_url.encode('utf-8'), headers={'Content-Type': 'application/xml'}, auth=auth, timeout=20)
            self.stdout.write(f"Status: {r2.status_code}")
            self.stdout.write(r2.text[:500])
            r2.raise_for_status()
        except requests.HTTPError as e:
            self.stderr.write(f"Upload Face (URL) failed: {e}")
            self.stderr.write(r2.text)

        # 2b. Upload Face (by URL) via JSON POST
        url_face_json = f"{base_url}/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json"
        json_url_body = {
            "faceLibType": "blackFD",
            "FDID": "1",
            "FPID": visitor_id,
            "name": visitor_name,
            "faceURL": face_url,
        }
        self.stdout.write(f"POST {url_face_json} [JSON faceURL]")
        try:
            r2b = requests.post(url_face_json, json=json_url_body, auth=auth, timeout=20)
            self.stdout.write(f"Status: {r2b.status_code}")
            self.stdout.write(r2b.text[:500])
            r2b.raise_for_status()
        except requests.HTTPError as e:
            self.stderr.write(f"Upload Face (JSON faceURL) failed: {e}")
            self.stderr.write(r2b.text)

        # 3. Upload Face (multipart)
        url_face_mp = f"{base_url}/ISAPI/Intelligent/FDLib/FaceDataRecord"
        self.stdout.write(f"POST {url_face_mp}")
        files = {
            'FaceImage': (media_target.name, media_target.read_bytes(), 'image/jpeg'),
        }
        data = {
            'faceLibType': 'blackFD',
            'FDID': '1',
            'FPID': visitor_id,
        }
        try:
            r3 = requests.post(url_face_mp, files=files, data=data, auth=auth, timeout=30)
            self.stdout.write(f"Status: {r3.status_code}")
            self.stdout.write(r3.text[:500])
            r3.raise_for_status()
        except requests.HTTPError as e:
            self.stderr.write(f"Upload Face (multipart) failed: {e}")
            self.stderr.write(r3.text)

        # 4. Upload Face (multipart) alternative keys and library type 'employee'
        url_face_mp_alt = url_face_mp
        self.stdout.write(f"POST {url_face_mp_alt} [alt keys]")
        files_alt = {
            'faceImage': (media_target.name, media_target.read_bytes(), 'image/jpeg'),
        }
        data_alt = {
            'faceLibType': 'employee',
            'FDID': '1',
            'employeeNo': visitor_id,
        }
        try:
            r4 = requests.post(url_face_mp_alt, files=files_alt, data=data_alt, auth=auth, timeout=30)
            self.stdout.write(f"Status: {r4.status_code}")
            self.stdout.write(r4.text[:500])
            r4.raise_for_status()
        except requests.HTTPError as e:
            self.stderr.write(f"Upload Face (multipart alt) failed: {e}")
            self.stderr.write(r4.text)

        # 5. AccessControl UserPictureRecord variant (commonly supported on some terminals)
        url_upr = f"{base_url}/ISAPI/AccessControl/UserPictureRecord"
        self.stdout.write(f"POST {url_upr} [UserPictureRecord]")
        files_upr = {
            'userID': (None, visitor_id),
            'deleteFlag': (None, 'false'),
            'faceImage': (media_target.name, media_target.read_bytes(), 'image/jpeg'),
        }
        try:
            r5 = requests.post(url_upr, files=files_upr, auth=auth, timeout=30)
            self.stdout.write(f"Status: {r5.status_code}")
            self.stdout.write(r5.text[:500])
            r5.raise_for_status()
        except requests.HTTPError as e:
            self.stderr.write(f"UserPictureRecord upload failed: {e}")
            self.stderr.write(r5.text)

        # 6. Upload Face (JSON base64) if device supports JSON-only
        try:
            b64 = base64.b64encode(media_target.read_bytes()).decode('ascii')
        except Exception as e:
            self.stderr.write(f"Base64 encode failed: {e}")
            b64 = None
        if b64:
            json_b64_body = {
                "faceLibType": "blackFD",
                "FDID": "1",
                "FPID": visitor_id,
                "name": visitor_name,
                "faceImage": b64,
            }
            self.stdout.write(f"POST {url_face_json} [JSON base64]")
            try:
                r6 = requests.post(url_face_json, json=json_b64_body, auth=auth, timeout=20)
                self.stdout.write(f"Status: {r6.status_code}")
                self.stdout.write(r6.text[:500])
                r6.raise_for_status()
            except requests.HTTPError as e:
                self.stderr.write(f"Upload Face (JSON base64) failed: {e}")
                self.stderr.write(r6.text)

        self.stdout.write('Done.')
        # Inspect FDLib capabilities and sets (diagnostics)
        url_caps = f"{base_url}/ISAPI/Intelligent/FDLib/capabilities"
        self.stdout.write(f"GET {url_caps}")
        try:
            rc = requests.get(url_caps, auth=auth, timeout=10)
            self.stdout.write(f"Status: {rc.status_code}")
            self.stdout.write(rc.text[:800])
        except Exception as e:
            self.stderr.write(f"FDLib capabilities fetch failed: {e}")

        for fmt in ('', '?format=json'):
            url_fdset = f"{base_url}/ISAPI/Intelligent/FDLib/FDSet{fmt}"
            self.stdout.write(f"GET {url_fdset}")
            try:
                rs = requests.get(url_fdset, auth=auth, timeout=10)
                self.stdout.write(f"Status: {rs.status_code}")
                self.stdout.write(rs.text[:800])
            except Exception as e:
                self.stderr.write(f"FDSet fetch failed: {e}")