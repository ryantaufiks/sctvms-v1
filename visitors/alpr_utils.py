"""
ALPR Camera Utilities for Dahua Integration
Handles whitelisting operations and camera communication
"""

import requests
import logging
from django.conf import settings
from django.utils import timezone
from site_settings.models import DahuaConfiguration
import urllib.parse

logger = logging.getLogger(__name__)


class ALPRCameraManager:
    """Manager class for ALPR camera operations"""
    
    def __init__(self):
        self.config = self._get_camera_config()
    
    def _get_camera_config(self):
        """Get the camera configuration"""
        try:
            return DahuaConfiguration.objects.first()
        except Exception as e:
            logger.error(f"Failed to get camera configuration: {str(e)}")
            return None
    
    def is_camera_available(self):
        """Check if camera is configured and available"""
        return (
            self.config and 
            self.config.is_enabled and 
            self.config.camera_ip and 
            self.config.username and 
            self.config.password
        )
    
    def add_to_whitelist(self, plate_number, visitor_name=None, expiry_hours=24, begin_time=None, end_time=None, camera_target: str = 'default'):
        """
        Add a plate number to the ALPR camera whitelist using Dahua HTTP API V2.76
        Uses recordUpdater.cgi with TrafficRedList (official whitelist)

        camera_target: 'default' (main camera) or 'resident' (resident-specific camera)
        """
        # Resolve camera target configuration
        if not self.config:
            return {'success': False, 'error': 'ALPR camera configuration not found'}

        if camera_target == 'resident':
            if not (self.config.resident_is_enabled and self.config.resident_camera_ip and self.config.resident_username and self.config.resident_password):
                return {
                    'success': False,
                    'error': 'Resident camera is not configured or disabled'
                }
            base_url = self.config.resident_camera_url
            username = getattr(self.config, 'resident_username', self.config.username)
            password = getattr(self.config, 'resident_password', self.config.password)
        else:
            if not self.is_camera_available():
                return {
                    'success': False,
                    'error': 'ALPR camera is not configured or disabled'
                }
            base_url = self.config.camera_url
            username = self.config.username
            password = self.config.password
        
        try:
            normalized_plate = plate_number.replace(' ', '').upper()
            now = timezone.now()
            # Use provided begin/end times if available and clamp for immediate activation
            effective_begin = begin_time or now
            if effective_begin > now:
                effective_begin = now
            effective_end = end_time or (effective_begin + timezone.timedelta(hours=expiry_hours))
            if effective_end <= effective_begin:
                effective_end = effective_begin + timezone.timedelta(hours=max(1, expiry_hours))
            
            # Format timestamps for Dahua API (YYYY-MM-DD HH:MM:SS)
            begin_time_str = effective_begin.strftime('%Y-%m-%d %H:%M:%S')
            end_time_str = effective_end.strftime('%Y-%m-%d %H:%M:%S')

            # Official Dahua HTTP API V2.76: Insert Traffic RedList Record
            url = f"{base_url}/cgi-bin/recordUpdater.cgi"
            params = {
                'action': 'insert',
                'name': 'TrafficRedList',
                'PlateNumber': normalized_plate,
                'BeginTime': begin_time_str,
                'CancelTime': end_time_str,
                'Enable': 'true',
            }
            
            # Add visitor name if provided (Owner Name)
            if visitor_name:
                params['MasterOfCar'] = visitor_name[:50]  # Limit to 50 chars
            
            logger.info(f"Adding {normalized_plate} to Dahua whitelist via recordUpdater.cgi (target={camera_target})")
            
            # Use percent-encoding for spaces (avoid '+' becoming literal in camera UI)
            query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
            full_url = f"{url}?{query}"
            
            response = requests.get(
                full_url,
                auth=requests.auth.HTTPDigestAuth(username, password),
                timeout=self.config.timeout_seconds,
            )
            
            logger.info(f"Dahua API response: {response.status_code} - {response.text}")
            
            if response.status_code == 200:
                response_text = response.text.lower()
                # Dahua typically returns "ok", "success", or "RecNo=" for successful operations
                if ('ok' in response_text or 'success' in response_text or 
                    response.text.strip() == '' or 'recno=' in response_text):
                    logger.info(f"Successfully added {normalized_plate} to ALPR whitelist via recordUpdater.cgi")
                    return {
                        'success': True,
                        'message': f'Plate {normalized_plate} added to whitelist successfully',
                        'plate_number': normalized_plate,
                        'expires_at': effective_end
                    }
                else:
                    # Check for specific error messages
                    if 'already exist' in response_text or 'duplicate' in response_text:
                        logger.warning(f"Plate {normalized_plate} already exists in whitelist")
                        return {
                            'success': True,
                            'message': f'Plate {normalized_plate} already in whitelist',
                            'plate_number': normalized_plate,
                            'expires_at': effective_end
                        }
                    else:
                        error_msg = f"Camera returned unexpected response: {response.text}"
                        logger.error(error_msg)
                        return {
                            'success': False,
                            'error': error_msg
                        }
            else:
                error_msg = f"Camera responded with status {response.status_code}: {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except requests.exceptions.Timeout:
            logger.error(f"Timeout connecting to ALPR camera at {self.config.camera_ip}")
            return {
                'success': False,
                'error': f'Connection timeout after {self.config.timeout_seconds} seconds'
            }
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error to ALPR camera at {self.config.camera_ip}")
            return {
                'success': False,
                'error': 'Cannot connect to ALPR camera. Check network connection.'
            }
        except Exception as e:
            logger.error(f"Error adding plate to whitelist: {str(e)}")
            return {
                'success': False,
                'error': f'Unexpected error: {str(e)}'
            }

    def remove_from_whitelist(self, plate_number):
        """Remove a plate number from the ALPR whitelist"""
        if not self.is_camera_available():
            return {
                'success': False,
                'error': 'ALPR camera is not configured or disabled'
            }
        
        try:
            normalized_plate = plate_number.replace(' ', '').upper()

            # First, find the record to get RecNo
            find_url = f"{self.config.camera_url}/cgi-bin/recordFinder.cgi"
            find_params = {
                'action': 'find',
                'name': 'TrafficRedList',
                'condition.PlateNumber': normalized_plate,
                'count': 1
            }
            
            logger.info(f"Finding {normalized_plate} in Dahua whitelist to get RecNo")
            
            find_response = requests.get(
                find_url,
                params=find_params,
                auth=requests.auth.HTTPDigestAuth(self.config.username, self.config.password),
                timeout=self.config.timeout_seconds,
            )
            
            if find_response.status_code != 200:
                logger.error(f"Failed to find record: {find_response.status_code} - {find_response.text}")
                return {
                    'success': False,
                    'error': f'Failed to find record: {find_response.text}'
                }
            
            # Parse response to find RecNo
            response_text = find_response.text
            rec_no = None
            
            # Look for RecNo in the response
            import re
            rec_match = re.search(rf'records\[\d+\]\.RecNo=(\d+)', response_text)
            if rec_match:
                rec_no = rec_match.group(1)
                logger.info(f"Found RecNo {rec_no} for plate {normalized_plate}")
            else:
                logger.warning(f"Plate {normalized_plate} not found in whitelist")
                return {
                    'success': True,
                    'message': f'Plate {normalized_plate} was not in whitelist',
                    'plate_number': normalized_plate
                }

            # Now delete using RecNo
            delete_url = f"{self.config.camera_url}/cgi-bin/recordUpdater.cgi"
            delete_params = {
                'action': 'delete',
                'name': 'TrafficRedList',
                'RecNo': rec_no,
            }
            
            logger.info(f"Removing {normalized_plate} (RecNo: {rec_no}) from Dahua whitelist via recordUpdater.cgi")
            
            response = requests.get(
                delete_url,
                params=delete_params,
                auth=requests.auth.HTTPDigestAuth(self.config.username, self.config.password),
                timeout=self.config.timeout_seconds,
            )
            
            logger.info(f"Dahua API response: {response.status_code} - {response.text}")
            
            if response.status_code == 200:
                response_text = response.text.lower()
                if ('ok' in response_text or 'success' in response_text or 
                    response.text.strip() == '' or 'recno=' in response_text):
                    logger.info(f"Successfully removed {normalized_plate} from ALPR whitelist")
                    return {
                        'success': True,
                        'message': f'Plate {normalized_plate} removed from whitelist successfully',
                        'plate_number': normalized_plate
                    }
                elif 'not found' in response_text or 'not exist' in response_text:
                    logger.warning(f"Plate {normalized_plate} not found in whitelist")
                    return {
                        'success': True,
                        'message': f'Plate {normalized_plate} was not in whitelist',
                        'plate_number': normalized_plate
                    }
                else:
                    error_msg = f"Camera returned unexpected response: {response.text}"
                    logger.error(error_msg)
                    return {
                        'success': False,
                        'error': error_msg
                    }
            else:
                error_msg = f"Camera responded with status {response.status_code}: {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Network error communicating with ALPR camera: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"Unexpected error removing from whitelist: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }

    def get_whitelist_entries(self, plate_number=None, count=100):
        """
        Get whitelist entries from Dahua camera using recordFinder.cgi
        
        Args:
            plate_number (str, optional): Specific plate to search for
            count (int): Maximum number of results to return
            
        Returns:
            dict: Result with success status and whitelist entries
        """
        if not self.is_camera_available():
            return {
                'success': False,
                'error': 'ALPR camera is not configured or disabled'
            }
        
        try:
            # Official Dahua HTTP API V2.76: Find Traffic RedList Record
            url = f"{self.config.camera_url}/cgi-bin/recordFinder.cgi"
            params = {
                'action': 'find',
                'name': 'TrafficRedList',
                'count': count,
            }
            
            # Add specific plate search condition if provided
            if plate_number:
                normalized_plate = plate_number.replace(' ', '').upper()
                params['condition.PlateNumber'] = normalized_plate
            
            logger.info(f"Fetching whitelist entries from Dahua camera")
            
            response = requests.get(
                url,
                params=params,
                auth=requests.auth.HTTPDigestAuth(self.config.username, self.config.password),
                timeout=self.config.timeout_seconds,
            )
            
            if response.status_code == 200:
                logger.info(f"Successfully retrieved whitelist entries")
                return {
                    'success': True,
                    'data': response.text,
                    'entries_count': response.text.count('PlateNumber=') if 'PlateNumber=' in response.text else 0
                }
            else:
                error_msg = f"Camera responded with status {response.status_code}: {response.text}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except Exception as e:
            logger.error(f"Error fetching whitelist entries: {str(e)}")
            return {
                'success': False,
                'error': f'Unexpected error: {str(e)}'
            }
    
    def sync_whitelist_entry(self, whitelist_entry):
        """
        Sync a single whitelist entry to the camera
        
        Args:
            whitelist_entry: ALPRWhitelist model instance
        
        Returns:
            dict: Result with success status and message
        """
        from .models import ALPRWhitelist
        
        if whitelist_entry.is_expired:
            # Remove expired entries
            result = self.remove_from_whitelist(whitelist_entry.plate_number)
            if result['success']:
                whitelist_entry.is_active = False
                whitelist_entry.save()
        else:
            # Add/update active entries
            expiry_hours = int((whitelist_entry.expires_at - timezone.now()).total_seconds() / 3600)
            visitor_name = whitelist_entry.visitor.full_name if whitelist_entry.visitor else None
            result = self.add_to_whitelist(
                whitelist_entry.plate_number,
                visitor_name,
                max(1, expiry_hours)  # Minimum 1 hour
            )
        
        # Update sync status
        whitelist_entry.sync_attempts += 1
        whitelist_entry.last_sync_attempt = timezone.now()
        
        if result['success']:
            whitelist_entry.synced_to_camera = True
            whitelist_entry.sync_error = None
        else:
            whitelist_entry.synced_to_camera = False
            whitelist_entry.sync_error = result.get('error', 'Unknown error')
        
        whitelist_entry.save()
        return result


