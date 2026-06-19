# Memory Loom

Memory Loom 是一个本地数字足迹记忆编织工具。当前仓库包含两部分骨架：

- `src/MemoryLoomApp`: .NET 8 WPF 前端和系统采集端。
- `backend`: FastAPI 后端，负责数据接收、SQLite 缓冲、后续 LanceDB 向量检索。

## Python 后端开发

进入后端目录并创建虚拟环境：

```powershell
cd E:\MemoryLoom\backend
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

启动开发服务：

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8765 --reload
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

写入一条测试记忆：

```powershell
Invoke-RestMethod `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"source":"manual","content":"Memory Loom first note","metadata":{"kind":"smoke-test"}}' `
  http://127.0.0.1:8765/ingest
```

搜索测试：

```powershell
Invoke-RestMethod `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"query":"Memory Loom","top_k":5}' `
  http://127.0.0.1:8765/search
```

默认 SQLite 缓冲库会写入 `backend/database/buffer.sqlite3`。如果需要使用纯内存库，可以设置：

```powershell
$env:MEMORYLOOM_SQLITE_PATH = ":memory:"
```

## 打包 backend.exe

WPF 启动时会尝试静默拉起 `backend.exe`。开发阶段可以先手动运行 `uvicorn`，也可以用 PyInstaller 生成可执行文件：

```powershell
cd E:\MemoryLoom\backend
.\.venv\Scripts\Activate.ps1
python -m pip install pyinstaller
pyinstaller --onefile --name backend main.py
```

打包产物位于 `backend/dist/backend.exe`。WPF 项目会在构建时自动把这个文件复制到输出目录。

如需指定其他后端可执行文件路径：

```powershell
$env:MEMORYLOOM_BACKEND_PATH = "E:\MemoryLoom\backend\dist\backend.exe"
```

## C# WPF 开发

确认安装 .NET 8 SDK：

```powershell
dotnet --version
```

还原并运行 WPF 项目：

```powershell
cd E:\MemoryLoom
dotnet restore .\MemoryLoom.sln
dotnet run --project .\src\MemoryLoomApp\MemoryLoomApp.csproj
```

如果 `backend.exe` 不存在，WPF 会继续启动搜索窗口，并在调试输出中记录后端未找到。此时可以手动运行 FastAPI 开发服务。

## 当前接口

- `GET /health`: 后端健康检查。
- `POST /ingest`: 写入采集事件到 SQLite 缓冲表。
- `POST /search`: 当前先做 SQLite 关键字检索，后续替换为 BGE + LanceDB 混合检索。

## 下一步建议

1. 在 `Services` 中接入真实 WinEventHook、剪贴板监听、UI Automation 和全局快捷键。
2. 在后端实现 BAAI/bge-small-zh-v1.5 本地模型加载、批量向量化和 LanceDB schema。
3. 增加 C# 到 `/ingest` 的采集事件上报客户端，并加入失败重试队列。
