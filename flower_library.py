import sqlite3
import uuid
from pathlib import Path

import cv2
import numpy as np
import pyvips
from PySide6.QtCore import QObject, QThread, Signal, Slot


IMAGE_EXTENSIONS = {".tif", ".tiff", ".jpg", ".jpeg", ".png"}
PREVIEW_EDGE = 2400
MAX_FEATURES = 1000


class LibraryWorker(QObject):
    status = Signal(str)
    progress = Signal(int, int)
    results = Signal(list)
    failed = Signal(str)
    roots_changed = Signal(list)
    preview_ready = Signal(str, int, int)

    def __init__(self, data_dir):
        super().__init__()
        self.data_dir = Path(data_dir)
        self.cache_dir = self.data_dir / "cache"
        self.db = None
        self.matcher = None
        self.image_ids = None
        self.orb = cv2.ORB_create(nfeatures=MAX_FEATURES)

    @Slot()
    def initialize(self):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            for temporary in self.cache_dir.glob(".*.tmp"):
                temporary.unlink(missing_ok=True)
            self.db = sqlite3.connect(self.data_dir / "library.sqlite3")
            self.db.execute("CREATE TABLE IF NOT EXISTS roots (path TEXT PRIMARY KEY)")
            self.db.execute("""CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY,
                root TEXT NOT NULL,
                path TEXT UNIQUE NOT NULL,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                thumbnail TEXT NOT NULL,
                features TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT ''
            )""")
            self.db.commit()
            roots = [row[0] for row in self.db.execute("SELECT path FROM roots")]
            if roots:
                self._index_roots(roots)
            else:
                self._build_search_index()
                self.status.emit("已就绪，可添加花型目录")
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot(str)
    def add_root(self, root):
        try:
            path = str(Path(root).resolve())
            self.db.execute("INSERT OR IGNORE INTO roots(path) VALUES (?)", (path,))
            self.db.commit()
            self._index_roots([path])
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot()
    def rescan(self):
        try:
            roots = [row[0] for row in self.db.execute("SELECT path FROM roots")]
            self._index_roots(roots)
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot(str)
    def load_preview(self, path):
        try:
            data, gray = self._read_preview(path)
            preview_path = self.cache_dir / "query_preview.jpg"
            preview_path.write_bytes(data)
            self.preview_ready.emit(str(preview_path), gray.shape[1], gray.shape[0])
        except Exception as exc:
            self.failed.emit(str(exc))

    def _read_preview(self, path, max_edge=PREVIEW_EDGE):
        image = pyvips.Image.new_from_file(
            str(path), access="sequential", unlimited=True
        ).thumbnail_image(max_edge, size="down")
        pixels = image.write_to_buffer(".png")
        color = cv2.imdecode(np.frombuffer(pixels, np.uint8), cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        preview = cv2.imencode(".jpg", color, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
        return preview, gray

    def _index_roots(self, roots):
        files = []
        online_roots = []
        for root in roots:
            folder = Path(root)
            if folder.is_dir():
                online_roots.append(str(folder.resolve()))
                files.extend(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)

        tiffs = {
            p.with_suffix(suffix).resolve()
            for p in files
            if p.suffix.lower() in {".tif", ".tiff"}
            for suffix in (".jpg", ".jpeg")
        }
        files = [p for p in files if p.suffix.lower() not in {".jpg", ".jpeg"} or p.resolve() not in tiffs]
        total = len(files)
        current_paths = {str(path.resolve()) for path in files}
        known = {
            path
            for path, root in self.db.execute("SELECT path,root FROM items")
            if root not in online_roots or path in current_paths
        }
        if len(known | current_paths) > 20_000:
            self.failed.emit("图库最多支持 20,000 个花型，请先移除部分目录或文件。")
            return
        self.status.emit(f"正在检查 {total:,} 个图片文件")
        seen_by_root = {root: set() for root in online_roots}

        for number, path in enumerate(files, 1):
            if QThread.currentThread().isInterruptionRequested():
                self.db.commit()
                self.status.emit("建库已暂停；下次启动或更新图库时可继续")
                return
            resolved_path = path.resolve()
            root = next(
                (r for r in sorted(online_roots, key=len, reverse=True) if resolved_path.is_relative_to(Path(r))),
                "",
            )
            if root:
                seen_by_root[root].add(str(resolved_path))
            existing = None
            item_id = None
            temporary_features = None
            temporary_thumb = None
            try:
                stat = path.stat()
                existing = self.db.execute(
                    "SELECT id,size,mtime,error,features FROM items WHERE path=?", (str(path.resolve()),)
                ).fetchone()
                if (
                    existing
                    and existing[1] == stat.st_size
                    and existing[2] == stat.st_mtime
                    and not existing[3]
                    and existing[4]
                    and Path(existing[4]).is_file()
                ):
                    self.progress.emit(number, total)
                    continue

                if existing:
                    item_id = existing[0]
                else:
                    cursor = self.db.execute(
                        "INSERT INTO items(root,path,size,mtime,thumbnail,features) VALUES (?,?,?,?,?,?)",
                        (root, str(path.resolve()), stat.st_size, stat.st_mtime, "", ""),
                    )
                    item_id = cursor.lastrowid

                thumb_path = self.cache_dir / f"{item_id}.jpg"
                feature_path = self.cache_dir / f"{item_id}.npz"
                image_data, gray = self._read_preview(path)
                keypoints, descriptors = self.orb.detectAndCompute(gray, None)
                points = np.array([kp.pt for kp in keypoints], dtype=np.float32)
                if descriptors is None:
                    descriptors = np.empty((0, 32), dtype=np.uint8)
                temporary_features = feature_path.with_name(f".{feature_path.name}.{uuid.uuid4().hex}.tmp")
                temporary_thumb = thumb_path.with_name(f".{thumb_path.name}.{uuid.uuid4().hex}.tmp")
                with temporary_features.open("wb") as output:
                    np.savez_compressed(output, points=points, descriptors=descriptors)
                temporary_thumb.write_bytes(image_data)
                temporary_features.replace(feature_path)
                temporary_thumb.replace(thumb_path)
                self.db.execute(
                    "UPDATE items SET root=?,size=?,mtime=?,thumbnail=?,features=?,error='' WHERE id=?",
                    (root, stat.st_size, stat.st_mtime, str(thumb_path), str(feature_path), item_id),
                )
            except Exception as exc:
                if temporary_features:
                    temporary_features.unlink(missing_ok=True)
                if temporary_thumb:
                    temporary_thumb.unlink(missing_ok=True)
                item_id = existing[0] if existing else item_id
                if item_id:
                    self.db.execute("UPDATE items SET error=? WHERE id=?", (str(exc), item_id))
                self.status.emit(f"读取失败：{path.name}（{exc}）")
            if number % 25 == 0:
                self.db.commit()
            self.progress.emit(number, total)

        for root, seen in seen_by_root.items():
            rows = self.db.execute("SELECT id,path FROM items WHERE root=?", (root,)).fetchall()
            for item_id, path in rows:
                if path not in seen:
                    self.db.execute("DELETE FROM items WHERE id=?", (item_id,))
                    (self.cache_dir / f"{item_id}.jpg").unlink(missing_ok=True)
                    (self.cache_dir / f"{item_id}.npz").unlink(missing_ok=True)
        self.db.commit()
        self.status.emit("正在构建本地搜索索引")
        self._build_search_index()
        self.roots_changed.emit([row[0] for row in self.db.execute("SELECT path FROM roots ORDER BY path")])
        count = self.db.execute("SELECT COUNT(*) FROM items WHERE error='' AND features<>''").fetchone()[0]
        self.status.emit(f"图库已就绪：{count:,} 个花型")

    def _build_search_index(self):
        rows = self.db.execute("SELECT id,features FROM items WHERE error='' AND features<>''").fetchall()
        descriptors, ids = [], []
        for item_id, path in rows:
            try:
                with np.load(path) as data:
                    desc = data["descriptors"]
                if len(desc):
                    descriptors.append(desc)
                    ids.append(item_id)
            except (OSError, KeyError, ValueError):
                continue
        if not descriptors:
            self.matcher = None
            self.image_ids = None
            return
        matcher = cv2.FlannBasedMatcher(
            {"algorithm": 6, "table_number": 12, "key_size": 12, "multi_probe_level": 1}, {}
        )
        matcher.add(descriptors)
        matcher.train()
        self.matcher = matcher
        self.image_ids = ids

    @Slot(str, object)
    def search(self, query_path, selection):
        try:
            if self.matcher is None:
                self.failed.emit("图库还没有可搜索的花型")
                return
            _, gray = self._read_preview(query_path)
            if selection:
                x, y, width, height = selection
                left, top = int(x * gray.shape[1]), int(y * gray.shape[0])
                right = int((x + width) * gray.shape[1])
                bottom = int((y + height) * gray.shape[0])
                gray = gray[top:bottom, left:right]
            query_points, query_desc = self.orb.detectAndCompute(gray, None)
            if query_desc is None or len(query_desc) < 4:
                self.results.emit([])
                return

            nearest = self.matcher.knnMatch(query_desc, k=10)
            votes = {}
            for pair in nearest:
                seen = set()
                for match in pair:
                    item_id = self.image_ids[match.imgIdx]
                    if match.distance < 120 and item_id not in seen:
                        votes[item_id] = votes.get(item_id, 0) + 1
                        seen.add(item_id)

            candidates = sorted(votes, key=votes.get, reverse=True)[:100]
            ranked = []
            for item_id in candidates:
                row = self.db.execute(
                    "SELECT path,thumbnail,features FROM items WHERE id=?", (item_id,)
                ).fetchone()
                if not row:
                    continue
                with np.load(row[2]) as data:
                    points, descriptors = data["points"], data["descriptors"]
                if len(descriptors) < 2:
                    continue
                pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(query_desc, descriptors, k=2)
                good = [a for a, b in pairs if a.distance < 0.75 * b.distance]
                inliers = 0
                if len(good) >= 4:
                    source = np.float32([query_points[m.queryIdx].pt for m in good])
                    target = np.float32([points[m.trainIdx] for m in good])
                    _, mask = cv2.findHomography(source, target, cv2.RANSAC, 5.0)
                    if mask is not None:
                        inliers = int(mask.sum())
                if inliers >= 4:
                    ranked.append((inliers, votes[item_id], row[0], row[1]))
            ranked.sort(reverse=True)
            self.results.emit(ranked[:30])
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot(str, str)
    def convert(self, source_dir, output_dir):
        try:
            source = Path(source_dir).resolve()
            output = Path(output_dir).resolve()
            if source == output or source in output.parents:
                raise ValueError("JPG 输出目录请选在原图库目录之外")
            files = [p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in {".tif", ".tiff"}]
            self.status.emit(f"正在转换 {len(files):,} 个 TIFF")
            failures = []
            for number, path in enumerate(files, 1):
                if QThread.currentThread().isInterruptionRequested():
                    self.status.emit("转换已暂停；原文件未修改")
                    return
                relative = path.relative_to(source).with_suffix(".jpg")
                target = output / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                suffix = 1
                while target.exists():
                    target = target.with_name(f"{relative.stem}_{suffix}.jpg")
                    suffix += 1
                temporary = target.with_name(f".{uuid.uuid4().hex}.tmp.jpg")
                try:
                    image = pyvips.Image.new_from_file(
                        str(path), access="sequential", unlimited=True
                    ).thumbnail_image(4096, size="down")
                    image.write_to_file(str(temporary), Q=90, strip=True)
                    temporary.replace(target)
                except Exception as exc:
                    temporary.unlink(missing_ok=True)
                    failures.append(f"{path.name}: {exc}")
                self.progress.emit(number, len(files))
            if failures:
                self.status.emit(
                    f"转换完成：{len(files) - len(failures):,}/{len(files):,} 个成功；失败 {len(failures)} 个："
                    + "；".join(failures[:5])
                )
            else:
                self.status.emit(f"转换完成：{len(files):,} 个 JPG")
        except Exception as exc:
            self.failed.emit(str(exc))
