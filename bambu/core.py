"""拓竹打印机 MQTT/TLS 客户端（局域网）。

协议要点（实测）：
  * broker 需要凭据，否则 CONNACK 5 (Not authorized)：username=bblp, password=访问码
  * 客户端 -> 打印机：device/{serial}/request
  * 打印机 -> 客户端：device/{serial}/report（大约每秒推一次全量状态）
  * 序列号只能通过通配符订阅 device/+/report 发现，SSDP / mDNS 均无响应
"""

import json
import ssl
import threading
import time

try:
    import paho.mqtt.client as mqtt
except ImportError as e:  # pragma: no cover - 依赖缺失时给出清晰提示
    raise ImportError(
        "缺少依赖 paho-mqtt，请在插件目录执行：pip install paho-mqtt"
    ) from e


class PrinterError(Exception):
    """与打印机通信失败。"""


def _tls_context():
    """打印机使用自签证书，且 TLS 套件需要放宽到 SECLEVEL=1。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except Exception:
        pass
    return ctx


class BambuService:
    """后台线程常驻的打印机连接，向调用方提供状态快照与指令下发。"""

    def __init__(self, ip, access_code, serial="", mqtt_port=8883,
                 connect_timeout=20, logger=None):
        self.ip = ip
        self.access_code = access_code
        self.serial = serial
        self.mqtt_port = int(mqtt_port)
        self.connect_timeout = connect_timeout
        self._log = logger

        self._lock = threading.Lock()
        self._client = None
        self._stop = threading.Event()
        self._thread = None
        self._report = {}
        self._report_time = 0.0
        self._last_error = ""
        self._seq = 0

    # ------------------------------------------------------------------ 日志
    def _debug(self, msg):
        if self._log:
            try:
                self._log.info(msg)
            except Exception:
                pass

    # ------------------------------------------------------------------ 生命周期
    def start(self):
        """启动后台连接线程（幂等）。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="bambu-mqtt", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            client = self._client
            self._client = None
        if client is not None:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass

    # ------------------------------------------------------------------ MQTT
    def _make_client(self):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=f"astrbot-bambu-{int(time.time()) % 10**6}")
        client.tls_set_context(_tls_context())
        client.username_pw_set("bblp", self.access_code)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        return client

    def _on_connect(self, client, userdata, flags, reason, props=None):
        self._debug(f"[bambu] MQTT 已连接: {reason}")
        # 先用通配符订阅，用于发现序列号；已知序列号时同时订阅精确主题
        client.subscribe("device/+/report", qos=0)
        if self.serial:
            client.subscribe(f"device/{self.serial}/report", qos=0)
            client.subscribe(f"device/{self.serial}/request", qos=0)

    def _on_disconnect(self, client, userdata, flags, reason, props=None):
        self._debug(f"[bambu] MQTT 断开: {reason}")

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload)
        except Exception:
            return
        topic = msg.topic
        # 主题形如 device/{serial}/report
        parts = topic.strip("/").split("/")
        if len(parts) == 3 and parts[1] != "+":
            serial = parts[1]
            if serial != self.serial:
                with self._lock:
                    self.serial = serial
                self._debug(f"[bambu] 发现序列号: {serial}")
                try:
                    client.subscribe(f"device/{serial}/report", qos=0)
                    client.subscribe(f"device/{serial}/request", qos=0)
                except Exception:
                    pass
        if topic.endswith("/report") and isinstance(data, dict) and "print" in data:
            with self._lock:
                self._report = data
                self._report_time = time.time()

    def _run(self):
        """连接线程主循环：断线自动重连。"""
        backoff = 3
        while not self._stop.is_set():
            try:
                client = self._make_client()
                with self._lock:
                    self._client = client
                client.connect(self.ip, self.mqtt_port, keepalive=60)
                backoff = 3
                # loop_forever 内部自带断线重连
                client.loop_forever(retry_first_connection=True)
            except Exception as e:
                self._last_error = f"{type(e).__name__}: {e}"
                self._debug(f"[bambu] MQTT 连接异常: {self._last_error}")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30)

    # ------------------------------------------------------------------ 对外接口
    @property
    def last_error(self):
        return self._last_error

    @property
    def connected(self):
        with self._lock:
            return self._client is not None

    def get_report(self, timeout=None, max_age=5.0):
        """返回状态报文；必要时等待一帧新数据。

        timeout: 最多等待多少秒拿不到数据就报错（None 表示用 connect_timeout）。
        max_age: 允许返回的旧数据最大年龄（秒），超时则视为无数据。
        """
        deadline = time.time() + (self.connect_timeout if timeout is None else timeout)
        while True:
            with self._lock:
                if self._report and (time.time() - self._report_time) <= max_age:
                    return self._report
            if time.time() >= deadline:
                if self._last_error:
                    raise PrinterError(f"连接打印机失败：{self._last_error}")
                raise PrinterError(
                    f"没有收到打印机状态数据，请检查 IP({self.ip})、访问码和 LAN 模式"
                )
            time.sleep(0.3)

    def send_command(self, command, **payload):
        """下发一条 MQTT 指令（同步，等待 broker 接收）。"""
        with self._lock:
            client = self._client
            serial = self.serial
        if client is None:
            raise PrinterError("尚未连接到打印机")
        if not serial:
            raise PrinterError("尚未获取到打印机序列号")
        self._seq += 1
        msg = {
            "sequence_id": str(self._seq),
            "command": command,
            "version": 1,
            "time": int(time.time()),
            "push_data": {"command": command, **payload},
        }
        client.publish(f"device/{serial}/request", json.dumps(msg), qos=0)
        return msg
