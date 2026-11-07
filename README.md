# 拓竹打印机插件（astrbot_plugin_bambu_peek）

> 仓库地址：<https://github.com/YangNaner/astrbot_plugin_bambu-peek>
> 插件包名（`metadata.yaml` 的 `name`、安装目录名）是 `astrbot_plugin_bambu_peek`，
> 与仓库名仅差连字符 —— AstrBot 要求插件名是合法 Python 标识符，不能用 `-`。

通过局域网直接访问家里的拓竹（Bambu Lab）打印机，让机器人能**查看打印状态**、**拍照发图**，
以及**暂停 / 继续 / 取消打印**。全程走本地网络，不需要云端、不需要账号。

![logo](logo.png)

## 功能

| 指令 | 作用 |
|---|---|
| `/打印状态` | 输出当前状态：打印状态、进度、层数、任务名、喷嘴/热床温度、AMS 槽位与余量 |
| `/打印机拍照` | 抓取摄像头实时画面并发送，同时附带状态摘要 |
| `/看看打印机` | 状态 + 照片一次性发送 |
| `/暂停打印` | 暂停当前打印任务 |
| `/继续打印` | 恢复被暂停的任务 |
| `/取消打印` | 停止当前打印任务 |
| `/打印帮助` | 显示指令列表 |

## 安装

### 方式一：上传安装包（推荐）

1. 在 AstrBot 管理面板 → **插件** → 右上角 **安装插件（+）** → **从文件安装**
2. 上传 `astrbot_plugin_bambu_peek.zip`
3. 安装完成后在「已安装」列表里确认插件已开启、无报错

### 方式二：手动放置

把整个 `astrbot_plugin_bambu_peek` 文件夹复制到 AstrBot 的 `data/plugins/` 目录下，
然后在面板里点击 **重载插件**。

### 依赖

插件需要两个第三方库（AstrBot 安装时会根据 `requirements.txt` 自动安装）：

```
paho-mqtt>=2.0.0
opencv-python-headless>=4.8.0
```

如果装不上 OpenCV，插件仍可正常查状态，只是拍照不可用；此时系统里装好 `ffmpeg`
也会被自动作为取流后备方案。

## 配置

在 **插件 → 插件 → 齿轮图标（插件配置）** 中填写：

| 配置项 | 说明 | 默认值 |
|---|---|---|
| 打印机 IP 地址 | 打印机在局域网中的 IP | `192.168.1.14` |
| 访问码 (Access Code) | 打印机「设置 → 网络 → 接入局域网模式」里的访问码 | 空（必填） |
| 打印机序列号 | 留空即可，插件会自动发现 | 空 |
| MQTT 端口 | 状态/控制通道 | `8883` |
| 摄像头 RTSPS 端口 | 摄像头通道 | `322` |
| 状态超时时间（秒） | 等待打印机数据的上限 | `20` |
| 摄像头取流超时（秒） | 拍照等待上限 | `20` |
| 启用摄像头拍照 | 关掉后仅能查状态 | `true` |
| 查看状态时附带照片 | 查状态时顺带拍一张 | `false` |

> 运行 AstrBot 的机器必须和打印机在同一局域网，且能访问打印机的 8883 / 322 端口。

## 协议实现要点

本插件的访问方式是对着真机实测出来的，不是照抄文档：

1. **MQTT 必须带凭据**：否则 broker 直接回 `CONNACK 5 (Not authorized)`。
   用户名固定 `bblp`，密码就是访问码。
2. **主题方向**：客户端发 `device/{serial}/request`，打印机推 `device/{serial}/report`
   （约每秒一次全量状态）。broker 会把客户端自己发的消息回显，解析时按 `print` 字段过滤。
3. **序列号自动发现**：订阅通配符 `device/+/report` 即可拿到序列号；
   SSDP(UDP 2021) 和 mDNS 都不应答，不能靠它们发现设备。
4. **摄像头**：`rtsps://bblp:{访问码}@{ip}:322/streaming/live/1`，
   OpenCV 用 FFMPEG 后端 + `rtsp_transport;tcp` 直接取流（实测 1920×1080）。
5. **TLS**：打印机是自签证书，校验需关闭且套件放宽到 `SECLEVEL=1`。

## 文件结构

```
astrbot_plugin_bambu_peek/
├── main.py               # 插件入口与指令处理
├── metadata.yaml         # 插件元数据
├── _conf_schema.json     # 配置项定义
├── requirements.txt      # 依赖
├── logo.png
└── bambu/
    ├── core.py           # MQTT/TLS 常驻连接、状态缓存、指令下发
    ├── camera.py         # RTSPS 取流（OpenCV，ffmpeg 兜底）
    └── format.py         # 状态报文 -> 中文文本
```

## 注意事项

- 「局域网直连打印」还需要把切片文件写进打印机存储，当前固件对该目录只读（`550`），
  所以插件提供的是**状态查看 + 拍照 + 打印控制**，不负责推送新的打印任务。
- 照片保存在 AstrBot 的标准插件数据目录 `data/plugin_data/astrbot_plugin_bambu_peek/`
  （通过 `StarTools.get_data_dir()` 获取，符合插件市场上架规范）。
- 插件在后台线程维持 MQTT 长连接，断线会自动重连；卸载插件时连接会被关闭。
