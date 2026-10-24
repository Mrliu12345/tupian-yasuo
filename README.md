
# 图片批量压缩工具

批量将 JPG / PNG / BMP / GIF / TIFF / WEBP 图片转换为 WebP（或 JPG / PNG），递归处理子目录、保留目录结构、多线程压缩，用于节省网盘 / 磁盘空间。

## 环境要求

```bash
# Python 3.9+
python -m pip install pywebview pillow
```

## 使用方式

### 桌面版（推荐，页面操作）

```bash
# 双击"启动图片压缩工具.bat"，或运行：
python "图片批量压缩工具.py"
```

页面内选择源文件夹 → 设置格式/质量 → 开始压缩，实时显示进度条和命令行日志。

### 命令行版

```bash
# 基本用法：转换到 源文件夹名_compressed
python batch_compress.py D:\资料

# 指定输出文件夹、格式、质量
python batch_compress.py D:\资料 -o D:\资料_webp -f webp -q 80

# 限制最长边 2000px
python batch_compress.py D:\资料 --max-edge 2000

# 先预览统计，不实际转换
python batch_compress.py D:\资料 --dry-run

# 转换成功后删除原图（危险）
python batch_compress.py D:\资料 -o D:\资料_webp --delete-original
```

### 网页版

直接用浏览器打开 `图片批量压缩工具.html`（纯前端，无需 Python，适合少量图片）。

## 命令行参数

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| `src` | 源文件夹路径 | 必填 |
| `-o, --out` | 输出文件夹 | 源文件夹_compressed |
| `-f, --format` | 输出格式：webp / jpg / png | webp |
| `-q, --quality` | 质量 1-100（webp/jpg 有效） | 80 |
| `--max-edge` | 最长边像素限制，0=不缩放 | 0 |
| `--threads` | 并发线程数 | 4 |
| `--force` | 覆盖已存在的输出（默认跳过，断点续跑） | 关 |
| `--dry-run` | 只预览统计，不转换 | 关 |
| `--min-size` | 只处理大于该字节数的文件 | 0 |
| `--no-subdirs` | 不递归子目录 | 关 |
| `--delete-original` | 转换成功后删除原图 | 关 |

## 说明

- 输出保留源文件夹的子目录结构
- 处理中断后重跑自动跳过已完成的文件（断点续跑）
- GIF 动图转为静态图；透明 PNG 转 JPG 会变白底，转 WebP 保留透明
- 删除原图是永久删除，请先确认输出无误再开启
