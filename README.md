# 花型搜图

Windows 本地花型图库搜索与 TIFF 转 JPG 工具。图像解码、建库、搜图与转换都在本机完成，原始印花文件不会上传。

免费体验和会员均支持最多 20,000 个花型、整图/局部搜图和批量 TIFF 转 JPG。会员期限、价格、登录和支付服务将在服务端接入阶段确定；当前版本不收集账号信息、不发起支付。

## 当前功能

- 搜索 TIFF、JPG、PNG 图库，生成本地缩略图和特征索引；同名 TIFF/JPG 按一个花型处理。
- 选择整图搜索，或在预览图上框选局部搜索；支持选择局部截图直接搜索。
- 搜索结果显示原文件名和路径，双击可打开原文件。
- 批量将 TIFF 转换为最长边 4,096 像素、质量 90 的 JPG；输出到独立目录，不覆盖已有文件。
- 大图的读取、索引、搜索和转换在后台线程运行。

## 开发运行

需要 Python 3.12 或更高版本。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

在“图库管理”添加目录并等待建库完成。TIFF 与同目录同名 JPG 会作为同一个花型处理。搜图页可选择整图或在预览上框选区域，也可直接选择局部截图。双击结果打开原文件。

转换页选择 TIFF 来源目录和图库之外的 JPG 输出目录。转换默认最长边 4,096 像素、质量 90；已有文件不会覆盖。

## 构建 Windows 应用

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.\build_windows.ps1
```

单文件可执行程序位于 `dist\FlowerSearch.exe`，可单独复制运行。

## 真实样本验证

```powershell
.venv\Scripts\python tools\validate_tiff_pair.py "花型.tif" "花型.jpg"
```

验证脚本会读取实际 TIFF/JPG、建立临时图库、执行框选和旋转局部搜索、转换 JPG，并确认 TIFF 原文件保留。临时验证数据在检查结束后删除。

当前样本是 20,079×3,012、46MB 的 CMYK LZW TIFF。实际验证包括 TIFF/JPG 解码、约 10% 面积的局部框选、旋转后的局部截图、批量转换和转换后 JPG 反查原 TIFF。你提到的 450MB–1GB TIFF 尚无样本可测，速度和内存表现需要用这类文件继续验证；重复纹样或面积更小的框选也需要更多真实花型评估。

## 会员与在线服务状态

免费体验和会员权益上限均为 20,000 个花型，均支持整图搜图、局部搜图和批量转换。会员有效期、价格、短信服务商、微信开放平台和支付商户配置尚未提供，所以登录、会员校验、微信/支付宝支付和在线更新未启用；不会用模拟支付冒充可收款版本。架构见 [系统架构图](docs/system-architecture.md)。
