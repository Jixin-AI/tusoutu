from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import cv2
import fitz
import numpy as np
import pyvips


SUPPORTED = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".pdf", ".ai"}
RASTER = {".tif", ".tiff", ".jpg", ".jpeg", ".png"}
MAX_FEATURE_SIDE = 1400


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}小时{minutes}分{seconds}秒"
    if minutes:
        return f"{minutes}分{seconds}秒"
    return f"{seconds}秒"


class LibraryDB:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    source_path TEXT PRIMARY KEY,
                    relative_path TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    outputs TEXT NOT NULL,
                    status TEXT NOT NULL,
                    elapsed REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS images (
                    output_path TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    page INTEGER NOT NULL DEFAULT 0,
                    histogram BLOB NOT NULL,
                    points BLOB NOT NULL,
                    descriptors BLOB NOT NULL,
                    feature_count INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS images_source ON images(source_path);
                CREATE INDEX IF NOT EXISTS images_relative ON images(relative_path);
                """
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def image_records(self) -> list[sqlite3.Row]:
        with self.connect() as db:
            return db.execute(
                "SELECT output_path, source_path, relative_path, page, histogram, feature_count FROM images"
            ).fetchall()

    def remove_source(self, source_path: str, delete_files: bool) -> None:
        with self.connect() as db:
            rows = db.execute(
                "SELECT output_path FROM images WHERE source_path=?", (source_path,)
            ).fetchall()
            if delete_files:
                for row in rows:
                    try:
                        Path(row["output_path"]).unlink(missing_ok=True)
                    except OSError:
                        pass
            db.execute("DELETE FROM images WHERE source_path=?", (source_path,))
            db.execute("DELETE FROM sources WHERE source_path=?", (source_path,))

    def save_source(
        self,
        source_path: str,
        relative_path: str,
        size: int,
        mtime_ns: int,
        outputs: list[str],
        status: str,
        elapsed: float,
        message: str,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO sources
                   (source_path, relative_path, size, mtime_ns, outputs, status, elapsed, message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_path) DO UPDATE SET
                     relative_path=excluded.relative_path, size=excluded.size,
                     mtime_ns=excluded.mtime_ns, outputs=excluded.outputs,
                     status=excluded.status, elapsed=excluded.elapsed, message=excluded.message""",
                (
                    source_path,
                    relative_path,
                    size,
                    mtime_ns,
                    json.dumps(outputs, ensure_ascii=False),
                    status,
                    elapsed,
                    message,
                ),
            )

    def save_image(
        self,
        output_path: str,
        source_path: str,
        relative_path: str,
        page: int,
        histogram: bytes,
        points: bytes,
        descriptors: bytes,
        feature_count: int,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT OR REPLACE INTO images
                   (output_path, source_path, relative_path, page, histogram, points,
                    descriptors, feature_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    output_path,
                    source_path,
                    relative_path,
                    page,
                    histogram,
                    points,
                    descriptors,
                    feature_count,
                ),
            )


def _features(image: np.ndarray) -> tuple[bytes, bytes, bytes, int]:
    height, width = image.shape[:2]
    scale = min(1.0, MAX_FEATURE_SIDE / max(width, height))
    if scale < 1:
        image = cv2.resize(image, (round(width * scale), round(height * scale)))
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256])
    cv2.normalize(histogram, histogram, alpha=1, norm_type=cv2.NORM_L1)
    detector = cv2.ORB_create(nfeatures=1200, fastThreshold=8)
    keypoints, descriptors = detector.detectAndCompute(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None)
    if descriptors is None:
        descriptors = np.empty((0, 32), dtype=np.uint8)
    points = np.asarray([point.pt for point in keypoints], dtype=np.float32).reshape(-1, 2)
    return histogram.astype(np.float32).tobytes(), points.tobytes(), descriptors.tobytes(), len(keypoints)


def _decode_file(path: Path) -> np.ndarray:
    image = pyvips.Image.new_from_file(str(path), access="sequential")
    scale = min(1.0, MAX_FEATURE_SIDE / max(image.width, image.height))
    if scale < 1:
        image = image.resize(scale)
    if image.interpretation == pyvips.Interpretation.CMYK:
        image = image.colourspace("srgb")
    if image.bands == 4:
        image = image.extract_band(0, n=3)
    elif image.bands == 1:
        image = image.colourspace("srgb")
    if image.format != "uchar":
        image = image.cast("uchar")
    pixels = np.frombuffer(image.write_to_memory(), dtype=np.uint8)
    pixels = pixels.reshape(image.height, image.width, image.bands)
    return cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)


