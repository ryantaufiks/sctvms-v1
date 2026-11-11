import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(BASE_DIR, 'vms', 'settings.py')

def update_settings(tunnel_url):
    """Update Django settings for Cloudflare Tunnel"""
    
    # Parse domain from URL
    if tunnel_url.startswith('https://'):
        domain = tunnel_url[8:]
    elif tunnel_url.startswith('http://'):
        domain = tunnel_url[7:]
    else:
        domain = tunnel_url
    
    # Remove trailing slash
    domain = domain.rstrip('/')
    tunnel_url = tunnel_url.rstrip('/')
    
    print(f"Domain: {domain}")
    print(f"URL: {tunnel_url}")
    print()
    
    with open(SETTINGS_PATH, 'r') as f:
        content = f.read()
    
    # 1. Add SECURE_PROXY_SSL_HEADER if not exists
    if 'SECURE_PROXY_SSL_HEADER' not in content:
        marker = '# Basic security flags'
        proxy_line = """# Trust Cloudflare proxy headers (X-Forwarded-Proto, X-Forwarded-For)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

"""
        content = content.replace(marker, proxy_line + marker)
        print('[OK] Added SECURE_PROXY_SSL_HEADER')
    else:
        print('[SKIP] SECURE_PROXY_SSL_HEADER already exists')
    
    # 2. Update ALLOWED_HOSTS
    old_hosts = re.search(r"ALLOWED_HOSTS\s*=\s*\[.*?\]", content, re.DOTALL)
    if old_hosts:
        new_hosts = f"""ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', '').split(',') if os.getenv('DJANGO_ALLOWED_HOSTS', '') else ['localhost', '127.0.0.1', '::1', '{domain}', '*']"""
        content = content[:old_hosts.start()] + new_hosts + content[old_hosts.end():]
        print('[OK] Updated ALLOWED_HOSTS')
    
    # 3. Update CSRF_TRUSTED_ORIGINS
    old_csrf = re.search(r"CSRF_TRUSTED_ORIGINS\s*=\s*\[.*?\]", content, re.DOTALL)
    if old_csrf:
        new_csrf = f"""CSRF_TRUSTED_ORIGINS = [
        'http://localhost',
        'http://127.0.0.1',
        'http://0.0.0.0',
        'http://{domain}',
        'https://{domain}',
        'http://*.sctvms.com',
        'https://*.sctvms.com',
    ]"""
        content = content[:old_csrf.start()] + new_csrf + content[old_csrf.end():]
        print('[OK] Updated CSRF_TRUSTED_ORIGINS')
    
    # Write updated settings
    with open(SETTINGS_PATH, 'w') as f:
        f.write(content)
    
    print()
    print('=' * 50)
    print('Configuration complete!')
    print('=' * 50)
    print()
    print('Next steps:')
    print('1. Run stop_server.bat')
    print('2. Run start_server.bat')
    print(f'3. Access: {tunnel_url}')

if __name__ == '__main__':
    if len(sys.argv) > 1:
        tunnel_url = sys.argv[1]
    else:
        tunnel_url = input('Enter your tunnel URL (e.g. https://hcibs.sctvms.com): ')
    
    if not tunnel_url:
        print('[ERROR] No URL entered!')
        sys.exit(1)
    
    update_settings(tunnel_url)