def auto_whitelist_visitor_plate(visitor, created_by=None, expiry_hours=24):
    """
    Automatically whitelist a visitor's plate number
    
    Args:
        visitor: Visitor model instance
        created_by: User who triggered the whitelisting
        expiry_hours: Hours until whitelist expires
    
    Returns:
        dict: Result with success status and message
    """
    from .models import ALPRWhitelist
    
    if not visitor.vehicle_number:
        return {
            'success': False,
            'error': 'No vehicle number provided for visitor'
        }
    
    try:
        # Calculate expiry time
        expires_at = timezone.now() + timezone.timedelta(hours=expiry_hours)
        
        # Create or update whitelist entry
        whitelist_entry, created = ALPRWhitelist.objects.get_or_create(
            visitor=visitor,
            plate_number=visitor.vehicle_number,
            defaults={
                'expires_at': expires_at,
                'created_by': created_by,
                'is_active': True
            }
        )
        
        if not created:
            # Update existing entry
            whitelist_entry.expires_at = expires_at
            whitelist_entry.is_active = True
            whitelist_entry.save()
        
        # Sync to camera
        camera_manager = ALPRCameraManager()
        sync_result = camera_manager.sync_whitelist_entry(whitelist_entry)
        
        if sync_result['success']:
            logger.info(f"Successfully whitelisted plate {visitor.vehicle_number} for visitor {visitor.full_name}")
            return {
                'success': True,
                'message': f'Plate {visitor.vehicle_number} has been whitelisted for {expiry_hours} hours',
                'whitelist_entry': whitelist_entry
            }
        else:
            logger.warning(f"Failed to sync whitelist to camera: {sync_result.get('error')}")
            return {
                'success': False,
                'error': f"Whitelist created but camera sync failed: {sync_result.get('error')}",
                'whitelist_entry': whitelist_entry
            }
            
    except Exception as e:
        logger.error(f"Error auto-whitelisting visitor plate: {str(e)}")
        return {
            'success': False,
            'error': f'Failed to whitelist plate: {str(e)}'
        }