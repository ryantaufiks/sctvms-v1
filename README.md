# Visitor Management System (VMS)

A comprehensive Django-based Visitor Management System with integrated ALPR (Automatic License Plate Recognition) capabilities, designed for modern facilities requiring secure and efficient visitor tracking.

## 🚀 Features

### Core Functionality
- **Pre-Registration System**: Online visitor registration with QR code generation
- **Walk-in Registration**: On-site visitor registration and check-in
- **Digital Visitor Passes**: Automated pass generation with QR codes
- **Check-out Management**: Streamlined visitor departure tracking
- **Comprehensive Reporting**: Analytics and visitor reports with export capabilities

### ALPR Integration ⭐ **NEW**
- **Auto-Whitelisting**: Automatic vehicle whitelisting for pre-registered visitors
- **Dahua Camera Integration**: Real-time communication with ALPR cameras
- **Whitelist Management**: Admin interface for managing vehicle whitelist entries
- **Expiry Management**: Automatic cleanup of expired whitelist entries
- **API Endpoints**: RESTful APIs for whitelist operations

### Security & Access Control
- **Role-based Access Control**: Admin, staff, and security guard permissions
- **Multi-site Support**: Manage multiple locations from a single system
- **Audit Trails**: Comprehensive logging of all system activities
- **Data Protection**: Secure handling of visitor information

### User Experience
- **Responsive Design**: Mobile-friendly interface for all devices
- **Multi-language Support**: Internationalization ready
- **Real-time Notifications**: SMS and email notifications
- **QR Code Verification**: Quick visitor verification using QR codes

## 🏗️ System Architecture

### Technology Stack
- **Backend**: Django 4.2+ (Python)
- **Database**: SQLite (development) / PostgreSQL (production)
- **Frontend**: HTML5, CSS3, JavaScript, Bootstrap
- **ALPR Integration**: Dahua camera API
- **Notifications**: Twilio SMS integration

### Key Models
- **Visitor**: Core visitor information and tracking
- **PreRegistration**: Pre-registration data and validation
- **ALPRWhitelist**: Vehicle whitelist management ⭐ **NEW**
- **SiteSettings**: Multi-site configuration
- **User Management**: Role-based access control

## 📋 Prerequisites

- Python 3.8+
- Django 4.2+
- SQLite (included) or PostgreSQL
- Dahua ALPR camera (for ALPR features)
- Twilio account (for SMS notifications)

## 🛠️ Installation

### Quick Start (Windows)
```bash
# Clone the repository
git clone <repository-url>
cd monolith_vms

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Start development server
python manage.py runserver 0.0.0.0:8004
```

### Quick Start (Linux)
```bash
# Clone the repository
git clone <repository-url>
cd monolith_vms

# Run installation script
chmod +x scripts/install_linux.sh
./scripts/install_linux.sh

# Start development server
python manage.py runserver
```

For detailed installation instructions, see:
- [Windows Installation Guide](INSTALLATION_WINDOWS.txt)
- [Linux Installation Guide](INSTALLATION_LINUX.txt)

## 🔧 Configuration

### ALPR Camera Setup ⭐ **NEW**
1. Configure camera settings in Django admin
2. Set up camera credentials and IP addresses
3. Test camera connectivity using the admin interface
4. Enable auto-whitelisting in site settings

### SMS Notifications
1. Create a Twilio account
2. Add Twilio credentials to settings
3. Configure SMS templates in admin

### Multi-site Configuration
1. Access Django admin panel
2. Navigate to Site Settings
3. Add your facility information
4. Configure categories and access levels

## 📖 Usage

### For Visitors
1. **Pre-Registration**: Visit the pre-registration portal
2. **Fill Details**: Complete the registration form including vehicle information
3. **Auto-Whitelisting**: Vehicle is automatically added to ALPR whitelist ⭐ **NEW**
4. **Receive Pass**: Get QR code via email/SMS
5. **Arrival**: Show QR code at security for quick verification

### For Security Staff
1. **Verify Visitors**: Scan QR codes for quick verification
2. **Walk-in Registration**: Register visitors on-site
3. **Check-out**: Process visitor departures
4. **Monitor ALPR**: View real-time ALPR events and whitelist status ⭐ **NEW**

