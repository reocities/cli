#!/usr/bin/env python3
"""
Reocities CLI - Command line interface for managing your Reocities site
"""
import os
import sys
import json
import requests
import argparse
import mimetypes
from pathlib import Path
import configparser
from typing import Optional, List
import fnmatch

__version__ = "1.0.1"

class ReocitiesConfig:
    def __init__(self):
        self.config_dir = Path.home() / '.reocities'
        self.config_file = self.config_dir / 'config'
        self.config_dir.mkdir(exist_ok=True)
        
    def load_config(self) -> Optional[str]:
        """Load API key from config file"""
        if not self.config_file.exists():
            return None
        
        config = configparser.ConfigParser()
        config.read(self.config_file)
        
        try:
            return config['default']['api_key']
        except KeyError:
            return None
    
    def save_config(self, api_key: str):
        """Save API key to config file"""
        config = configparser.ConfigParser()
        config['default'] = {'api_key': api_key}
        
        with open(self.config_file, 'w') as f:
            config.write(f)
        
        os.chmod(self.config_file, 0o600)

class ReocitiesAPI:
    def __init__(self, api_key: str, base_url: str = "https://reocities.xyz"):
        self.api_key = api_key
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'X-API-Key': api_key,
            'User-Agent': f'reocities-cli/{__version__}'
        })
    
    def _handle_response(self, response: requests.Response) -> dict:
        """Handle API response and parse JSON safely"""
        try:
            if not response.text.strip():
                return {'error': f'Empty response from server (HTTP {response.status_code})'}
            
            data = response.json()
            
            if response.status_code >= 400:
                if isinstance(data, dict) and 'error' not in data:
                    data['error'] = f'HTTP {response.status_code}: {response.reason}'
            
            return data
            
        except json.JSONDecodeError:
            return {
                'error': f'Invalid JSON response (HTTP {response.status_code})',
                'raw_response': response.text[:500] 
            }
        except Exception as e:
            return {'error': f'Unexpected error parsing response: {str(e)}'}
    
    def upload_file(self, file_path: Path, remote_path: str = None, overwrite: bool = True) -> dict:
        """Upload a single file"""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        try:
            import urllib3
            import urllib.parse
            
            file_content = file_path.read_bytes()
            mime_type = mimetypes.guess_type(str(file_path))[0] or 'application/octet-stream'
            
            fields = {
                'overwrite': str(overwrite).lower(),
                'file': (file_path.name, file_content, mime_type)
            }
            
            if remote_path:
                fields['folder'] = remote_path
            
            encoded_data, content_type = urllib3.filepost.encode_multipart_formdata(fields)
            
            headers = {
                'Content-Type': content_type,
                'X-API-Key': self.api_key,
                'User-Agent': f'reocities-cli/{__version__}'
            }
            
            http = urllib3.PoolManager()
            response = http.request('POST', f"{self.base_url}/api/upload", body=encoded_data, headers=headers)
            
            response_data = {
                'status_code': response.status,
                'text': response.data.decode('utf-8'),
                'headers': dict(response.headers)
            }
            
            if response.status >= 400:
                return {'error': f'HTTP {response.status}: {response_data["text"]}'}
            
            try:
                return json.loads(response_data['text'])
            except json.JSONDecodeError:
                return {'error': 'Invalid JSON response', 'raw_response': response_data['text'][:500]}
                
        except Exception as e:
            return {'error': f'Upload failed: {str(e)}'}
    
    def upload_files_bulk(self, files: List[tuple], folder: str = None, overwrite: bool = True) -> dict:
        """Upload multiple files at once (max 10)"""
        if len(files) > 10:
            raise ValueError("Maximum 10 files per bulk upload")
        
        try:
            import urllib3
            
            fields = {'overwrite': str(overwrite).lower()}
            if folder:
                fields['folder'] = folder
            
            for file_path, filename in files:
                file_content = Path(file_path).read_bytes()
                if len(file_content) == 0:
                    return {'error': f'File {filename} is empty'}
                
                mime_type = mimetypes.guess_type(str(file_path))[0]
                if not mime_type:
                    ext = Path(file_path).suffix.lower()
                    if ext == '.html':
                        mime_type = 'text/html'
                    elif ext == '.css':
                        mime_type = 'text/css'
                    elif ext == '.js':
                        mime_type = 'text/javascript'
                    elif ext == '.txt':
                        mime_type = 'text/plain'
                    else:
                        mime_type = 'application/octet-stream'
                
                fields['files[]'] = (filename, file_content, mime_type)
            
            encoded_data, content_type = urllib3.filepost.encode_multipart_formdata(fields)
            
            headers = {
                'Content-Type': content_type,
                'X-API-Key': self.api_key,
                'User-Agent': f'reocities-cli/{__version__}'
            }
            
            http = urllib3.PoolManager()
            response = http.request('POST', f"{self.base_url}/api/bulk-upload", body=encoded_data, headers=headers)
            
            if response.status >= 400:
                return {'error': f'HTTP {response.status}: {response.data.decode("utf-8")}'}
            
            try:
                return json.loads(response.data.decode('utf-8'))
            except json.JSONDecodeError:
                return {'error': 'Invalid JSON response', 'raw_response': response.data.decode('utf-8')[:500]}
                
        except Exception as e:
            return {'error': f'Bulk upload failed: {str(e)}'}
    
    def list_files(self, folder: str = None, recursive: bool = False) -> dict:
        """List files on the site"""
        try:
            params = {}
            if folder:
                params['folder'] = folder
            if recursive:
                params['recursive'] = 'true'
            
            response = self.session.get(f"{self.base_url}/api/files", params=params)
            return self._handle_response(response)
        except Exception as e:
            return {'error': f'List files failed: {str(e)}'}
    
    def delete_file(self, path: str) -> dict:
        """Delete a file or folder"""
        try:
            import urllib3
            
            data = json.dumps({'path': path})
            
            headers = {
                'Content-Type': 'application/json',
                'X-API-Key': self.api_key,
                'User-Agent': f'reocities-cli/{__version__}'
            }
            
            http = urllib3.PoolManager()
            response = http.request('DELETE', f"{self.base_url}/api/files", body=data, headers=headers)
            
            if response.status >= 400:
                return {'error': f'HTTP {response.status}: {response.data.decode("utf-8")}'}
            
            try:
                return json.loads(response.data.decode('utf-8'))
            except json.JSONDecodeError:
                return {'error': 'Invalid JSON response', 'raw_response': response.data.decode('utf-8')[:500]}
                
        except Exception as e:
            return {'error': f'Delete failed: {str(e)}'}
    
    def create_folder(self, name: str, parent: str = None) -> dict:
        """Create a new folder"""
        try:
            data = {'name': name}
            if parent:
                data['parent'] = parent
            
            response = self.session.post(f"{self.base_url}/api/folders", data=data)
            return self._handle_response(response)
        except Exception as e:
            return {'error': f'Create folder failed: {str(e)}'}

