import os
import re
import sys
import time
import glob
import signal
import threading
import subprocess
import collections
import datetime
import psutil
import requests
import gdown
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

# Cấu hình từ Biến Môi Trường (Environment Variables)
YOUTUBE_STREAM_KEY = os.environ.get("YOUTUBE_STREAM_KEY", "").strip()
RTMP_URL = os.environ.get("RTMP_URL", "rtmp://a.rtmp.youtube.com/live2").strip()
GDRIVE_URL = os.environ.get("GDRIVE_URL", "https://drive.google.com/drive/folders/1p0M5INgrKabaVUAqzK24yGC8X0fzhDKg").strip()
VIDEO_URL = os.environ.get("VIDEO_URL", "").strip()
LOCAL_VIDEO_PATH = os.environ.get("LOCAL_VIDEO_PATH", "video.mp4").strip()
PLAYLIST_PATH = "playlist.txt"
MEDIA_DIR = "media_files"
PORT = int(os.environ.get("PORT", 10000))

# Trạng thái luồng phát
stream_state = {
    "status": "INIT",  # INIT, DOWNLOADING, STREAMING, ERROR, STOPPED, WAITING_FOR_KEY
    "started_at": None,
    "reconnect_count": 0,
    "last_error": None,
    "video_source": None,
    "track_count": 0,
    "is_running": False
}

log_buffer = collections.deque(maxlen=100)
stream_process = None
worker_thread = None
stop_event = threading.Event()

def log(msg: str):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted, flush=True)
    log_buffer.append(formatted)

