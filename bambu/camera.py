"""拓竹打印机摄像头取流。

RTSP(S) 地址：rtsps://bblp:{访问码}@{ip}:{port}/streaming/live/1
优先使用 OpenCV（FFMPEG 后端），没有 OpenCV 时退回到系统 ffmpeg 命令行。
"""

import os
import shutil
import subprocess
import tempfile
import time


class CameraError(Exception):
    """摄像头取流失败。"""


def camera_url(ip, access_code, port=322):
    return f"rtsps://bblp:{access_code}@{ip}:{port}/streaming/live/1"


def capture_camera(ip, access_code, out_path, port=322, timeout=20, logger=None):
    """抓取一帧摄像头画面并保存到 out_path，返回 out_path。失败抛 CameraError。"""
    url = camera_url(ip, access_code, port)

    # 让 OpenCV/FFmpeg 走 TCP，避免 UDP 丢包导致取不到帧
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                          "rtsp_transport;tcp|stimeout;8000000")

    try:
        import cv2
    except ImportError:
        cv2 = None

    if cv2 is not None:
        try:
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            if cap.isOpened():
                deadline = time.time() + timeout
                frame = None
                while time.time() < deadline:
                    ok, img = cap.read()
                    if ok and img is not None:
                        frame = img
                        break
                    time.sleep(0.2)
                cap.release()
                if frame is not None:
                    if not cv2.imwrite(out_path, frame):
                        raise CameraError(f"图片写入失败: {out_path}")
                    return out_path
            else:
                cap.release()
        except Exception as e:
            if logger:
                logger.warning(f"[bambu] OpenCV 取流失败，尝试 ffmpeg: {e}")
            # 继续尝试 ffmpeg

    # 退路：系统 ffmpeg
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            cmd = [ffmpeg, "-y", "-rtsp_transport", "tcp", "-i", url,
                   "-frames:v", "1", "-q:v", "3", tmp_path]
            res = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
            if res.returncode == 0 and os.path.exists(tmp_path) \
                    and os.path.getsize(tmp_path) > 0:
                shutil.move(tmp_path, out_path)
                return out_path
            err = res.stderr[-300:].decode("utf-8", "replace")
            raise CameraError(f"ffmpeg 取流失败: {err}")
        except subprocess.TimeoutExpired:
            raise CameraError("摄像头取流超时")
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    raise CameraError(
        "无法访问摄像头：缺少 OpenCV 且系统没有 ffmpeg。"
        "请执行 pip install opencv-python-headless 或安装 ffmpeg"
    )
