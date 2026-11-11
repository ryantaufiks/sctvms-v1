# Dokumentasi Integrasi ALPR (Automatic License Plate Recognition)

## Daftar Isi
1. [Pendahuluan](#pendahuluan)
2. [Alur Kerja ALPR pada Sistem Lama](#alur-kerja-alur-kerja-alpr-pada-sistem-lama)
3. [Model dan Struktur Data](#model-dan-struktur-data)
4. [Implementasi pada Django](#implementasi-pada-django)
5. [Fitur Scan Plate Manual](#fitur-scan-plate-manual)
6. [Fitur Auto-Whitelisting](#fitur-auto-whitelisting)
7. [Manajemen Whitelist ALPR](#manajemen-whitelist-alpr)
8. [API Endpoints untuk Whitelist](#api-endpoints-untuk-whitelist)
9. [Pengujian dan Troubleshooting](#pengujian-dan-troubleshooting)
10. [Pertimbangan Keamanan](#pertimbangan-keamanan)

## Pendahuluan

Dokumen ini menjelaskan integrasi sistem ALPR (Automatic License Plate Recognition) dari kamera Dahua ke sistem VMS (Visitor Management System) berbasis Django. Integrasi ini memungkinkan pengenalan plat nomor kendaraan secara otomatis dan pembaruan status kendaraan di sistem VMS.

## Alur Kerja ALPR pada Sistem Lama

Sistem lama menggunakan CodeIgniter 3 dengan alur kerja sebagai berikut:

1. Kamera ALPR Dahua menangkap gambar plat nomor kendaraan
2. Kamera mengirimkan data XML ke endpoint callback API (`Api::index_post` dengan action "callback")
3. API memproses XML untuk mengekstrak nomor plat dan waktu
4. Data dicatat ke tabel `log_callback`
5. Sistem memeriksa apakah kendaraan masuk ("in") atau keluar ("out")
6. Untuk kendaraan masuk, sistem:
   - Memperbarui status di tabel `vms`
   - Memeriksa apakah kendaraan terdaftar di tabel `hosts` atau `preregistration`
   - Mengirim SMS notifikasi ke host atau pengguna jika kendaraan terdaftar
7. Untuk kendaraan keluar, sistem memperbarui status di tabel `vms`

## Model dan Struktur Data

### Tabel pada Sistem Lama

1. **log_callback**
   - LogID (PK)
   - Camera
   - Xml (menyimpan XML lengkap)
   - CreatedBy
   - CreatedOn

2. **vms**
   - id (PK)
   - plate_no
   - status (in/out)
   - check_in
   - check_out
   - ...

3. **hosts**
   - id (PK)
   - name
   - phone
   - plate_no
   - ...

4. **preregistration**
   - id (PK)
   - plate_no
   - phone
   - ...

5. **users**
   - id (PK)
   - phone
   - ...

### Model Django yang Direkomendasikan

```python
# models.py
from django.db import models

class Host(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    plate_no = models.CharField(max_length=20)
    # tambahkan field lain sesuai kebutuhan

class Vms(models.Model):
    plate_no = models.CharField(max_length=20)
    status = models.CharField(max_length=10, choices=[('in', 'In'), ('out', 'Out')])
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    # tambahkan field lain sesuai kebutuhan

class PreRegistration(models.Model):
    plate_no = models.CharField(max_length=20)
    phone = models.CharField(max_length=20)
    # tambahkan field lain sesuai kebutuhan

class CallbackLog(models.Model):
    camera = models.CharField(max_length=50)
    xml_data = models.TextField()
    created_by = models.CharField(max_length=50)
    created_on = models.DateTimeField(auto_now_add=True)
```

## Implementasi pada Django

### View untuk Callback ALPR

```python
# views.py
import xmltodict
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .models import CallbackLog, Vms, Host, PreRegistration
from .utils import send_sms

@csrf_exempt
def alpr_callback(request):
    if request.method == 'POST':
        try:
            # Ambil file XML yang diunggah
            xml_file = request.FILES.get('file')
            if not xml_file:
                return JsonResponse({'status': 'error', 'message': 'No file uploaded'}, status=400)
            
            # Baca dan parse XML
            xml_data = xml_file.read().decode('utf-8')
            data_dict = xmltodict.parse(xml_data)
            
            # Ekstrak informasi plat nomor dan waktu
            plate_info = data_dict.get('Message', {}).get('PlateResult', {})
            license_plate = plate_info.get('licensePlate', '')
            date_time = plate_info.get('dateTime', '')
            
            # Normalisasi plat nomor (hapus spasi, ubah ke huruf besar)
            license_plate = license_plate.replace(' ', '').upper()
            
            # Log callback
            log = CallbackLog.objects.create(
                camera=request.META.get('REMOTE_ADDR', 'unknown'),
                xml_data=xml_data,
                created_by='system'
            )
            
            # Tentukan apakah ini event masuk atau keluar
            # Logika ini perlu disesuaikan dengan kebutuhan spesifik
            # Misalnya berdasarkan kamera atau waktu
            is_entry = True  # Contoh sederhana, sesuaikan dengan logika bisnis
            
            if is_entry:
                # Proses kendaraan masuk
                vms_entry = Vms.objects.create(
                    plate_no=license_plate,
                    status='in',
                    check_in=timezone.now()
                )
                
                # Cek apakah kendaraan terdaftar
                host = Host.objects.filter(plate_no=license_plate).first()
                pre_reg = PreRegistration.objects.filter(plate_no=license_plate).first()
                
                # Kirim SMS jika kendaraan terdaftar
                if host and host.phone:
                    message = f"Kendaraan dengan plat nomor {license_plate} telah masuk pada {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    send_sms(host.phone, message)
                elif pre_reg and pre_reg.phone:
                    message = f"Kendaraan dengan plat nomor {license_plate} telah masuk pada {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    send_sms(pre_reg.phone, message)
            else:
                # Proses kendaraan keluar
                vms_entry = Vms.objects.filter(plate_no=license_plate, status='in').first()
                if vms_entry:
                    vms_entry.status = 'out'
                    vms_entry.check_out = timezone.now()
                    vms_entry.save()
            
            return JsonResponse({'status': 'success', 'message': 'Data processed successfully'})
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)
```

### Konfigurasi URL

```python
# urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('api/alpr/callback/', views.alpr_callback, name='alpr_callback'),
    # tambahkan URL lain sesuai kebutuhan
]
```

### Utilitas untuk Mengirim SMS

```python
# utils.py
from twilio.rest import Client
from django.conf import settings

def send_sms(phone_number, message):
    """
    Fungsi untuk mengirim SMS menggunakan Twilio
    """
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=message,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=phone_number
        )
        return True
    except Exception as e:
        # Log error
        print(f"Error sending SMS: {str(e)}")
        return False
```

## Fitur Auto-Whitelisting

Sistem VMS Django telah dilengkapi dengan fitur auto-whitelisting yang secara otomatis menambahkan nomor plat kendaraan ke whitelist kamera ALPR saat pre-registrasi dilakukan.

### Model ALPRWhitelist

```python
# models.py
class ALPRWhitelist(models.Model):
    plate_number = models.CharField(max_length=20, unique=True)
    visitor = models.ForeignKey('Visitor', on_delete=models.SET_NULL, null=True, blank=True)
    expires_at = models.DateTimeField()
    is_camera_synced = models.BooleanField(default=False)
    camera_sync_error = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"{self.plate_number} - Expires: {self.expires_at}"
```

### Alur Kerja Auto-Whitelisting

1. **Pre-Registrasi dengan Nomor Kendaraan**
   - User mengisi form pre-registrasi dengan nomor kendaraan
   - Sistem menghitung waktu kadaluarsa berdasarkan tanggal/waktu kedatangan yang diharapkan
   - Jika tidak ada waktu kedatangan, default 24 jam dari sekarang

2. **Pembuatan Entry Whitelist**
   - Sistem membuat entry ALPRWhitelist dengan nomor plat dan waktu kadaluarsa
   - Entry dikaitkan dengan visitor yang bersangkutan

3. **Sinkronisasi dengan Kamera**
   - Sistem mengirim perintah whitelist ke kamera Dahua menggunakan API
   - Status sinkronisasi disimpan di field `is_camera_synced`
   - Error sinkronisasi disimpan di field `camera_sync_error`

4. **Notifikasi Status**
   - Halaman sukses pre-registrasi menampilkan status whitelist
   - Pesan sukses atau peringatan ditampilkan berdasarkan hasil sinkronisasi

### Implementasi Auto-Whitelisting

```python
# alpr_utils.py
import requests
from requests.auth import HTTPDigestAuth
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def auto_whitelist_visitor_plate(plate_number, expires_at, visitor=None, created_by=None):
    """
    Menambahkan nomor plat ke whitelist ALPR secara otomatis
    """
    try:
        # Buat entry whitelist di database
        whitelist_entry = ALPRWhitelist.objects.create(
            plate_number=plate_number,
            visitor=visitor,
            expires_at=expires_at,
            created_by=created_by
        )
        
        # Kirim perintah ke kamera Dahua
        success = send_whitelist_to_camera(plate_number, expires_at)
        
        # Update status sinkronisasi
        whitelist_entry.is_camera_synced = success
        if not success:
            whitelist_entry.camera_sync_error = "Gagal mengirim ke kamera"
        whitelist_entry.save()
        
        return {
            'success': success,
            'whitelist_id': whitelist_entry.id,
            'message': 'Berhasil menambahkan ke whitelist' if success else 'Gagal sinkronisasi dengan kamera'
        }
        
    except Exception as e:
        logger.error(f"Error auto-whitelisting plate {plate_number}: {str(e)}")
        return {
            'success': False,
            'message': f'Error: {str(e)}'
        }

def send_whitelist_to_camera(plate_number, expires_at):
    """
    Mengirim perintah whitelist ke kamera Dahua
    """
    try:
        camera_config = DahuaConfiguration.objects.first()
        if not camera_config:
            return False
            
        # Format perintah whitelist untuk Dahua
        whitelist_data = {
            'method': 'whitelist.add',
            'params': {
                'plate': plate_number,
                'expires': expires_at.isoformat()
            }
        }
        
        response = requests.post(
            f"http://{camera_config.camera_ip}/cgi-bin/whitelist.cgi",
            json=whitelist_data,
            auth=HTTPDigestAuth(camera_config.username, camera_config.password),
            timeout=10
        )
        
        return response.status_code == 200
        
    except Exception as e:
        logger.error(f"Error sending whitelist to camera: {str(e)}")
        return False
```

## Manajemen Whitelist ALPR

Sistem menyediakan interface manajemen whitelist untuk admin dan staff.

### Fitur Interface Manajemen

1. **Dashboard Whitelist**
   - Statistik entry aktif dan kadaluarsa
   - Filter berdasarkan status (aktif/kadaluarsa/semua)
   - Pencarian berdasarkan nomor plat, nama visitor, atau perusahaan

2. **Tabel Whitelist**
   - Daftar semua entry whitelist dengan informasi lengkap
   - Status sinkronisasi kamera
   - Aksi untuk menghapus entry manual

3. **Tambah Whitelist Manual**
   - Form untuk menambah entry whitelist secara manual
   - Pilihan waktu kadaluarsa custom
   - Opsional kaitkan dengan visitor existing

### Akses dan Permissions

- **Admin**: Akses penuh ke semua fitur manajemen whitelist
- **Management**: Akses penuh ke semua fitur manajemen whitelist  
- **Staff**: Akses penuh ke semua fitur manajemen whitelist
- **Security Officer**: Tidak memiliki akses ke manajemen whitelist

## API Endpoints untuk Whitelist

Sistem menyediakan API endpoints untuk operasi whitelist programmatik.

### 1. Tambah Whitelist Manual

```
POST /visitors/api/whitelist-plate/
Content-Type: application/json

{
    "plate_number": "B1234CD",
    "expires_at": "2024-01-15T23:59:59",
    "visitor_id": 123  // optional
}
```

**Response:**
```json
{
    "success": true,
    "message": "Plate berhasil ditambahkan ke whitelist",
    "whitelist_id": 456
}
```

### 2. Hapus dari Whitelist

```
DELETE /visitors/api/remove-whitelist/
Content-Type: application/json

{
    "plate_number": "B1234CD"
}
```

atau

```
DELETE /visitors/api/remove-whitelist/
Content-Type: application/json

{
    "whitelist_id": 456
}
```

**Response:**
```json
{
    "success": true,
    "message": "Plate berhasil dihapus dari whitelist"
}
```

### 3. Status Whitelist

```
GET /visitors/api/whitelist-status/
```

**Response:**
```json
{
    "active_count": 25,
    "expired_count": 10,
    "entries": [
        {
            "id": 456,
            "plate_number": "B1234CD",
            "visitor_name": "John Doe",
            "expires_at": "2024-01-15T23:59:59",
            "is_expired": false,
            "is_camera_synced": true
        }
    ]
}
```

## Pengujian dan Troubleshooting

### Contoh Payload XML

```xml
<Message>
  <PlateResult>
    <licensePlate>B1234CD</licensePlate>
    <dateTime>2023-06-15T14:30:45</dateTime>
  </PlateResult>
</Message>
```

### Pengujian dengan cURL

```bash
curl -X POST -F "file=@sample.xml" http://yourdomain.com/api/alpr/callback/
```

### Troubleshooting Umum

1. **XML tidak dapat diproses**
   - Periksa format XML dari kamera
   - Pastikan struktur XML sesuai dengan yang diharapkan

2. **SMS tidak terkirim**
   - Periksa konfigurasi Twilio
   - Pastikan nomor telepon dalam format yang benar

3. **Kendaraan tidak terdeteksi sebagai terdaftar**
   - Periksa normalisasi plat nomor
   - Pastikan data di tabel Host dan PreRegistration sudah benar

4. **Auto-whitelisting gagal**
   - Periksa konfigurasi DahuaConfiguration di admin panel
   - Pastikan IP kamera, username, dan password sudah benar
   - Cek koneksi jaringan ke kamera ALPR
   - Periksa log error di field `camera_sync_error` pada ALPRWhitelist

5. **Whitelist tidak sinkron dengan kamera**
   - Verifikasi endpoint API whitelist kamera Dahua
   - Periksa format data yang dikirim ke kamera
   - Cek timeout koneksi (default 10 detik)
   - Pastikan kamera mendukung API whitelist management

6. **Interface manajemen whitelist tidak dapat diakses**
   - Periksa role user (harus staff ke atas)
   - Pastikan URL pattern sudah terdaftar di urls.py
   - Cek permission di view whitelist_management

## Pertimbangan Keamanan

1. **Autentikasi API**
   - Implementasikan autentikasi untuk endpoint callback
   - Batasi akses hanya dari IP kamera ALPR
   - Gunakan HTTPS untuk komunikasi dengan kamera

2. **Validasi Input**
   - Validasi semua input XML sebelum diproses
   - Batasi ukuran file XML yang diunggah
   - Validasi format nomor plat sebelum whitelist

3. **Logging**
   - Log semua aktivitas untuk audit trail
   - Simpan XML asli untuk keperluan debugging
   - Log semua operasi whitelist (tambah/hapus)

4. **Perlindungan Data**
   - Enkripsi data sensitif seperti nomor telepon
   - Terapkan kebijakan retensi data untuk log
   - Enkripsi kredensial kamera di database

5. **Keamanan Whitelist**
   - Batasi akses manajemen whitelist berdasarkan role
   - Implementasikan rate limiting untuk API whitelist
   - Audit trail untuk semua perubahan whitelist
   - Automatic cleanup untuk entry whitelist yang kadaluarsa

6. **Komunikasi Kamera**
   - Gunakan Digest Authentication untuk komunikasi dengan kamera
   - Validasi response dari kamera sebelum update status
   - Timeout yang wajar untuk mencegah hanging request
   - Retry mechanism dengan backoff untuk request yang gagal

---

Dokumen ini dibuat sebagai panduan untuk integrasi ALPR ke sistem VMS berbasis Django. Silakan sesuaikan implementasi dengan kebutuhan spesifik proyek Anda.