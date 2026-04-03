# Thesis Drive

本仓库包含：
- `thesis_frontend`：前端（Vue 3 + Vite）
- `cfms_on_websocket-master`：后端（以 Git Submodule 方式引入）

## 1. 环境要求

- Git 2.30+
- Node.js 18+（建议 20 LTS）
- Python 3.13+
- Windows PowerShell（本文命令以 PowerShell 为例）

## 2. 首次拉取与子模块初始化

```powershell
git clone <你的仓库地址>
Set-Location <仓库目录>
git submodule update --init --recursive
```

如果后端子模块有更新，拉取主仓库后执行：

```powershell
git submodule update --init --recursive
```

## 3. 后端环境配置与启动

```powershell
Set-Location .\cfms_on_websocket-master\src

# 首次生成配置文件
if (-not (Test-Path "config.toml")) {
  Copy-Item "config.toml.sample" "config.toml"
}

# 准备运行目录
New-Item -ItemType Directory -Path "content\logs" -Force | Out-Null
New-Item -ItemType Directory -Path "content\ssl" -Force | Out-Null

# 启动后端
python.exe main.py
```

默认监听地址与端口（见 `config.toml`）：
- Host: `localhost`
- Port: `5104`
- 协议：`wss`

## 4. 前端环境配置与启动

```powershell
Set-Location ..\..\thesis_frontend
npm install
npm run dev
```

常用命令：

```powershell
npm run build
npm run preview
```

## 5. 联调说明

- 前端默认连接地址：`wss://localhost:5104`
- 若使用自签名证书，浏览器可能提示证书不受信任，需要先手动信任证书后再连接

## 6. 常见问题

1. 后端目录为空
- 原因：未初始化子模块
- 处理：`git submodule update --init --recursive`

2. 前端连接失败
- 先确认后端是否已启动
- 再确认 `config.toml` 的 host/port 与前端连接地址一致
- 检查证书是否已被系统/浏览器信任