def _raster_to_jpeg(source: Path, destination: Path) -> tuple[int, int]:
    image = pyvips.Image.new_from_file(str(source), access="sequential")
    width, height = image.width, image.height
    if image.interpretation == pyvips.Interpretation.CMYK:
        image = image.colourspace("srgb")
    if image.hasalpha():
        image = image.flatten(background=[255] * (image.bands - 1))
    if image.format == "ushort":
        image = image.cast("uchar", shift=True)
    elif image.format != "uchar":
        image = image.cast("uchar")
    image = image.copy(xres=72 / 25.4, yres=72 / 25.4)
    image.jpegsave(str(destination), Q=92, optimize_coding=True)
    return width, height


def _vector_to_jpegs(source: Path, destination_base: Path) -> list[tuple[Path, int, int, int]]:
    document = fitz.open(filename=str(source), filetype="pdf")
    converted = []
    try:
        for index, page in enumerate(document):
            destination = destination_base.with_name(
                f"{destination_base.stem}_p{index + 1:03d}.jpg"
            )
            pixmap = page.get_pixmap(dpi=72, colorspace=fitz.csRGB, alpha=False)
            pixmap.save(str(destination), jpg_quality=92)
            converted.append((destination, index + 1, pixmap.width, pixmap.height))
    except Exception:
        for path, *_ in converted:
            path.unlink(missing_ok=True)
        raise
    finally:
        document.close()
    if not converted:
        raise ValueError("文件没有可转换的页面")
    return converted


def _output_base(source: Path, root: Path, output: Path) -> Path:
    relative = source.relative_to(root)
    folder = output / relative.parent
    folder.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower().lstrip(".")
    return folder / f"{source.stem}__{suffix}.jpg"


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def scan_and_convert(
    source_root: Path,
    output_root: Path,
    db_path: Path,
    progress: Callable[[dict], None],
) -> dict[str, int]:
    root = source_root.resolve()
    output = output_root.resolve()
    if root == output:
        raise ValueError("JPG 输出文件夹不能与花型库源文件夹相同")

    db = LibraryDB(db_path)
    sources: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        resolved = path.resolve()
        if _inside(resolved, output):
            continue
        sources[str(resolved)] = resolved

    with db.connect() as connection:
        known = connection.execute("SELECT * FROM sources").fetchall()
    old = {row["source_path"]: row for row in known}
    deleted = set(old) - set(sources)
    for source_path in deleted:
        db.remove_source(source_path, delete_files=True)
        progress({"name": Path(source_path).name, "status": "已删除", "elapsed": "—", "message": "源文件已移除"})

    converted = failed = skipped = 0
    items = list(sources.values())
    for source in items:
        source_path = str(source)
        relative = source.relative_to(root).as_posix()
        try:
            stat = source.stat()
        except OSError as exc:
            failed += 1
            progress({"name": source.name, "status": "失败", "elapsed": "—", "message": str(exc)})
            continue

        previous = old.get(source_path)
        unchanged = previous and previous["size"] == stat.st_size and previous["mtime_ns"] == stat.st_mtime_ns
        previous_outputs = json.loads(previous["outputs"]) if previous else []
        if unchanged and previous["status"] == "完成" and previous_outputs and all(Path(p).is_file() for p in previous_outputs):
            skipped += 1
            continue

        started = time.monotonic()
        outputs: list[str] = []
        generated: list[tuple[Path, int, int, int]] = []
        try:
            if time.time() - stat.st_mtime < 3:
                skipped += 1
                progress({"name": source.name, "status": "稍后重试", "elapsed": "—", "message": "文件刚更新，等待写入完成"})
                continue
            if previous:
                db.remove_source(source_path, delete_files=True)
            base = _output_base(source, root, output)
            if source.suffix.lower() in RASTER:
                width, height = _raster_to_jpeg(source, base)
                generated.append((base, 0, width, height))
            else:
                generated.extend(_vector_to_jpegs(source, base))

            after = source.stat()
            if after.st_size != stat.st_size or after.st_mtime_ns != stat.st_mtime_ns:
                for path, *_ in generated:
                    path.unlink(missing_ok=True)
                skipped += 1
                progress({"name": source.name, "status": "稍后重试", "elapsed": format_elapsed(time.monotonic() - started), "message": "转换期间源文件发生变化"})
                continue

            for path, page, _, _ in generated:
                histogram, points, descriptors, count = _features(_decode_file(path))
                db.save_image(
                    str(path), source_path, relative, page,
                    histogram, points, descriptors, count,
                )
                outputs.append(str(path))
            elapsed = time.monotonic() - started
            db.save_source(source_path, relative, stat.st_size, stat.st_mtime_ns, outputs, "完成", elapsed, "")
            converted += 1
            progress({"name": source.name, "status": "完成", "elapsed": format_elapsed(elapsed), "message": f"{len(outputs)} 张 JPG"})
        except Exception as exc:
            for path, *_ in generated:
                path.unlink(missing_ok=True)
            for path in outputs:
                Path(path).unlink(missing_ok=True)
            with db.connect() as connection:
                connection.execute("DELETE FROM images WHERE source_path=?", (source_path,))
            elapsed = time.monotonic() - started
            db.save_source(source_path, relative, stat.st_size, stat.st_mtime_ns, [], "失败", elapsed, str(exc))
            failed += 1
            progress({"name": source.name, "status": "失败", "elapsed": format_elapsed(elapsed), "message": str(exc)})

    return {"found": len(items), "converted": converted, "failed": failed, "skipped": skipped}