def extract_gdrive_id(url_or_id: str) -> tuple[str, bool]:
    """Trích xuất file/folder ID từ link Google Drive bất kỳ và xác định là folder hay file."""
    if not url_or_id:
        return "", False
    
    # Kiểm tra xem có phải là thư mục (folder) không
    if "folders/" in url_or_id:
        match = re.search(r'folders/([a-zA-Z0-9_-]+)', url_or_id)
        if match:
            return match.group(1), True

    if re.match(r'^[a-zA-Z0-9_-]{20,}$', url_or_id):
        return url_or_id, False
    
    patterns = [
        r'/file/d/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'/d/([a-zA-Z0-9_-]+)',
        r'open\?id=([a-zA-Z0-9_-]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1), False
    return url_or_id, False

def prepare_media():
    """Chuẩn bị nguồn video/playlist từ Google Drive (File đơn hoặc Cả Album Thư mục)."""
    os.makedirs(MEDIA_DIR, exist_ok=True)
    
    # 1. Nếu đã có sẵn video cục bộ
    if os.path.exists(LOCAL_VIDEO_PATH) and os.path.getsize(LOCAL_VIDEO_PATH) > 0:
        log(f"✅ Đã có file video cục bộ: {LOCAL_VIDEO_PATH}")
        stream_state["track_count"] = 1
        return "single", LOCAL_VIDEO_PATH

    source_url = GDRIVE_URL or VIDEO_URL
    if not source_url:
        log("⚠️ Không tìm thấy nguồn video (GDRIVE_URL hoặc VIDEO_URL).")
        return None, None

    stream_state["status"] = "DOWNLOADING"

    # 2. Xử lý Google Drive
    if GDRIVE_URL or "drive.google.com" in source_url:
        gdrive_id, is_folder = extract_gdrive_id(source_url)
        
        if is_folder:
            log(f"📁 Phát hiện Link Thư Mục Album Google Drive (Folder ID: {gdrive_id}). Đang tải toàn bộ MVs...")
            try:
                gdown.download_folder(id=gdrive_id, output=MEDIA_DIR, quiet=False, use_cookies=False)
                # Quét tất cả file mp4 trong thư mục (bao gồm cả subfolders)
                video_files = sorted(glob.glob(f"{MEDIA_DIR}/**/*.mp4", recursive=True))
                if not video_files:
                    video_files = sorted(glob.glob(f"{MEDIA_DIR}/*.mp4"))
                
                if video_files:
                    log(f"✅ Đã tải thành công {len(video_files)} MV từ Album Google Drive:")
                    with open(PLAYLIST_PATH, "w", encoding="utf-8") as f:
                        for idx, vf in enumerate(video_files, 1):
                            abs_path = os.path.abspath(vf).replace("\\", "/")
                            f.write(f"file '{abs_path}'\n")
                            log(f"   [{idx:02d}] {os.path.basename(vf)}")
                    
                    stream_state["track_count"] = len(video_files)
                    return "playlist", PLAYLIST_PATH
                else:
                    raise Exception("Không tìm thấy file .mp4 nào trong thư mục Google Drive tải về.")
            except Exception as e:
                err = f"Lỗi tải Album Folder từ Google Drive: {str(e)}"
                log(f"❌ {err}")
                stream_state["last_error"] = err
                stream_state["status"] = "ERROR"
                return None, None
        else:
            # File đơn
            log(f"📥 Đang tải Video đơn từ Google Drive (File ID: {gdrive_id})...")
            try:
                output_file = gdown.download(id=gdrive_id, output=LOCAL_VIDEO_PATH, quiet=False, fuzzy=True)
                if output_file and os.path.exists(LOCAL_VIDEO_PATH) and os.path.getsize(LOCAL_VIDEO_PATH) > 0:
                    size_mb = os.path.getsize(LOCAL_VIDEO_PATH) / (1024 * 1024)
                    log(f"✅ Tải thành công từ Google Drive: {LOCAL_VIDEO_PATH} ({size_mb:.2f} MB)")
                    stream_state["track_count"] = 1
                    return "single", LOCAL_VIDEO_PATH
                else:
                    raise Exception("File tải về rỗng hoặc chưa mở quyền chia sẻ công khai.")
            except Exception as e:
                err = f"Lỗi tải video đơn từ Drive: {str(e)}"
                log(f"❌ {err}")
                stream_state["last_error"] = err
                stream_state["status"] = "ERROR"
                return None, None

    # 3. Direct HTTP Link
    log(f"📥 Đang tải từ Direct URL: {source_url}...")
    try:
        response = requests.get(source_url, stream=True, timeout=30)
        response.raise_for_status()
        with open(LOCAL_VIDEO_PATH, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        log(f"✅ Tải thành công: {LOCAL_VIDEO_PATH}")
        stream_state["track_count"] = 1
        return "single", LOCAL_VIDEO_PATH
    except Exception as e:
        err = f"Lỗi tải từ direct URL: {str(e)}"
        log(f"❌ {err}")
        stream_state["last_error"] = err
        stream_state["status"] = "ERROR"
        return None, None

def run_ffmpeg_stream():
    """Vòng lặp phát livestream qua ffmpeg chuẩn livestream-ops-master."""
    global stream_process
    
    mode, media_target = prepare_media()
    if not media_target:
        log("❌ Không thể chuẩn bị nguồn phát livestream. Hãy kiểm tra lại link Google Drive.")
        stream_state["status"] = "ERROR"
        return

    stream_state["video_source"] = media_target

    if not YOUTUBE_STREAM_KEY or "PASTE_YOUR_STREAM_KEY" in YOUTUBE_STREAM_KEY:
        log("⚠️ CHƯA CẤU HÌNH YOUTUBE_STREAM_KEY! Hãy thêm biến môi trường YOUTUBE_STREAM_KEY trong mục Environment của Render.")
        stream_state["status"] = "WAITING_FOR_KEY"
        return

    rtmp_destination = f"{RTMP_URL}/{YOUTUBE_STREAM_KEY}"
    
    # Chuẩn bị lệnh ffmpeg theo chế độ (Playlist nhiều MV hoặc 1 Video)
    if mode == "playlist":
        cmd = [
            "ffmpeg",
            "-re",
            "-stream_loop", "-1",
            "-f", "concat",
            "-safe", "0",
            "-i", media_target,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "48000",
            "-f", "flv",
            rtmp_destination
        ]
    else:
        cmd = [
            "ffmpeg",
            "-re",
            "-stream_loop", "-1",
            "-i", media_target,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "48000",
            "-f", "flv",
            rtmp_destination
        ]

    log(f"🚀 Bắt đầu phát Live Stream YouTube ({stream_state['track_count']} Tracks / Loop)...")
    stream_state["is_running"] = True
    stream_state["started_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    while not stop_event.is_set():
        try:
            stream_state["status"] = "STREAMING"
            masked_key = YOUTUBE_STREAM_KEY[-4:] if len(YOUTUBE_STREAM_KEY) > 4 else '****'
            log(f"📡 Đang phát luồng tới YouTube RTMP (Stream Key: ***{masked_key})")
            
            stream_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            for line in iter(stream_process.stdout.readline, ''):
                line_str = line.strip()
                if line_str:
                    if "frame=" in line_str or "fps=" in line_str or "bitrate=" in line_str:
                        if int(time.time()) % 15 == 0:
                            log(f"📊 {line_str}")
                    elif "error" in line_str.lower() or "warning" in line_str.lower():
                        log(f"⚠️ {line_str}")
                if stop_event.is_set():
                    break

            stream_process.stdout.close()
            ret = stream_process.wait()
            
            if stop_event.is_set():
                log("⏹️ Đã nhận tín hiệu dừng phát luồng.")
                break

            stream_state["reconnect_count"] += 1
            log(f"⚠️ Luồng bị ngắt (Exit code: {ret}). Tự động kết nối lại sau 15 giây (Lần reconnect: {stream_state['reconnect_count']})...")
            stream_state["status"] = "RECONNECTING"
            time.sleep(15)

        except Exception as e:
            err = f"Lỗi tiến trình ffmpeg: {str(e)}"
            log(f"❌ {err}")
            stream_state["last_error"] = err
            stream_state["status"] = "ERROR"
            time.sleep(15)

    stream_state["status"] = "STOPPED"
    stream_state["is_running"] = False
    log("🏁 Tiến trình Live Stream đã kết thúc.")

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "stream_status": stream_state["status"],
        "tracks": stream_state.get("track_count"),
        "uptime": stream_state.get("started_at"),
        "reconnects": stream_state.get("reconnect_count")
    }), 200

@app.route("/api/status")
def api_status():
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=None)
    return jsonify({
        "stream": stream_state,
        "system": {
            "cpu_percent": cpu,
            "memory_used_mb": round(mem.used / (1024 * 1024), 2),
            "memory_total_mb": round(mem.total / (1024 * 1024), 2),
            "memory_percent": mem.percent
        }
    })

