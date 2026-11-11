import logging
import os
import base64
from datetime import datetime
from typing import Optional

import requests
from requests.auth import HTTPDigestAuth
from django.conf import settings
from django.utils.text import slugify
from pathlib import Path
try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except Exception:
    _CV2_AVAILABLE = False

from site_settings.models import HikvisionConfiguration

logger = logging.getLogger(__name__)


class HikvisionTerminalManager:
    """
    Minimal helper to provision a user with face and PIN on Hikvision Face Reader.
    Uses device settings from HikvisionConfiguration.
    """

    def __init__(self):
        self.config = HikvisionConfiguration.objects.first()
        if not self.config:
            raise RuntimeError("HikvisionConfiguration not found. Please configure terminal in Admin.")
        self.base_url = self.config.terminal_url
        self.auth = HTTPDigestAuth(self.config.username, self.config.password)

    def _post_xml(self, endpoint: str, xml_body: str, timeout: int = 10) -> requests.Response:
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/xml"}
        logger.info("POST %s", url)
        resp = requests.post(url, data=xml_body.encode("utf-8"), headers=headers, auth=self.auth, timeout=timeout, verify=False)
        resp.raise_for_status()
        return resp

    def _put_xml(self, endpoint: str, xml_body: str, timeout: int = 10) -> requests.Response:
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/xml"}
        logger.info("PUT %s", url)
        resp = requests.put(url, data=xml_body.encode("utf-8"), headers=headers, auth=self.auth, timeout=timeout, verify=False)
        resp.raise_for_status()
        return resp

    def create_user_json_with_rights_and_pin(self, employee_no: str, name: str,
                                             start_time: datetime, end_time: datetime,
                                             pin: Optional[str] = None) -> Optional[str]:
        """
        Create user using JSON and include access rights and optional PIN.
        This mirrors a more complete payload used in prior integrations, adding
        door rights and verify mode so PIN and face are usable for access.
        """
        try:
            url = f"{self.base_url}/ISAPI/AccessControl/UserInfo/Record?format=json"
            body = {
                "UserInfo": {
                    "employeeNo": str(employee_no),
                    "name": name,
                    "userType": "normal",
                    "Valid": {
                        "enable": True,
                        "beginTime": start_time.strftime('%Y-%m-%dT%H:%M:%S'),
                        "endTime": end_time.strftime('%Y-%m-%dT%H:%M:%S'),
                        "timeType": "local",
                    },
                    # Align with common verify mode; devices vary. Keep cardOrFace for compatibility.
                    "userVerifyMode": "cardOrFace",
                    # Basic door rights; most setups use door 1 + plan 1.
                    "doorRight": "1",
                    "RightPlan": [
                        {"doorNo": 1, "planTemplateNo": "1"}
                    ],
                    "checkUser": True,
                }
            }
            if pin:
                body["UserInfo"]["password"] = str(pin)
            logger.info("POST %s (UserInfo JSON with rights)", url)
            r = requests.post(url, json=body, auth=self.auth, timeout=15, verify=False)
            r.raise_for_status()
            return str(employee_no)
        except requests.HTTPError as e:
            msg = e.response.text if getattr(e, 'response', None) is not None else str(e)
            logger.exception("UserInfo Record (JSON+rights) failed: %s", msg)
            return None
        except Exception as e:
            logger.exception("UserInfo Record (JSON+rights) exception: %s", e)
            return None

    def _preprocess_face_image(self, image_content: bytes) -> Optional[bytes]:
        """
        Verify face presence and crop/resize to improve compatibility.
        - Detect the largest face using Haar cascade.
        - Crop with slight padding and resize to 480x480.
        - Encode JPEG with quality adjusted to keep size reasonable.
        Returns processed JPEG bytes, or original if OpenCV unavailable.
        """
        if not _CV2_AVAILABLE:
            logger.info("OpenCV not available; skipping face preprocessing")
            return image_content
        try:
            # Decode image bytes
            img_array = np.frombuffer(image_content, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is None:
                logger.warning("Failed to decode image for preprocessing; using original")
                return image_content

            # Detect faces
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            face_cascade = cv2.CascadeClassifier(cascade_path)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5, minSize=(60, 60))
            logger.info("Preprocess face: detected %d face(s)", len(faces))
            if len(faces) == 0:
                # No face detected; still return original to avoid blocking
                logger.warning("No face detected; proceeding with original image content")
                return image_content

            # Pick largest face
            (x, y, w, h) = max(faces, key=lambda r: r[2] * r[3])
            # Add padding around face
            pad_x = int(0.15 * w)
            pad_y = int(0.20 * h)
            x1 = max(x - pad_x, 0)
            y1 = max(y - pad_y, 0)
            x2 = min(x + w + pad_x, img.shape[1])
            y2 = min(y + h + pad_y, img.shape[0])
            crop = img[y1:y2, x1:x2]

            # Resize to square 480x480 maintaining aspect (pad if needed)
            target = 480
            h_c, w_c = crop.shape[:2]
            scale = target / max(h_c, w_c)
            resized = cv2.resize(crop, (int(w_c * scale), int(h_c * scale)), interpolation=cv2.INTER_AREA)
            # Pad to square
            h_r, w_r = resized.shape[:2]
            top = (target - h_r) // 2
            bottom = target - h_r - top
            left = (target - w_r) // 2
            right = target - w_r - left
            padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=[255, 255, 255])

            # Encode JPEG with sensible quality; reduce if too big (target <200KB)
            quality = 85
            for _ in range(4):
                ok, buf = cv2.imencode('.jpg', padded, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                if not ok:
                    break
                out = buf.tobytes()
                if len(out) <= 200_000 or quality <= 65:
                    return out
                quality -= 7
            # Fallback to original if encoding failed
            logger.warning("JPEG encode failed or too large; using original image")
            return image_content
        except Exception as e:
            logger.exception("Face preprocessing failed: %s", e)
            return image_content

    def create_user(self, employee_no: str, name: str, start_time: datetime, end_time: datetime) -> Optional[str]:
        """
        Create user per attached ISAPI spec.
        Primary: PUT /ISAPI/AccessControl/UserInfo/SetUp?format=json with application/json.
        Fallbacks: POST /ISAPI/AccessControl/UserInfo/Record (JSON), then XML Record.
        """
        # Primary per spec: SetUp JSON PUT
        try:
            url_setup = f"{self.base_url}/ISAPI/AccessControl/UserInfo/SetUp?format=json"
            body_setup = {
                "UserInfo": {
                    "employeeNo": str(employee_no),
                    "name": name,
                    "userType": "normal",
                    "valid": {
                        "enable": True,
                        "beginTime": start_time.strftime('%Y-%m-%dT%H:%M:%S'),
                        "endTime": end_time.strftime('%Y-%m-%dT%H:%M:%S')
                    },
                    "doorRight": "1",
                    "rightPlan": [1]
                }
            }
            logger.info("PUT %s (SetUp JSON)", url_setup)
            r_setup = requests.put(url_setup, json=body_setup, auth=self.auth, timeout=15, verify=False)
            r_setup.raise_for_status()
            return employee_no
        except requests.HTTPError as e_setup:
            body = e_setup.response.text if getattr(e_setup, 'response', None) is not None else str(e_setup)
            logger.exception("User SetUp (JSON) failed: %s", body)
        except Exception as e_setupo:
            logger.exception("User SetUp (JSON) failed: %s", e_setupo)

        # Fallback: Record JSON POST
        try:
            url_record_json = f"{self.base_url}/ISAPI/AccessControl/UserInfo/Record?format=json"
            body_record = {
                "UserInfo": {
                    "employeeNo": str(employee_no),
                    "name": name,
                    "userType": "normal",
                    "Valid": {
                        "enable": True,
                        "beginTime": start_time.strftime('%Y-%m-%dT%H:%M:%S'),
                        "endTime": end_time.strftime('%Y-%m-%dT%H:%M:%S')
                    }
                }
            }
            logger.info("POST %s (Record JSON)", url_record_json)
            r_rec = requests.post(url_record_json, json=body_record, auth=self.auth, timeout=15, verify=False)
            r_rec.raise_for_status()
            return employee_no
        except requests.HTTPError as e_rec:
            bodyr = e_rec.response.text if getattr(e_rec, 'response', None) is not None else str(e_rec)
            logger.exception("User Record (JSON) failed: %s", bodyr)
        except Exception as e_reco:
            logger.exception("User Record (JSON) failed: %s", e_reco)

        # Last resort: XML Record
        xml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<UserInfo version=\"2.0\" xmlns=\"http://www.isapi.org/ver20/XMLSchema\">
  <employeeNo>{employee_no}</employeeNo>
  <name>{name}</name>
  <userType>normal</userType>
  <Valid>
    <enable>true</enable>
    <beginTime>{start_time.strftime('%Y-%m-%dT%H:%M:%S')}</beginTime>
    <endTime>{end_time.strftime('%Y-%m-%dT%H:%M:%S')}</endTime>
  </Valid>
</UserInfo>"""
        try:
            self._post_xml("/ISAPI/AccessControl/UserInfo/Record", xml)
            return employee_no
        except Exception as e_xml:
            logger.exception("User Record (XML) failed: %s", e_xml)
            return None

    def set_password(self, employee_no: str, password: str) -> bool:
        """
        Set user's password/PIN per attached ISAPI using JSON Modify.
        Primary: PUT /ISAPI/AccessControl/UserInfo/Modify?format=json with application/json.
        Fallbacks: Password JSON, then XML Password, then XML ModifyPassword.
        """
        # Primary per spec: Modify JSON
        try:
            url_mod = f"{self.base_url}/ISAPI/AccessControl/UserInfo/Modify?format=json"
            body_mod = {"UserInfo": {"employeeNo": str(employee_no), "password": str(password)}}
            logger.info("PUT %s (Modify JSON)", url_mod)
            rm = requests.put(url_mod, json=body_mod, auth=self.auth, timeout=15, verify=False)
            rm.raise_for_status()
            return True
        except requests.HTTPError as em:
            bodym = em.response.text if getattr(em, 'response', None) is not None else str(em)
            logger.exception("User Modify (JSON) failed: %s", bodym)
        except Exception as emo:
            logger.exception("User Modify (JSON) failed: %s", emo)

        # Fallback: Password JSON
        try:
            url_pwd_json = f"{self.base_url}/ISAPI/AccessControl/UserInfo/Password?format=json"
            body_pwd = {"UserInfo": {"employeeNo": str(employee_no), "password": str(password)}}
            logger.info("PUT %s (Password JSON)", url_pwd_json)
            rpj = requests.put(url_pwd_json, json=body_pwd, auth=self.auth, timeout=15, verify=False)
            rpj.raise_for_status()
            return True
        except Exception as epj:
            logger.exception("User Password (JSON) failed: %s", epj)

        # Fallback: XML Password
        try:
            xml = f"""
                <UserInfo>
                    <employeeNo>{employee_no}</employeeNo>
                    <password>{password}</password>
                </UserInfo>
            """.strip()
            self._put_xml("/ISAPI/AccessControl/UserInfo/Password", xml)
            return True
        except Exception as epxml:
            logger.exception("User Password (XML) failed: %s", epxml)

        # Last resort: XML ModifyPassword
        try:
            xml_modify = f"""
                <UserPassword>
                    <employeeNo>{employee_no}</employeeNo>
                    <oldPassword></oldPassword>
                    <newPassword>{password}</newPassword>
                </UserPassword>
            """.strip()
            self._put_xml("/ISAPI/AccessControl/UserInfo/ModifyPassword", xml_modify)
            return True
        except Exception as emxml:
            logger.exception("User ModifyPassword (XML) failed: %s", emxml)
            return False

    def create_user_with_face_and_pin_base64(self, employee_no: str, name: str, password: str,
                                             image_content: bytes, start_time: datetime,
                                             end_time: datetime) -> bool:
        """
        Combined provisioning per DS-K1T342MFX-E1 reference:
        POST /ISAPI/AccessControl/UserInfo with XML containing employeeNo, name, password (PIN),
        Valid enable/begin/end, and faceImage base64.
        """
        try:
            processed = self._preprocess_face_image(image_content)
            face_b64 = base64.b64encode(processed).decode('ascii')
        except Exception as e:
            logger.exception("Failed to encode face image to base64: %s", e)
            return False

        # Minimal XML per reference, including validity window
        xml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<UserInfo version=\"2.0\" xmlns=\"http://www.isapi.org/ver20/XMLSchema\">
  <employeeNo>{employee_no}</employeeNo>
  <name>{name}</name>
  <password>{password}</password>
  <userType>normal</userType>
  <Valid>
    <enable>true</enable>
    <beginTime>{start_time.strftime('%Y-%m-%dT%H:%M:%S')}</beginTime>
    <endTime>{end_time.strftime('%Y-%m-%dT%H:%M:%S')}</endTime>
  </Valid>
  <faceImage>
    <data>{face_b64}</data>
  </faceImage>
</UserInfo>"""
        try:
            logger.info("POST %s", f"{self.base_url}/ISAPI/AccessControl/UserInfo")
            resp = self._post_xml("/ISAPI/AccessControl/UserInfo", xml)
            return True
        except requests.HTTPError as e:
            # Log device response body for diagnostics
            try:
                resp = getattr(e, 'response', None)
                msg = resp.text if resp is not None else str(e)
                logger.exception("Combined UserInfo add (XML) failed: %s", msg)
            except Exception:
                logger.exception("Combined UserInfo add (XML) failed without response text")
            return False
        except Exception as e:
            logger.exception("Failed to call combined UserInfo add: %s", e)
            return False

    def provision_user_with_face_and_pin(self, employee_no: str, name: str, image_content: bytes, pin: str,
                                         start_time: datetime, end_time: datetime) -> bool:
        """
        Full provisioning: create user, set PIN, optional face upload.
        If no face image is provided, user is still created with PIN.
        Try combined XML (UserInfo with face base64 + PIN) first for DS-K1T342MFX-E1.
        If that fails, fallback to legacy flow: create → upload face → set PIN.
        """
        # Attempt combined method when image and PIN provided
        if image_content and len(image_content) > 0 and pin:
            try:
                combined_ok = self.create_user_with_face_and_pin_base64(
                    employee_no, name, pin, image_content, start_time, end_time
                )
                if combined_ok:
                    return True
            except Exception:
                # Fall through to legacy flow
                pass

        # Legacy flow
        user_id = self.create_user(employee_no, name, start_time, end_time)
        if not user_id:
            return False
        # Set PIN first to avoid face upload failing on some firmwares
        pin_ok = self.set_password(employee_no, pin)
        # Upload face after PIN is set
        face_ok = True
        if image_content and len(image_content) > 0:
            try:
                face_ok = self.upload_face_image(employee_no, image_content)
            except Exception:
                face_ok = False
        return bool(pin_ok and face_ok)

    def upload_face_image(self, employee_no: str, image_content: bytes) -> bool:
        """
        Upload user's face image. Devices vary: UserPictureRecord or FDLib.
        Strategy:
        1) Prefer FDLib multipart (employee library) for recognition linkage
        2) Try FDLib FaceDataRecord JSON using faceURL (reference approach)
        3) Try FDLib JSON base64 (blackFD)
        4) Try UserPictureRecord variants (canonical, lowercase, employeeNo)
        Logs include response body to reveal device expectations.
        """
        # Helper: persist image to media for JSON faceURL
        def _save_image_and_get_url(emp_no: str, content: bytes) -> Optional[str]:
            base_url = getattr(settings, 'PUBLIC_BASE_URL', '')
            if not base_url:
                logger.warning("PUBLIC_BASE_URL not set; skipping FDLib JSON faceURL attempt")
                return None
            try:
                folder = Path(settings.MEDIA_ROOT) / 'fdlib_faces'
                folder.mkdir(parents=True, exist_ok=True)
                safe_name = f"{slugify(emp_no)}.jpg"
                file_path = folder / safe_name
                with open(file_path, 'wb') as f:
                    f.write(content)
                # Build URL: serve MEDIA_ROOT directly on 8005, no MEDIA_URL prefix
                base_url = base_url.rstrip('/')
                return f"{base_url}/fdlib_faces/{safe_name}"
            except Exception as e:
                logger.exception("Failed to save face image for FDLib JSON: %s", e)
                return None

        # 1) FDLib multipart preferred (employee library)
        try:
            processed_bytes = self._preprocess_face_image(image_content)
            url4 = f"{self.base_url}/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json"
            files4 = {
                'FaceLibType': (None, 'employee'),
                'clientType': (None, '2'),
                'employeeNo': (None, employee_no),
                'faceImage': ('face.jpg', processed_bytes, 'image/jpeg'),
            }
            logger.info("POST %s (FDLib multipart employee)", url4)
            r4 = requests.post(url4, files=files4, auth=self.auth, timeout=20, verify=False)
            r4.raise_for_status()
            return True
        except requests.HTTPError as e4:
            body4 = e4.response.text if getattr(e4, 'response', None) is not None else str(e4)
            logger.exception("FDLib multipart employee failed: %s", body4)
        except Exception as e4o:
            logger.exception("FDLib multipart employee failed: %s", e4o)

        # 2) FDLib JSON with faceURL (reference approach)
        try:
            face_url = _save_image_and_get_url(employee_no, image_content)
            if face_url:
                url_json = f"{self.base_url}/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json"
                body_employee = {
                    "faceLibType": "blackFD",
                    "FDID": "1",
                    "FPID": str(employee_no),
                    "name": "Visitor",
                    "bornTime": "",
                    "faceURL": face_url,
                }
                logger.info("POST %s (FDLib JSON faceURL)", url_json)
                rj = requests.post(url_json, json=body_employee, auth=self.auth, timeout=20, verify=False)
                rj.raise_for_status()
                return True
        except requests.HTTPError as ej:
            bodyj = ej.response.text if getattr(ej, 'response', None) is not None else str(ej)
            logger.exception("FDLib JSON faceURL failed: %s", bodyj)
        except Exception as ejo:
            logger.exception("FDLib JSON faceURL failed: %s", ejo)
        # 3) FDLib JSON base64 with blackFD (for devices exposing only blacklist library)
        try:
            processed_bytes2 = self._preprocess_face_image(image_content)
            b64 = base64.b64encode(processed_bytes2).decode('ascii')
            url_json_b64 = f"{self.base_url}/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json"
            body_black = {
                "faceLibType": "blackFD",
                "FDID": "1",
                "FPID": str(employee_no),
                "name": "Visitor",
                "bornTime": "",
                "faceImage": {"data": b64},
            }
            logger.info("POST %s (FDLib JSON base64 blackFD)", url_json_b64)
            rb = requests.post(url_json_b64, json=body_black, auth=self.auth, timeout=20, verify=False)
            rb.raise_for_status()
            return True
        except requests.HTTPError as eb:
            bodyb = eb.response.text if getattr(eb, 'response', None) is not None else str(eb)
            logger.exception("FDLib JSON base64 blackFD failed: %s", bodyb)
        except Exception as ebo:
            logger.exception("FDLib JSON base64 blackFD failed: %s", ebo)

        # 4) Canonical UserPictureRecord variants
        url1 = f"{self.base_url}/ISAPI/AccessControl/UserPictureRecord?format=json"
        processed_bytes = self._preprocess_face_image(image_content)
        files1 = {
            'UserID': (None, employee_no),
            'DeleteFlag': (None, 'false'),
            'faceImage': ('face.jpg', processed_bytes, 'image/jpeg'),
        }
        try:
            logger.info("POST %s", url1)
            r1 = requests.post(url1, files=files1, auth=self.auth, timeout=15, verify=False)
            r1.raise_for_status()
            return True
        except requests.HTTPError as e1:
            body1 = e1.response.text if getattr(e1, 'response', None) is not None else str(e1)
            logger.exception("UserPictureRecord (canonical) failed: %s", body1)
        except Exception as e1o:
            logger.exception("UserPictureRecord (canonical) failed: %s", e1o)

        # 2) Lowercase variant
        url2 = f"{self.base_url}/ISAPI/AccessControl/UserPictureRecord?format=json"
        files2 = {
            'userID': (None, employee_no),
            'deleteFlag': (None, 'false'),
            'faceImage': ('face.jpg', processed_bytes, 'image/jpeg'),
        }
        try:
            logger.info("POST %s (lowercase)", url2)
            r2 = requests.post(url2, files=files2, auth=self.auth, timeout=15, verify=False)
            r2.raise_for_status()
            return True
        except requests.HTTPError as e2:
            body2 = e2.response.text if getattr(e2, 'response', None) is not None else str(e2)
            logger.exception("UserPictureRecord (lowercase) failed: %s", body2)
        except Exception as e2o:
            logger.exception("UserPictureRecord (lowercase) failed: %s", e2o)

        # 3) employeeNo/name variant
        url3 = f"{self.base_url}/ISAPI/AccessControl/UserPictureRecord?format=json"
        files3 = {
            'employeeNo': (None, employee_no),
            'name': (None, 'Visitor'),
            'deleteFlag': (None, 'false'),
            'faceImage': ('face.jpg', processed_bytes, 'image/jpeg'),
        }
        try:
            logger.info("POST %s (employeeNo)", url3)
            r3 = requests.post(url3, files=files3, auth=self.auth, timeout=15, verify=False)
            r3.raise_for_status()
            return True
        except requests.HTTPError as e3:
            body3 = e3.response.text if getattr(e3, 'response', None) is not None else str(e3)
            logger.exception("UserPictureRecord (employeeNo) failed: %s", body3)
        except Exception as e3o:
            logger.exception("UserPictureRecord (employeeNo) failed: %s", e3o)

        return False