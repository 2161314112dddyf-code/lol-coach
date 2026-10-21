import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class EvidenceClient:
    """Bounded read-only HTTP; immutable body cache and append-only attempt evidence."""

    def __init__(self, root, *, timeout=12, retries=1, interval=0.4, opener=urlopen, max_bytes=8_000_000):
        self.root = Path(root)
        self.timeout, self.retries, self.interval = timeout, retries, interval
        self.opener = opener
        self.max_bytes = max_bytes
        self.last_request = 0.0

    def fetch(self, source_id, url, *, expect_json=False, refresh=False, offline=False):
        key = hashlib.sha256(url.encode()).hexdigest()
        index = self.root / "cache" / (key + ".json")
        if index.exists() and not refresh:
            old = json.loads(index.read_text(encoding="utf-8"))
            body_path = self.root / old["evidence_path"]
            if body_path.exists() and hashlib.sha256(body_path.read_bytes()).hexdigest() == old["sha256"]:
                old["cache_hit"] = True
                return self._classify(old, body_path.read_bytes(), expect_json)
        record = dict(source_id=source_id, requested_url=url, final_url=None,
                      retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
                      http_status=None, content_type=None, sha256=None,
                      content_version=None, status="network_error", evidence_path=None,
                      limitations=[], cache_hit=False, attempts=[],
                      license_review_status="not_reviewed", target_client_version_status="unverified")
        body = None
        if offline:
            record["status"] = "cache_miss"
            record["limitations"].append("Offline mode: no verified cache available")
        else:
            for attempt in range(self.retries + 1):
                time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
                try:
                    req = Request(url, headers={"User-Agent": "lol-coach-source-audit/0.1", "Accept-Encoding": "identity"})
                    with self.opener(req, timeout=self.timeout) as response:
                        record.update(http_status=response.status, final_url=response.geturl(),
                                      content_type=response.headers.get("Content-Type"))
                        length = response.headers.get("Content-Length")
                        if length and int(length) > self.max_bytes:
                            raise ValueError(f"Response exceeds {self.max_bytes} byte audit limit")
                        body = response.read(self.max_bytes + 1)
                        if len(body) > self.max_bytes:
                            raise ValueError(f"Response exceeds {self.max_bytes} byte audit limit")
                    record["attempts"].append({"attempt": attempt + 1, "status": record["http_status"]})
                    break
                except HTTPError as exc:
                    record.update(http_status=exc.code, final_url=exc.geturl(), content_type=exc.headers.get("Content-Type"))
                    body = exc.read(self.max_bytes)
                    record["status"] = "blocked" if exc.code in (401, 403, 429) else "http_error"
                    record["attempts"].append({"attempt": attempt + 1, "error": str(exc)})
                    if exc.code < 500:
                        break
                except (URLError, TimeoutError, OSError, ValueError) as exc:
                    record["attempts"].append({"attempt": attempt + 1, "error": str(exc)})
                    body = None
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        if body is not None:
            digest = hashlib.sha256(body).hexdigest()
            relative = "raw/" + digest + ".bin"
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            record.update(sha256=digest, evidence_path=relative)
        record, data = self._classify(record, body, expect_json)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        save_json(self.root / "attempts" / (key + "-" + stamp + ".json"), record)
        if record["http_status"] == 200 and body is not None:
            save_json(index, record)
        return record, data

    @staticmethod
    def _classify(record, body, expect_json):
        if record["http_status"] != 200 or body is None:
            return record, None
        if not expect_json:
            record["status"] = "accessible_unvalidated"
            return record, None
        if "json" not in (record["content_type"] or "").lower():
            record["status"] = "non_json"
            return record, None
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            record["status"] = "invalid_json"
            return record, None
        record["status"] = "json_parsed_fields_unverified"
        if isinstance(data, dict):
            record["content_version"] = data.get("version") or data.get("patch")
        return record, data