### For Administrators
1. **Manage Users**: Create and manage staff accounts
2. **Configure Settings**: Set up site-specific configurations
3. **ALPR Management**: Manage vehicle whitelist entries ⭐ **NEW**
4. **View Reports**: Access comprehensive analytics and reports
5. **System Monitoring**: Monitor system performance and logs

## 🔐 Security Features

### Data Protection
- Encrypted sensitive data storage
- Secure API authentication
- Input validation and sanitization
- CSRF protection

### ALPR Security ⭐ **NEW**
- HTTPS communication with cameras
- Digest authentication for camera APIs
- Rate limiting for whitelist operations
- Automatic cleanup of expired entries
- Comprehensive audit trails

### Access Control
- Role-based permissions
- Session management
- Password policies
- Activity logging

## 📊 API Documentation

### ALPR Whitelist APIs ⭐ **NEW**
```
POST /api/alpr/whitelist/add/     # Add vehicle to whitelist
DELETE /api/alpr/whitelist/remove/ # Remove vehicle from whitelist
GET /api/alpr/whitelist/check/    # Check whitelist status
GET /api/alpr/whitelist/list/     # List all whitelist entries
```

### Visitor APIs
```
POST /api/visitors/register/      # Register new visitor
GET /api/visitors/verify/         # Verify visitor QR code
POST /api/visitors/checkout/      # Check out visitor
```

## 📁 Project Structure
```
monolith_vms/
├── accounts/           # User authentication and management
├── dashboard/          # Main dashboard views
├── reports/           # Analytics and reporting
├── site_settings/     # Multi-site configuration
├── user_management/   # User administration
├── visitors/          # Core visitor management
│   ├── alpr_utils.py  # ALPR integration utilities ⭐ NEW
│   └── models.py      # Including ALPRWhitelist model ⭐ NEW
├── templates/         # HTML templates
├── static/           # Static files and diagrams
├── media/            # Uploaded files and QR codes
└── docs/             # Documentation files
```

## 🧪 Testing
```
python manage.py test
```

### ALPR Testing ⭐ **NEW**
```
# Test camera connectivity
python manage.py test visitors.tests.test_alpr

# Test whitelist operations
curl -X POST http://localhost:8004/api/alpr/whitelist/add/ \
-   -H "Content-Type: application/json" \
-   -d '{"plate_number": "ABC123", "expiry_hours": 24}'
```

## 📚 Documentation
```
- [Technical Documentation](technical_documentation.txt)
- [ALPR Integration Guide](ALPR_Integration.md)
- [Phase 1 Enhancements](PHASE1_ENHANCEMENTS.md)
- [Phase 2 Planning](PHASE2_PLANNING.md)
```

## 🔄 Recent Updates
```
### Version 2.1.0 - ALPR Auto-Whitelisting ⭐ **NEW**
- Added automatic vehicle whitelisting for pre-registered visitors
- Integrated Dahua ALPR camera support
- Created comprehensive whitelist management interface
- Implemented RESTful APIs for whitelist operations
- Added expiry management and automatic cleanup
- Enhanced security with camera authentication

### Version 2.0.0 - Core System
- Complete Django-based VMS implementation
- Multi-site support
- Comprehensive reporting system
- QR code generation and verification
- SMS notification integration
```

## 🤝 Contributing
```
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request
```

## 📄 License
```
This project is proprietary software. All rights reserved.
```

## 🆘 Support
```
For technical support or questions:
- Check the [Technical Documentation](technical_documentation.txt)
- Review the [ALPR Integration Guide](ALPR_Integration.md)
- Contact the development team
```

## 🎯 Roadmap
```
### Upcoming Features
- Mobile application for visitors
- Advanced analytics dashboard
- Integration with additional camera brands
- Facial recognition capabilities
- IoT sensor integration
```

---

**Monolith VMS** - Secure, Efficient, Modern Visitor Management

## Change Log
```
### 2025-10-25
- Added visitor Self Registration (Face + PIN) flow:
  - New fields on `Visitor`: `access_pin`, `face_image`, `terminal_user_id`
  - Self-register page with face capture and form submission
  - Hikvision Face Terminal provisioning with face+PIN and 24-hour validity
  - Print Pass updated to display PIN and access instructions
- Standardized dev server port to `8004` across docs and examples