def search_images(
    db_path: Path,
    query_bytes: bytes,
    scope: str,
    threshold: int,
    progress: Callable[[int, int], None],
) -> list[dict]:
    query = cv2.imdecode(np.frombuffer(query_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if query is None:
        raise ValueError("查询图片无法读取")
    qhist, qpoints_blob, qdesc_blob, qcount = _features(query)
    if qcount < 4:
        raise ValueError("图片可用于搜索的局部特征太少，请换一张图片或扩大裁剪区域")
    qpoints = np.frombuffer(qpoints_blob, dtype=np.float32).reshape(-1, 2)
    qdesc = np.frombuffer(qdesc_blob, dtype=np.uint8).reshape(-1, 32)
    qhist_array = np.frombuffer(qhist, dtype=np.float32)

    database = LibraryDB(db_path)
    records = database.image_records()
    if scope:
        prefix = scope.rstrip("/") + "/"
        records = [r for r in records if r["relative_path"] == scope or r["relative_path"].startswith(prefix)]
    records = [r for r in records if Path(r["output_path"]).is_file() and r["feature_count"] >= 2]
    if not records:
        return []

    ranked = []
    for row in records:
        hist = np.frombuffer(row["histogram"], dtype=np.float32)
        color_score = float(np.minimum(qhist_array, hist).sum())
        ranked.append((color_score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    candidates = [row for _, row in ranked[: min(500, len(ranked))]]

    results = []
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    # ponytail: 500 color-ranked candidates bounds search time for large libraries; persist an LSH index if recall needs to grow.
    with database.connect() as connection:
        for index, row in enumerate(candidates, 1):
            features = connection.execute(
                "SELECT points, descriptors FROM images WHERE output_path=?", (row["output_path"],)
            ).fetchone()
            if not features:
                continue
            candidate_desc = np.frombuffer(features["descriptors"], dtype=np.uint8).reshape(-1, 32)
            candidate_points = np.frombuffer(features["points"], dtype=np.float32).reshape(-1, 2)
            if len(candidate_desc) < 2:
                continue
            matches = matcher.knnMatch(qdesc, candidate_desc, k=2)
            good = [pair[0] for pair in matches if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance]
            if len(good) >= 4:
                source_points = np.float32([qpoints[item.queryIdx] for item in good])
                target_points = np.float32([candidate_points[item.trainIdx] for item in good])
                _, mask = cv2.findHomography(source_points, target_points, cv2.RANSAC, 5.0)
                inliers = int(mask.sum()) if mask is not None else len(good)
            else:
                inliers = len(good)
            score = min(100, round(inliers * 100 / max(1, qcount)))
            if score >= threshold:
                results.append(
                    {
                        "source_path": row["source_path"],
                        "relative_path": row["relative_path"],
                        "page": row["page"],
                        "score": score,
                    }
                )
            if index % 10 == 0 or index == len(candidates):
                progress(index, len(candidates))
    results.sort(key=lambda item: item["score"], reverse=True)
    return results