class ReocitiesCLI:
    def __init__(self):
        self.config = ReocitiesConfig()
        self.api = None
        
    def load_gitignore(self, directory: Path) -> List[str]:
        """Load .gitignore patterns"""
        gitignore_file = directory / '.gitignore'
        if not gitignore_file.exists():
            return []
        
        patterns = []
        with open(gitignore_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    patterns.append(line)
        return patterns
    
    def should_ignore(self, file_path: Path, gitignore_patterns: List[str], base_dir: Path) -> bool:
        """Check if file should be ignored based on gitignore patterns"""
        relative_path = file_path.relative_to(base_dir)
        
        for pattern in gitignore_patterns:
            if fnmatch.fnmatch(str(relative_path), pattern) or fnmatch.fnmatch(file_path.name, pattern):
                return True
        return False
    
    def login(self, api_key: str):
        """Login with API key"""
        test_api = ReocitiesAPI(api_key)
        result = test_api.list_files()
        
        if 'error' in result:
            print(f"Error: {result['error']}")
            if 'raw_response' in result:
                print(f"Server response: {result['raw_response']}")
            return False
        
        self.config.save_config(api_key)
        print("Successfully logged in!")
        return True
    
    def logout(self):
        """Remove stored API key"""
        if self.config.config_file.exists():
            self.config.config_file.unlink()
            print("Logged out successfully")
        else:
            print("Not currently logged in")
    
    def ensure_authenticated(self) -> bool:
        """Ensure user is authenticated"""
        api_key = self.config.load_config()
        if not api_key:
            print("Error: Not logged in. Please run 'reocities login <your-api-key>' first.")
            return False
        
        self.api = ReocitiesAPI(api_key)
        return True
    
    def push(self, directory: str):
        """Push entire directory to site"""
        if not self.ensure_authenticated():
            return
        
        dir_path = Path(directory).resolve()
        if not dir_path.exists() or not dir_path.is_dir():
            print(f"Error: Directory '{directory}' does not exist")
            return
        
        gitignore_patterns = self.load_gitignore(dir_path)
        
        files_to_upload = []
        for file_path in dir_path.rglob('*'):
            if file_path.is_file():
                if not self.should_ignore(file_path, gitignore_patterns, dir_path):
                    relative_path = file_path.relative_to(dir_path)
                    files_to_upload.append((file_path, str(relative_path)))
        
        if not files_to_upload:
            print("No files to upload")
            return
        
        print(f"Found {len(files_to_upload)} files to upload...")
        
        uploaded_count = 0
        failed_count = 0
        
        for i in range(0, len(files_to_upload), 10):
            batch = files_to_upload[i:i+10]
            
            files_data = []
            for file_path, relative_path in batch:
                files_data.append((file_path, relative_path))
            
            result = self.api.upload_files_bulk(files_data)
            
            if 'error' in result:
                print(f"Error uploading batch: {result['error']}")
                if 'raw_response' in result:
                    print(f"Server response: {result['raw_response']}")
                failed_count += len(batch)
                continue
            
            if result.get('success'):
                batch_uploaded = len(result.get('uploaded', []))
                batch_failed = len(result.get('failed', []))
                uploaded_count += batch_uploaded
                failed_count += batch_failed
                
                for file_info in result.get('uploaded', []):
                    print(f"✓ {file_info.get('path', file_info.get('filename', 'unknown'))}")
                
                for file_info in result.get('failed', []):
                    print(f"✗ {file_info.get('filename', 'unknown')}: {file_info.get('error', 'Unknown error')}")
            else:
                print(f"Error uploading batch: {result.get('message', 'Unknown error')}")
                failed_count += len(batch)
        
        print(f"\nUpload complete: {uploaded_count} succeeded, {failed_count} failed")
    
    def upload(self, files: List[str], folder: str = None):
        """Upload individual files"""
        if not self.ensure_authenticated():
            return
        
        for file_path_str in files:
            file_path = Path(file_path_str)
            if not file_path.exists():
                print(f"Error: File '{file_path_str}' does not exist")
                continue
            
            result = self.api.upload_file(file_path, folder)
            
            if 'error' in result:
                print(f"✗ Failed to upload {file_path.name}: {result['error']}")
                if 'raw_response' in result:
                    print(f"Server response: {result['raw_response']}")
            elif result.get('success'):
                print(f"✓ Uploaded {result.get('filename', file_path.name)} to {result.get('path', 'unknown path')}")
            else:
                print(f"✗ Failed to upload {file_path.name}: {result.get('message', 'Unknown error')}")
    
    def list_files(self, folder: str = None, recursive: bool = False):
        """List files on the site"""
        if not self.ensure_authenticated():
            return
        
        result = self.api.list_files(folder, recursive)
        
        if 'error' in result:
            print(f"Error: {result['error']}")
            if 'raw_response' in result:
                print(f"Server response: {result['raw_response']}")
            return
        
        if result.get('success'):
            files = result.get('files', [])
            if not files:
                print("No files found")
                return
            
            print(f"Files in {'/' + folder if folder else 'root'}:")
            for file_info in files:
                size = file_info.get('size')
                if size is not None and isinstance(size, (int, float)):
                    if size < 1024:
                        size_str = f"{size:,} bytes"
                    else:
                        size_str = f"{size/1024:.1f} KB"
                else:
                    size_str = "unknown size"
                
                file_path = file_info.get('path', file_info.get('name', 'unknown'))
                print(f"  {file_path} ({size_str})")
        else:
            print(f"Error: {result.get('message', 'Unknown error')}")
    
    def delete(self, paths: List[str]):
        """Delete files from the site"""
        if not self.ensure_authenticated():
            return
        
        for path in paths:
            result = self.api.delete_file(path)
            
            if 'error' in result:
                print(f"✗ Failed to delete {path}: {result['error']}")
                if 'raw_response' in result:
                    print(f"Server response: {result['raw_response']}")
            elif result.get('success'):
                print(f"✓ Deleted {path}")
            else:
                print(f"✗ Failed to delete {path}: {result.get('message', 'Unknown error')}")

def print_banner():
    """Print the Reocities CLI banner"""
    print("""
 ____                _ _   _           
|  _ \ ___  ___   ___(_) |_(_) ___  ___ 
| |_) / _ \/ _ \ / __| | __| |/ _ \/ __|
|  _ <  __/ (_) | (__| | |_| |  __/\__ \\
|_| \_\___|\___/ \___|_|\__|_|\___||___/
                                       
Reocities CLI - Manage your site from the command line
""")

def main():
    parser = argparse.ArgumentParser(
        description='Reocities CLI - Command line interface for managing your Reocities site',
        prog='reocities'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    login_parser = subparsers.add_parser('login', help='Login with your API key')
    login_parser.add_argument('api_key', help='Your Reocities API key')
    
    subparsers.add_parser('logout', help='Remove stored API key')
    
    push_parser = subparsers.add_parser('push', help='Upload entire directory to your site')
    push_parser.add_argument('directory', nargs='?', default='.', help='Directory to upload (default: current directory)')
    
    upload_parser = subparsers.add_parser('upload', help='Upload individual files')
    upload_parser.add_argument('files', nargs='+', help='Files to upload')
    upload_parser.add_argument('--folder', help='Target folder on site')
    
    list_parser = subparsers.add_parser('list', help='List files on your site')
    list_parser.add_argument('--folder', help='Specific folder to list')
    list_parser.add_argument('--recursive', action='store_true', help='Include subdirectories')
    
    delete_parser = subparsers.add_parser('delete', help='Delete files from your site')
    delete_parser.add_argument('paths', nargs='+', help='Paths to delete')
    
    subparsers.add_parser('version', help='Show version information')
    
    args = parser.parse_args()
    
    if not args.command:
        print_banner()
        parser.print_help()
        return
    
    cli = ReocitiesCLI()
    
    if args.command == 'login':
        cli.login(args.api_key)
    elif args.command == 'logout':
        cli.logout()
    elif args.command == 'push':
        cli.push(args.directory)
    elif args.command == 'upload':
        cli.upload(args.files, args.folder)
    elif args.command == 'list':
        cli.list_files(args.folder, args.recursive)
    elif args.command == 'delete':
        cli.delete(args.paths)
    elif args.command == 'version':
        print(f"Reocities CLI version {__version__}")

if __name__ == '__main__':
    main()
