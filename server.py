#!/usr/bin/env python3
"""
File Finder - ローカルファイル検索サーバー
ブラウザから素早くファイルを検索し、Finderで開けるツール
"""

import os
import sys
import json
import signal
import subprocess
import urllib.parse
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
import mimetypes
import socket

PORT = 8765
PID_FILE = "/tmp/file-finder.pid"


def kill_existing_server():
    """既存のサーバープロセスを停止する"""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, signal.SIGTERM)
            print(f"   ⚠️  既存のサーバー (PID {old_pid}) を停止しました")
            import time
            time.sleep(0.5)
        except (ProcessLookupError, ValueError, OSError):
            pass
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


def is_port_in_use(port):
    """ポートが使用中かチェック"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0
SEARCH_DIRS = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
]

# File type icons mapping
FILE_ICONS = {
    '.pdf': '📄', '.doc': '📝', '.docx': '📝', '.txt': '📝', '.md': '📝',
    '.xls': '📊', '.xlsx': '📊', '.csv': '📊', '.numbers': '📊',
    '.ppt': '📊', '.pptx': '📊', '.key': '📊',
    '.pages': '📝', '.odt': '📝', '.rtf': '📝',
    '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️',
    '.webp': '🖼️', '.svg': '🖼️', '.heic': '🖼️', '.bmp': '🖼️',
    '.mp4': '🎬', '.mov': '🎬', '.avi': '🎬', '.mkv': '🎬', '.webm': '🎬',
    '.mp3': '🎵', '.wav': '🎵', '.m4a': '🎵', '.flac': '🎵',
    '.zip': '📦', '.tar': '📦', '.gz': '📦', '.7z': '📦', '.rar': '📦',
    '.dmg': '💿', '.pkg': '💿', '.iso': '💿',
    '.py': '💻', '.js': '💻', '.ts': '💻', '.html': '💻', '.css': '💻',
    '.java': '💻', '.kt': '💻', '.swift': '💻',
    '.json': '⚙️', '.yaml': '⚙️', '.yml': '⚙️', '.toml': '⚙️',
}


def format_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def get_file_icon(ext: str) -> str:
    return FILE_ICONS.get(ext.lower(), '📁')


def build_index() -> list[dict]:
    """Build file index from search directories."""
    index = []
    ignore = {'.git', 'node_modules', 'venv', '.venv', '__pycache__', '.Trash'}

    for search_dir in SEARCH_DIRS:
        if not search_dir.exists():
            continue
        for root, dirs, files in os.walk(search_dir):
            # Skip ignored directories
            dirs[:] = [d for d in dirs if d not in ignore and not d.startswith('.')]

            for name in files:
                if name.startswith('.'):
                    continue
                filepath = Path(root) / name
                try:
                    stat = filepath.stat()
                    ext = filepath.suffix.lower()
                    index.append({
                        'name': name,
                        'path': str(filepath),
                        'dir': str(filepath.parent),
                        'ext': ext,
                        'size': stat.st_size,
                        'size_str': format_size(stat.st_size),
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        'modified_str': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                        'icon': get_file_icon(ext),
                        'location': str(filepath.parent).replace(str(Path.home()), '~'),
                    })
                except (OSError, PermissionError):
                    pass

    return index


class FileFinderHandler(SimpleHTTPRequestHandler):
    file_index = []

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == '/api/search':
            self.handle_search(params)
        elif path == '/api/open':
            self.handle_open(params)
        elif path == '/api/refresh':
            self.handle_refresh()
        elif path == '/api/stats':
            self.handle_stats()
        elif path == '/' or path == '/index.html':
            self.serve_index()
        else:
            self.send_error(404)

    def handle_search(self, params):
        query = params.get('q', [''])[0].lower()
        ext_filter = params.get('ext', [''])[0].lower()
        after = params.get('after', [''])[0]
        before = params.get('before', [''])[0]
        min_size = params.get('min_size', [''])[0]
        max_size = params.get('max_size', [''])[0]
        sort = params.get('sort', ['relevance'])[0]

        results = self.file_index

        # Filter by query
        if query:
            query_terms = query.split()
            filtered = []
            for f in results:
                name_lower = f['name'].lower()
                path_lower = f['path'].lower()
                if all(term in name_lower or term in path_lower for term in query_terms):
                    filtered.append(f)
            results = filtered

        # Filter by extension
        if ext_filter:
            exts = [e.strip() if e.strip().startswith('.') else f'.{e.strip()}'
                    for e in ext_filter.split(',')]
            results = [f for f in results if f['ext'] in exts]

        # Filter by date
        if after:
            results = [f for f in results if f['modified'] >= after]
        if before:
            results = [f for f in results if f['modified'] <= before]

        # Filter by size
        if min_size:
            try:
                min_bytes = int(min_size) * 1024  # KB
                results = [f for f in results if f['size'] >= min_bytes]
            except ValueError:
                pass
        if max_size:
            try:
                max_bytes = int(max_size) * 1024  # KB
                results = [f for f in results if f['size'] <= max_bytes]
            except ValueError:
                pass

        # Sort
        if sort == 'name':
            results.sort(key=lambda f: f['name'].lower())
        elif sort == 'date':
            results.sort(key=lambda f: f['modified'], reverse=True)
        elif sort == 'size':
            results.sort(key=lambda f: f['size'], reverse=True)
        else:
            # Relevance: prioritize name matches over path matches
            if query:
                def relevance_score(f):
                    name_lower = f['name'].lower()
                    score = 0
                    for term in query.split():
                        if term in name_lower:
                            score += 10
                            if name_lower.startswith(term):
                                score += 5
                    return -score
                results.sort(key=relevance_score)

        # Limit results
        total = len(results)
        results = results[:100]

        self.send_json({'results': results, 'total': total, 'showing': len(results)})

    def handle_open(self, params):
        filepath = params.get('path', [''])[0]
        if filepath and os.path.exists(filepath):
            # -R flag reveals the file in Finder
            subprocess.Popen(['open', '-R', filepath])
            self.send_json({'status': 'ok', 'message': f'Opened in Finder: {filepath}'})
        else:
            self.send_json({'status': 'error', 'message': 'File not found'}, status=404)

    def handle_refresh(self):
        FileFinderHandler.file_index = build_index()
        count = len(FileFinderHandler.file_index)
        self.send_json({'status': 'ok', 'count': count, 'message': f'Index refreshed: {count} files'})

    def handle_stats(self):
        index = self.file_index
        total = len(index)
        total_size = sum(f['size'] for f in index)

        # Count by extension
        ext_counts = {}
        for f in index:
            ext = f['ext'] if f['ext'] else '(なし)'
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

        # Top 10 extensions
        top_exts = sorted(ext_counts.items(), key=lambda x: -x[1])[:10]

        # Count by location
        loc_counts = {}
        for f in index:
            parts = Path(f['path']).parts
            if len(parts) >= 4:
                loc = parts[3]  # Desktop, Documents, Downloads
            else:
                loc = 'other'
            loc_counts[loc] = loc_counts.get(loc, 0) + 1

        self.send_json({
            'total_files': total,
            'total_size': format_size(total_size),
            'by_extension': top_exts,
            'by_location': loc_counts,
        })

    def serve_index(self):
        html_path = Path(__file__).parent / 'index.html'
        if html_path.exists():
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            with open(html_path, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, 'index.html not found')

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def log_message(self, format, *args):
        # Suppress access logs for cleaner output
        pass


def main():
    print(f"🔍 File Finder - ファイル検索サーバー")

    # 既存のサーバーがあれば停止
    if is_port_in_use(PORT):
        print(f"   ⚠️  ポート {PORT} が使用中です。既存サーバーの停止を試みます...")
        kill_existing_server()
        import time
        time.sleep(0.5)
        if is_port_in_use(PORT):
            # PIDファイルにない別プロセスがポートを使用中
            print(f"   ❌ ポート {PORT} を解放できませんでした。")
            print(f"      以下のコマンドで手動停止してください:")
            print(f"      lsof -ti :{PORT} | xargs kill")
            sys.exit(1)

    print(f"   Building index...")
    FileFinderHandler.file_index = build_index()
    print(f"   ✅ {len(FileFinderHandler.file_index)} files indexed")
    print(f"   🌐 http://localhost:{PORT}")
    print(f"   Press Ctrl+C to stop\n")

    server = HTTPServer(('localhost', PORT), FileFinderHandler)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # PIDファイルを保存
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        server.shutdown()
    finally:
        # PIDファイルを削除
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


if __name__ == '__main__':
    main()
