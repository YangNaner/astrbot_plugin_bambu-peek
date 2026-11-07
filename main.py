"""拓竹（Bambu Lab）打印机插件 —— 查看状态 / 拍照 / 打印控制。

指令：
  /打印状态        查看打印机当前状态
  /打印机拍照      拍一张摄像头照片发到聊天里
  /看看打印机      状态 + 照片一起发
  /暂停打印        暂停当前打印
  /继续打印        恢复打印
  /取消打印        停止当前打印
  /打印帮助        显示帮助
"""

import asyncio
import sys
import time
from pathlib import Path

# 兼容以包目录方式加载的情况：确保插件目录在 sys.path 中
_PLUGIN_DIR = str(Path(__file__).resolve().parent)
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

# 插件名 = 安装目录名（AstrBot 安装时按 metadata.yaml 的 name 创建目录）
PLUGIN_NAME = Path(__file__).resolve().parent.name

import astrbot.api.message_components as Comp  # noqa: E402
from astrbot.api import AstrBotConfig, logger  # noqa: E402
from astrbot.api.event import AstrMessageEvent, filter  # noqa: E402
from astrbot.api.star import Context, Star, StarTools  # noqa: E402
from bambu.camera import CameraError, capture_camera  # noqa: E402
from bambu.core import BambuService, PrinterError  # noqa: E402
from bambu.format import format_status  # noqa: E402

HELP_TEXT = """🖨️ 拓竹打印机指令
/打印状态 —— 查看当前打印状态
/打印机拍照 —— 拍一张照片
/看看打印机 —— 状态 + 照片
/暂停打印 —— 暂停当前打印
/继续打印 —— 恢复打印
/取消打印 —— 停止当前打印
/打印帮助 —— 显示本帮助"""


class BambuPrinterPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.service = BambuService(
            ip=self._conf("ip", "192.168.1.14"),
            access_code=self._conf("access_code", ""),
            serial=self._conf("serial", ""),
            mqtt_port=self._conf("mqtt_port", 8883),
            connect_timeout=self._conf("timeout", 20),
            logger=logger,
        )
        self.service.start()
        logger.info(f"[bambu] 插件已启动，尝试连接打印机 {self.service.ip}")

    # ------------------------------------------------------------------ 工具
    def _conf(self, key, default=None):
        value = self.config.get(key, default) if self.config else default
        if value in (None, ""):
            return default
        return value

    def _data_dir(self) -> Path:
        """返回插件持久化目录，遵循 AstrBot 标准路径 data/plugin_data/<插件名>。

        上架规范要求插件数据保存在 data/plugin_data/{plugin_name} 下
        （见 StarTools.get_data_dir），这样备份、迁移和卸载清理时能被正确识别。
        插件名取安装目录名，安装时 AstrBot 会用 metadata.yaml 的 name 命名目录。
        """
        try:
            return StarTools.get_data_dir(PLUGIN_NAME)
        except Exception as e:
            logger.warning(f"[bambu] StarTools 获取数据目录失败，改用兜底路径: {e}")

        for parent in Path(__file__).resolve().parent.parents:
            if parent.name == "data":
                d = parent / "plugin_data" / PLUGIN_NAME
                break
        else:
            d = Path.cwd() / "data" / "plugin_data" / PLUGIN_NAME
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def _get_report(self, timeout=None):
        """阻塞等待一帧状态，放到线程里执行以免卡住事件循环。"""
        if timeout is None:
            return await asyncio.to_thread(self.service.get_report)
        return await asyncio.to_thread(self.service.get_report, timeout)

    async def _take_photo(self) -> Path:
        path = self._data_dir() / f"camera_{int(time.time())}.jpg"
        return await asyncio.to_thread(
            capture_camera,
            self.service.ip,
            self.service.access_code,
            str(path),
            int(self._conf("camera_port", 322)),
            int(self._conf("camera_timeout", 20)),
            logger,
        )

    def _camera_enabled(self) -> bool:
        return bool(self._conf("camera_enabled", True))

    async def _yield_text_and_photo(self, event, texts, photo_path=None):
        """输出文本 + 可选图片；图片组件不可用时退回 image_result。"""
        chain = [Comp.Plain(t) for t in texts if t]
        if photo_path is not None:
            try:
                chain.append(Comp.Image.fromFileSystem(str(photo_path)))
                yield event.chain_result(chain)
                return
            except Exception as e:
                logger.warning(f"[bambu] 图片消息链构造失败，改用 image_result: {e}")
        for t in chain:
            yield event.plain_result(t)
        if photo_path is not None:
            yield event.image_result(str(photo_path))

    # ------------------------------------------------------------------ 指令
    @filter.command("打印状态")
    async def cmd_status(self, event: AstrMessageEvent):
        """查看打印机的当前状态"""
        try:
            report = await self._get_report()
        except PrinterError as e:
            yield event.plain_result(f"❌ {e}")
            return

        text = format_status(report, self.service.serial)
        photo_path = None
        if self._camera_enabled() and self._conf("photo_with_status", False):
            try:
                photo_path = await self._take_photo()
            except CameraError as e:
                text += f"\n📷 拍照失败：{e}"
        async for res in self._yield_text_and_photo(event, [text], photo_path):
            yield res

    @filter.command("打印机拍照")
    async def cmd_photo(self, event: AstrMessageEvent):
        """拍一张打印机摄像头的照片"""
        if not self._camera_enabled():
            yield event.plain_result("❌ 摄像头功能已在插件配置中关闭")
            return
        try:
            path = await self._take_photo()
        except CameraError as e:
            yield event.plain_result(f"❌ 拍照失败：{e}")
            return

        caption = "📷 拓竹打印机实时画面"
        try:
            report = await self._get_report(timeout=5)
            detail = format_status(report, self.service.serial).split("\n", 1)[-1]
            caption += "\n" + detail
        except PrinterError:
            pass

        async for res in self._yield_text_and_photo(event, [caption], path):
            yield res

    @filter.command("看看打印机")
    async def cmd_status_photo(self, event: AstrMessageEvent):
        """同时发送状态和照片"""
        try:
            report = await self._get_report()
        except PrinterError as e:
            yield event.plain_result(f"❌ {e}")
            return

        text = format_status(report, self.service.serial)
        photo_path = None
        if self._camera_enabled():
            try:
                photo_path = await self._take_photo()
            except CameraError as e:
                text += f"\n📷 拍照失败：{e}"
        async for res in self._yield_text_and_photo(event, [text], photo_path):
            yield res

    @filter.command("暂停打印")
    async def cmd_pause(self, event: AstrMessageEvent):
        """暂停当前打印任务"""
        async for res in self._control(event, "pause", "已发送暂停指令"):
            yield res

    @filter.command("继续打印")
    async def cmd_resume(self, event: AstrMessageEvent):
        """恢复被暂停的打印任务"""
        async for res in self._control(event, "resume", "已发送继续指令"):
            yield res

    @filter.command("取消打印")
    async def cmd_stop(self, event: AstrMessageEvent):
        """停止当前打印任务"""
        async for res in self._control(event, "stop", "已发送停止指令"):
            yield res

    @filter.command("打印帮助")
    async def cmd_help(self, event: AstrMessageEvent):
        """显示插件帮助"""
        yield event.plain_result(HELP_TEXT)

    async def _control(self, event, command, ok_text):
        try:
            await asyncio.to_thread(self.service.send_command, command)
        except PrinterError as e:
            yield event.plain_result(f"❌ {e}")
            return
        yield event.plain_result(f"✅ {ok_text}")

    # ------------------------------------------------------------------ 生命周期
    async def terminate(self):
        self.service.stop()
        logger.info("[bambu] 插件已卸载，连接已关闭")