@app.route("/api/logs")
def api_logs():
    return jsonify(list(log_buffer))

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Render YouTube Live Stream Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>body { font-family: 'Inter', sans-serif; }</style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen p-4 md:p-8">
    <div class="max-w-4xl mx-auto space-y-6">
        <!-- Header -->
        <div class="flex items-center justify-between border-b border-slate-800 pb-4">
            <div class="flex items-center space-x-3">
                <span class="text-3xl">🔴</span>
                <div>
                    <h1 class="text-2xl font-bold text-white">YouTube Live Stream Ops</h1>
                    <p class="text-xs text-slate-400">Album Đông A Tiêu Dao Lục (Render.com Cloud Sync)</p>
                </div>
            </div>
            <div id="badge-status" class="px-3 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-300">
                ĐANG TẢI...
            </div>
        </div>

        <!-- Metrics Grid -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div class="text-xs text-slate-400">Trạng Thái Luồng</div>
                <div id="val-status" class="text-lg font-bold text-indigo-400 mt-1">--</div>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div class="text-xs text-slate-400">Số Track / MV</div>
                <div id="val-tracks" class="text-lg font-bold text-emerald-400 mt-1">--</div>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div class="text-xs text-slate-400">Số Lần Reconnect</div>
                <div id="val-reconnects" class="text-lg font-bold text-amber-400 mt-1">0</div>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div class="text-xs text-slate-400">RAM / CPU Usage</div>
                <div id="val-sys" class="text-sm font-semibold text-slate-200 mt-1">--</div>
            </div>
        </div>

        <!-- Stream Key Warning -->
        <div id="warning-box" class="hidden bg-amber-950/50 border border-amber-800 rounded-xl p-4 text-amber-200 text-sm">
            ⚠️ <strong>Lưu ý:</strong> Chưa cấu hình <code class="bg-amber-900/60 px-1 py-0.5 rounded text-xs">YOUTUBE_STREAM_KEY</code>. Vui lòng vào Render Dashboard -> Environment để thêm Stream Key.
        </div>

        <!-- Live Log Console -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <div class="flex items-center justify-between px-4 py-3 bg-slate-850 border-b border-slate-800">
                <div class="text-sm font-semibold text-slate-300">📜 Real-time System Logs</div>
                <button onclick="fetchData()" class="text-xs px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded transition">Làm mới</button>
            </div>
            <div id="log-console" class="p-4 bg-black/70 font-mono text-xs text-slate-300 h-80 overflow-y-auto space-y-1">
                <div class="text-slate-500">Đang tải nhật ký...</div>
            </div>
        </div>
    </div>

    <script>
        async function fetchData() {
            try {
                const [resStatus, resLogs] = await Promise.all([
                    fetch('/api/status'),
                    fetch('/api/logs')
                ]);
                const data = await resStatus.json();
                const logs = await resLogs.json();

                const status = data.stream.status;
                const statusEl = document.getElementById('val-status');
                const badgeEl = document.getElementById('badge-status');
                const warnEl = document.getElementById('warning-box');

                statusEl.innerText = status;
                document.getElementById('val-tracks').innerText = `${data.stream.track_count || 0} MV`;
                document.getElementById('val-reconnects').innerText = data.stream.reconnect_count;
                document.getElementById('val-sys').innerText = `${data.system.memory_used_mb}MB (${data.system.memory_percent}%) | CPU ${data.system.cpu_percent}%`;

                if (status === 'STREAMING') {
                    badgeEl.className = 'px-3 py-1 rounded-full text-xs font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800 animate-pulse';
                    badgeEl.innerText = '🔴 LIVE STREAMING';
                    warnEl.classList.add('hidden');
                } else if (status === 'WAITING_FOR_KEY') {
                    badgeEl.className = 'px-3 py-1 rounded-full text-xs font-semibold bg-amber-950 text-amber-300 border border-amber-800';
                    badgeEl.innerText = '⚠️ THIẾU STREAM KEY';
                    warnEl.classList.remove('hidden');
                } else if (status === 'DOWNLOADING') {
                    badgeEl.className = 'px-3 py-1 rounded-full text-xs font-semibold bg-blue-950 text-blue-300 border border-blue-800 animate-pulse';
                    badgeEl.innerText = '📥 ĐANG TẢI ALBUM GOOGLE DRIVE';
                    warnEl.classList.add('hidden');
                } else {
                    badgeEl.className = 'px-3 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-300';
                    badgeEl.innerText = status;
                }

                // Render Logs
                const logBox = document.getElementById('log-console');
                if (logs && logs.length > 0) {
                    logBox.innerHTML = logs.map(l => {
                        let color = 'text-slate-300';
                        if (l.includes('❌') || l.includes('Lỗi')) color = 'text-rose-400';
                        if (l.includes('⚠️')) color = 'text-amber-300';
                        if (l.includes('✅') || l.includes('📡') || l.includes('🚀')) color = 'text-emerald-300';
                        return `<div class="${color}">${l}</div>`;
                    }).join('');
                    logBox.scrollTop = logBox.scrollHeight;
                }
            } catch (err) {
                console.error("Fetch error:", err);
            }
        }

        setInterval(fetchData, 5000);
        fetchData();
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

def start_background_stream():
    global worker_thread
    stop_event.clear()
    worker_thread = threading.Thread(target=run_ffmpeg_stream, daemon=True)
    worker_thread.start()

def handle_exit(signum, frame):
    log("Nhận tín hiệu dừng từ hệ thống. Đang dọn dẹp...")
    stop_event.set()
    if stream_process and stream_process.poll() is None:
        stream_process.terminate()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_exit)
signal.signal(signal.SIGINT, handle_exit)

if __name__ == "__main__":
    start_background_stream()
    log(f"🌐 Khởi động Web Dashboard & Health check trên cổng {PORT}...")
    app.run(host="0.0.0.0", port=PORT, debug=False)
