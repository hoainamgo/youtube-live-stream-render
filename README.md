# 🔴 YOUTUBE LIVE STREAM TRÊN RENDER.COM (TỰ ĐỘNG KÉO TỪ GOOGLE DRIVE)

Dự án phát Live Stream YouTube tự động 24/7 chạy trên nền tảng Cloud [Render.com](https://dashboard.render.com/) bằng Docker, FFmpeg và Python Web Dashboard.

---

## 🧰 1. TÀI NGUYÊN CẦN CHUẨN BỊ

1. **Tài khoản Render**: Đăng ký tại [dashboard.render.com](https://dashboard.render.com/) (liên kết với GitHub/GitLab).
2. **Kho mã nguồn (GitHub Repo)**: Tạo 1 repository GitHub mới để chứa mã nguồn này.
3. **Mã luồng YouTube (Stream Key)**:
   - Vào [YouTube Studio Live](https://studio.youtube.com/channel/UC/livestreaming).
   - Copy **Khóa phát trực tiếp (Stream Key)**.
4. **Link Google Drive Video**:
   - Upload video lên Google Drive của bạn.
   - Nhấp chuột phải vào file → **Chia sẻ (Share)** → Đổi quyền thành **"Bất kỳ ai có đường liên kết đều có thể xem" (Anyone with the link)**.
   - Copy đường liên kết dạng: `https://drive.google.com/file/d/1A2B3C.../view?usp=sharing` (hoặc chỉ cần ID `1A2B3C...`).

---

## 🚀 2. HƯỚNG DẪN TRIỂN KHAI LÊN RENDER (3 BƯỚC)

### Bước 1: Đẩy mã nguồn lên GitHub
Mở PowerShell tại thư mục `D:\Test_script\render_youtube_live` và chạy:
```powershell
git init
git add .
git commit -m "Init Render YouTube Live Stream with Google Drive Sync"
git branch -M main
git remote add origin https://github.com/<tai-khoan-cua-ban>/<ten-repo>.git
git push -u origin main
```

---

### Bước 2: Tạo Web Service trên Render Dashboard
1. Truy cập [dashboard.render.com](https://dashboard.render.com/).
2. Nhấn nút **New +** ở góc trên bên phải -> Chọn **Web Service**.
3. Chọn kho GitHub bạn vừa tạo ở Bước 1.
4. Cấu hình cơ bản:
   - **Name**: `youtube-live-stream` (hoặc tên tùy thích).
   - **Region**: `Singapore` (độ trễ thấp, kết nối YouTube và Google Drive cực nhanh).
   - **Runtime**: `Docker`.
   - **Instance Type**: `Free` (hoặc `Starter`).
5. Cuộn xuống mục **Environment Variables** -> Thêm các biến sau:
   - `YOUTUBE_STREAM_KEY` = `xxxx-xxxx-xxxx-xxxx-xxxx` (Stream Key từ YouTube Studio).
   - `GDRIVE_URL` = `https://drive.google.com/file/d/1A2B3C.../view?usp=sharing` (Link file video trên Drive).
   - `RTMP_URL` = `rtmp://a.rtmp.youtube.com/live2` (Mặc định).
6. Nhấn **Create Web Service**.

Render sẽ tự động:
1. Build Docker container với FFmpeg & Python.
2. Tự động bypass màn hình xác nhận virus của Google Drive và tải file video về container.
3. Kích hoạt vòng lặp phát livestream qua YouTube RTMP 24/7.

---

### Bước 3: Giữ Stream 24/7 (Đối với Free Plan)
Gói Free của Render sẽ tự động ngủ (sleep) sau 15 phút nếu không có lượt truy cập web. Để giữ luồng live chạy liên tục:
1. Lấy URL của Web Service trên Render (ví dụ: `https://youtube-live-stream.onrender.com`).
2. Vào [UptimeRobot.com](https://uptimerobot.com) (miễn phí).
3. Tạo một Monitor mới:
   - **Monitor Type**: `HTTP(s)`
   - **Friendly Name**: `Render Live Keep-Alive`
   - **URL**: `https://youtube-live-stream.onrender.com/health`
   - **Monitoring Interval**: `5 minutes`
4. Render sẽ luôn được đánh thức và giữ kết nối live stream không bị ngắt.
