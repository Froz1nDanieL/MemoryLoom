# Memory Loom

Memory Loom 是一个本地数字足迹记忆编织工具。当前仓库包含：

- `src/MemoryLoomApp`: .NET 8 WPF 前端和系统采集端。
- `backend`: FastAPI 后端，负责事件接收、SQLite 缓冲、BGE 向量化、LanceDB 本地向量检索。

## 后端能力

当前 Python 后端已经不是占位版，数据链路如下：

1. `POST /ingest` 接收 C# 采集端上报的事件。
2. SQLite 写入 `memory_events` 事实表。
3. SQLite FTS5 写入 `memory_events_fts` 全文索引。
4. SQLite 写入 `embedding_jobs` 向量化队列。
5. 后台 APScheduler 定时 claim pending job。
6. `sentence-transformers` 加载 `BAAI/bge-small-zh-v1.5`。
7. 文本切块后写入 LanceDB `memory_chunks` 表。
8. `POST /search` 执行关键词 + 向量混合检索。

## Python 后端开发

进入后端目录并创建虚拟环境：

```powershell
cd E:\MemoryLoom\backend
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果你曾经单独执行过 `python -m pip install -U huggingface_hub`，请重新执行：

```powershell
python -m pip install "huggingface-hub>=0.34,<1.0"
```

`transformers` 当前需要 `huggingface-hub` 保持在 `1.0` 以下，否则 BGE 模型导入会失败，向量搜索会返回空结果。

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
  -Body '{"source":"manual","content":"Memory Loom 正在编织跨时空记忆","app_name":"DevConsole","metadata":{"kind":"smoke-test"}}' `
  http://127.0.0.1:8765/ingest
```

手动触发一次向量化：

```powershell
Invoke-RestMethod `
  -Method Post `
  http://127.0.0.1:8765/admin/embed-now
```

混合搜索：

```powershell
Invoke-RestMethod `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"query":"跨时空记忆","top_k":5,"backend":"hybrid"}' `
  http://127.0.0.1:8765/search
```

也可以只跑关键词搜索，避免首次加载模型：

```powershell
Invoke-RestMethod `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"query":"记忆","top_k":5,"backend":"keyword"}' `
  http://127.0.0.1:8765/search
```

## BGE 模型

默认模型名是：

```text
BAAI/bge-small-zh-v1.5
```

后端优先查找本地目录：

```text
E:\MemoryLoom\backend\models\bge-small-zh-v1.5
```

如果该目录存在，`sentence-transformers` 会从本地加载。若不存在，则会按模型名尝试从 Hugging Face 下载。离线部署时请提前把模型文件放到上述目录，或设置：

```powershell
$env:MEMORYLOOM_LOCAL_MODEL_PATH = "D:\Models\bge-small-zh-v1.5"
```

## 数据目录

默认运行数据位于：

```text
E:\MemoryLoom\backend\database
```

默认文件：

- SQLite: `backend/database/memoryloom.sqlite3`
- LanceDB: `backend/database/lancedb`

可用环境变量覆盖：

```powershell
$env:MEMORYLOOM_DATABASE_DIR = "D:\MemoryLoomData"
$env:MEMORYLOOM_SQLITE_PATH = "D:\MemoryLoomData\memoryloom.sqlite3"
$env:MEMORYLOOM_LANCEDB_URI = "D:\MemoryLoomData\lancedb"
$env:MEMORYLOOM_EMBEDDING_INTERVAL_SECONDS = "30"
```

## 打包 backend.exe

WPF 启动时会尝试静默拉起 `backend.exe`。开发阶段可以先手动运行 `uvicorn`，也可以用 PyInstaller 生成可执行文件：

```powershell
cd E:\MemoryLoom\backend
.\.venv\Scripts\Activate.ps1
python -m pip install pyinstaller
pyinstaller --onefile --name backend main.py
```

打包产物位于：

```text
E:\MemoryLoom\backend\dist\backend.exe
```

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

- `GET /health`: 查看 SQLite、LanceDB、模型和 embedding job 状态。
- `POST /ingest`: 写入一条采集事件，并自动创建向量化任务。
- `POST /search`: 混合检索，支持 `hybrid`、`keyword`、`vector`。
- `POST /admin/embed-now`: 手动执行一次 embedding 批处理，支持 `?retry_failed=true`。

## Python CLI 测试

Windows PowerShell 容易把 UTF-8 JSON 显示成乱码。推荐用仓库里的 Python CLI 测接口：

```powershell
cd E:\MemoryLoom

python backend\tools\memoryloom_client.py health

python backend\tools\memoryloom_client.py ingest `
  --content "今天在浏览器里研究跨时空记忆编织，复制了一段关于 BGE 和 LanceDB 的资料。"

python backend\tools\memoryloom_client.py embed-now

python backend\tools\memoryloom_client.py search `
  --query "我之前研究过什么向量数据库" `
  --backend hybrid `
  --top-k 5
```

## 下一步建议

1. C# 采集端接入 `/ingest`，把剪贴板、窗口、浏览器 URL 和微信 UIA 事件上报到后端。
2. 为敏感应用和隐私字段增加采集黑名单、脱敏和删除接口。
3. 增加 episode/session 聚合，把离散事件编织成时间线片段。
