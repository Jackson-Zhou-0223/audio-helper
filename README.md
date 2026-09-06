# 语音约碰面地点

同一座城市里，两个人用语音找中间附近的碰面店铺。当前仓库是项目骨架：后端只提供健康检查，前端只提供可打开的基础页面。

## 环境

- 约定为 Python 3.11；本机若只有 3.14，也可使用（依赖已改为带 3.14 预编译包的版本）
- Node.js 22.12 及以上的 22.x
- 后端 `http://localhost:8003`
- 前端 `http://localhost:5175`

真实密钥填写在 `backend/.env`。仓库只保留 `backend/.env.example` 空值模板。没有密钥时，健康检查也应可用。

### 启动后端

在 `backend` 目录、虚拟环境已激活时：

```powershell
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8003
```

不要直接敲 `uvicorn`。Windows 上即使安装成功，该命令也可能不在 PATH 里；用 `python -m uvicorn` 或 `python main.py`。

## 模拟测试

本轮不调用百炼、DeepSeek、高德。可在 `backend` 目录运行：

```powershell
python -m pytest
```

当前 Mock 覆盖 `GET /health` 和 `POST /upload` 的成功/失败分支，不调用真实 ffprobe。Mock 通过不能证明真实录音校验、ASR、搜店或语音播报已跑通。

`POST /upload` 用本机 `ffprobe` 探测真实容器、编码和时长（只探测，不转码）。Windows 可用 `winget install Gyan.FFmpeg`。后端会在 PATH、WinGet 安装目录和 `FFPROBE_PATH` 中查找，不要求当前终端一定能直接运行 `ffprobe`。缺少 Duration 标签的浏览器 WebM 不会因此直接判为非法，会再看音频流时长或数据包时间戳。

## 真实接口验收

配置密钥后的 ASR、DeepSeek、高德、TTS 与前端全链路验收，等对应接口开发完成后再做。本轮只验收健康检查和页面打开。
