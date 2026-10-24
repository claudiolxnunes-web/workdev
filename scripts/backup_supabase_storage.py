#!/usr/bin/env python3
"""Backup Supabase Storage buckets without logging credentials or signed URLs."""

import argparse
import hashlib
import json
import os
import pathlib
import time
import urllib.parse
import urllib.request


def request_json(url: str, key: str, payload: dict) -> object:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def list_files(base_url: str, key: str, bucket: str, prefix: str = "") -> list[str]:
    result: list[str] = []
    offset = 0
    while True:
        items = request_json(
            f"{base_url}/storage/v1/object/list/{urllib.parse.quote(bucket, safe='')}",
            key,
            {"prefix": prefix, "limit": 1000, "offset": offset, "sortBy": {"column": "name", "order": "asc"}},
        )
        if not isinstance(items, list):
            raise RuntimeError(f"Unexpected listing response for {bucket}/{prefix}")
        for item in items:
            name = item["name"]
            path = f"{prefix}/{name}" if prefix else name
            if item.get("id") is None:
                result.extend(list_files(base_url, key, bucket, path))
            else:
                result.append(path)
        if len(items) < 1000:
            break
        offset += 1000
    return result


def safe_destination(root: pathlib.Path, relative: str) -> pathlib.Path:
    destination = (root / relative).resolve()
    if root.resolve() not in destination.parents:
        raise ValueError(f"Unsafe object path: {relative!r}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--bucket", action="append", required=True)
    args = parser.parse_args()

    credentials = json.loads(pathlib.Path(args.credentials).read_text())
    base_url = credentials["url"].rstrip("/")
    key = credentials["service_role"]
    output = pathlib.Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []

    for bucket in args.bucket:
        paths = list_files(base_url, key, bucket)
        for index, object_path in enumerate(paths, 1):
            encoded = urllib.parse.quote(object_path, safe="/")
            url = f"{base_url}/storage/v1/object/authenticated/{urllib.parse.quote(bucket, safe='')}/{encoded}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "apikey": key})
            destination = safe_destination(output / bucket, object_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            temporary = destination.with_name(destination.name + ".partial")
            for attempt in range(5):
                try:
                    digest = hashlib.sha256()
                    size = 0
                    with urllib.request.urlopen(req, timeout=120) as response, temporary.open("wb") as target:
                        while chunk := response.read(1024 * 1024):
                            target.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    temporary.replace(destination)
                    break
                except Exception:
                    temporary.unlink(missing_ok=True)
                    if attempt == 4:
                        raise
                    time.sleep(2 ** attempt)
            manifest.append({"bucket": bucket, "path": object_path, "size": size, "sha256": digest.hexdigest()})
            print(f"{bucket}: {index}/{len(paths)}", flush=True)

    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    os.chmod(manifest_path, 0o600)
    summary = {bucket: sum(1 for item in manifest if item["bucket"] == bucket) for bucket in args.bucket}
    print(json.dumps({"files": len(manifest), "buckets": summary}))


if __name__ == "__main__":
    main()
