#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
批量图片压缩工具（命令行版）
================================
递归扫描源文件夹中的图片，批量转换为 WebP / JPG / PNG，
保留子目录结构输出到新文件夹，默认不碰原图。

用法示例：
  python batch_compress.py D:\资料
  python batch_compress.py D:\资料 -o D:\资料_webp
  python batch_compress.py D:\资料 -f webp -q 80 --max-edge 2000
  python batch_compress.py D:\资料 --dry-run          # 先预览统计
  python batch_compress.py D:\资料 -o E:\out --force   # 覆盖已存在的输出

参数说明见 python batch_compress.py -h
"""
import argparse
import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

from PIL import Image, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
FMT_EXT = {"webp": ".webp", "jpg": ".jpg", "png": ".png"}


def fmt_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1048576:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1048576:.2f} MB"


def collect_files(src: Path, args):
    files = []
    it = src.rglob("*") if not args.no_subdirs else src.iterdir()
    for p in it:
        try:
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                if args.min_size and p.stat().st_size < args.min_size:
                    continue
                files.append(p)
        except OSError:
            continue
    return sorted(files)


def convert_one(src: Path, dst: Path, args):
    """返回 (状态, 原大小, 新大小, 错误信息)"""
    try:
        if dst.exists() and not args.force:
            return "skip", 0, 0, None
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            if getattr(im, "is_animated", False):
                im.seek(0)  # GIF 动图只取第一帧转静态图
            if args.format == "jpg":
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGBA")
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.split()[-1])
                    im = bg
                else:
                    im = im.convert("RGB")
            elif im.mode not in ("RGB", "RGBA", "L"):
                im = im.convert("RGB")

            if args.max_edge > 0:
                im.thumbnail((args.max_edge, args.max_edge), Image.LANCZOS)

            dst.parent.mkdir(parents=True, exist_ok=True)
            if args.format == "webp":
                im.save(dst, "WEBP", quality=args.quality, method=6)
            elif args.format == "jpg":
                im.save(dst, "JPEG", quality=args.quality, optimize=True, progressive=True)
            else:
                im.save(dst, "PNG", optimize=True)

        return "ok", src.stat().st_size, dst.stat().st_size, None
    except Exception as e:
        return "fail", 0, 0, f"{e}"[:200]


def main():
    parser = argparse.ArgumentParser(
        description="批量图片压缩工具：递归转换图片为 WebP/JPG/PNG，保留目录结构输出到新文件夹",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python batch_compress.py D:\\资料\n"
            "  python batch_compress.py D:\\资料 -o D:\\资料_webp -f webp -q 80 --max-edge 2000\n"
            "  python batch_compress.py D:\\资料 --dry-run\n"
        ),
    )
    parser.add_argument("src", help="源文件夹路径")
    parser.add_argument("-o", "--out", help="输出文件夹（默认: 源文件夹名_compressed）")
    parser.add_argument("-f", "--format", choices=["webp", "jpg", "png"], default="webp",
                        help="输出格式，默认 webp")
    parser.add_argument("-q", "--quality", type=int, default=80,
                        help="质量 1-100，仅 webp/jpg 有效，默认 80")
    parser.add_argument("--max-edge", type=int, default=0,
                        help="最长边像素限制，0=不缩放，默认 0")
    parser.add_argument("--threads", type=int, default=4, help="并发线程数，默认 4")
    parser.add_argument("--force", action="store_true",
                        help="覆盖已存在的输出文件（默认跳过，方便断点续跑）")
    parser.add_argument("--dry-run", action="store_true", help="只统计预览，不实际转换")
    parser.add_argument("--min-size", type=int, default=0,
                        help="只处理大于该字节数的文件，默认 0=全部")
    parser.add_argument("--no-subdirs", action="store_true", help="不递归子目录，只处理顶层")
    parser.add_argument("--delete-original", action="store_true",
                        help="转换成功后删除原图（危险！确认输出无误后再用）")
    args = parser.parse_args()

    src = Path(args.src)
    if not src.is_dir():
        print(f"[错误] 源文件夹不存在: {src}")
        sys.exit(1)
    out = Path(args.out) if args.out else Path(str(src) + "_compressed")
    if args.dry_run and out == src:
        print("[错误] 请指定 -o 输出文件夹（dry-run 模式）")
        sys.exit(1)
    if out == src:
        print("[错误] 输出文件夹不能等于源文件夹，请用 -o 指定")
        sys.exit(1)

    files = collect_files(src, args)
    if not files:
        print("没有找到可处理的图片。")
        return

    total_orig = sum(f.stat().st_size for f in files)
    print(f"发现 {len(files)} 张图片，总大小 {fmt_size(total_orig)}")
    print(f"输出格式: {args.format}  质量: {args.quality}"
          + (f"  最长边: {args.max_edge}px" if args.max_edge else "")
          + f"  ->  {out}")

    if args.dry_run:
        for f in files:
            rel = f.relative_to(src)
            print(f"  {rel}")
        print(f"[预览] 共 {len(files)} 张，未执行转换。")
        return

    stats = {"ok": 0, "skip": 0, "fail": 0, "orig": 0, "new": 0, "errors": []}
    total = len(files)
    done = 0

    def worker(f):
        rel = f.relative_to(src)
        dst = out / rel.with_suffix(FMT_EXT[args.format])
        return f, convert_one(f, dst, args)

    with ThreadPoolExecutor(max_workers=max(1, args.threads)) as pool:
        futures = [pool.submit(worker, f) for f in files]
        for fut in as_completed(futures):
            f, (status, old, new, err) = fut.result()
            done += 1
            rel = f.relative_to(src)
            if status == "ok":
                stats["ok"] += 1
                stats["orig"] += old
                stats["new"] += new
                print(f"[{done}/{total}] OK   {rel}  {fmt_size(old)} -> {fmt_size(new)}"
                      f"  ({'节省' if old - new >= 0 else '增大'} {fmt_size(abs(old - new))})")
                if args.delete_original:
                    try:
                        f.unlink()
                    except OSError:
                        pass
            elif status == "skip":
                stats["skip"] += 1
                print(f"[{done}/{total}] 跳过 {rel}（输出已存在）")
            else:
                stats["fail"] += 1
                stats["errors"].append((str(rel), err))
                print(f"[{done}/{total}] 失败 {rel}  {err}")

    print("\n========== 汇总 ==========")
    print(f"成功: {stats['ok']} 张   跳过: {stats['skip']} 张   失败: {stats['fail']} 张")
    if stats["ok"]:
        saved = stats["orig"] - stats["new"]
        pct = stats["orig"] and round(saved / stats["orig"] * 100) or 0
        verb = "节省" if saved >= 0 else "增大"
        print(f"原大小: {fmt_size(stats['orig'])}")
        print(f"新大小: {fmt_size(stats['new'])}")
        print(f"{verb}:   {fmt_size(abs(saved))}（{pct}%）")
    if stats["errors"]:
        print("\n失败明细:")
        for rel, err in stats["errors"]:
            print(f"  {rel}: {err}")
    if args.delete_original:
        print("\n[注意] 已开启 --delete-original，转换成功的原图已删除。")


if __name__ == "__main__":
    main()
