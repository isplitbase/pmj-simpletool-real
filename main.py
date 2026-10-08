# -*- coding: utf-8 -*-
"""pmj-simpletool : 小さな道具をまとめる API (Cloud Run)

  今あるのは「ファイルを GCS に置く」だけ。
  サーバ(test1 など)の cron から、マスタ(v2ac_kanjo_master.json)を GCS へ転送するのに使う。

      cron(php) → pmj-door → [このサービス] → GCS gs://pmjbase/ 直下
      cron(php) → pmj-door-real → pmj-simpletool-real → GCS gs://pmjbase/real/ 直下

  エンドポイント:
    GET  /         … ヘルスチェック(置き場所も返す)
    POST /gcs_put  … ファイルを GCS に置く

  POST /gcs_put の入力:
    {
      "filename":         "v2ac_kanjo_master.json",  # 必須。フォルダなしのファイル名だけ
      "content_gzip_b64": "…",                       # 必須。中身を gzip して base64 にしたもの
      "md5":              "…",                       # 任意。元の中身の md5(16進)。あれば照合する
      "content_type":     "application/json"         # 任意。省略時は拡張子から決める
    }
  返り値:
    { "status":"OK", "uri":"gs://pmjbase/v2ac_kanjo_master.json",
      "size":3813435, "md5":"…", "elapsed":0.8 }

  環境変数 (Cloud Run に設定。無ければ下の既定値):
    GCS_BUCKET        … 置き先のバケット。既定 pmjbase
    GCS_PREFIX        … バケット内のフォルダ。既定 "real/"(この -real 版)。無印版は ""(直下)
    SIMPLETOOL_MAX_MB … 受け取るファイルの上限MB(展開後)。既定 50

  GCS への書き込みは Cloud Run のサービスアカウント(ADC)で行う。
  そのサービスアカウントに、バケットへの書き込み権限(roles/storage.objectAdmin など)が必要。
"""

import base64
import binascii
import gzip
import hashlib
import io
import os
import re
import time

from flask import Flask, jsonify, request

app = Flask(__name__)

SERVICE_NAME = "pmj-simpletool-real"
GCS_BUCKET = os.environ.get("GCS_BUCKET", "pmjbase")
GCS_PREFIX = os.environ.get("GCS_PREFIX", "real/")
MAX_BYTES = int(float(os.environ.get("SIMPLETOOL_MAX_MB", "50")) * 1024 * 1024)

# ファイル名はフォルダなし・英数字と . _ - だけ(先頭の . は不可)
FILENAME_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,199}$")

CONTENT_TYPES = {
    ".json": "application/json",
    ".csv": "text/csv",
    ".txt": "text/plain",
}


def _prefix():
    p = GCS_PREFIX.strip().strip("/")
    return (p + "/") if p else ""


def _ng(msg, code=400):
    return jsonify({"status": "NG", "error": msg}), code


@app.get("/")
def health():
    return jsonify({"status": "ok", "service": SERVICE_NAME,
                    "dest": "gs://%s/%s" % (GCS_BUCKET, _prefix())})


@app.post("/gcs_put")
def gcs_put():
    t0 = time.time()
    body = request.get_json(silent=True) or {}

    filename = str(body.get("filename") or "")
    if not FILENAME_RE.match(filename):
        return _ng("filename が不正です(フォルダなし・英数字と . _ - のみ)")

    b64 = body.get("content_gzip_b64")
    if not b64:
        return _ng("content_gzip_b64 がありません")
    try:
        packed = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return _ng("content_gzip_b64 が base64 として読めません")
    try:
        # 展開しすぎ(圧縮爆弾)を防ぐため、上限+1 バイトまでしか読まない
        with gzip.GzipFile(fileobj=io.BytesIO(packed)) as gz:
            data = gz.read(MAX_BYTES + 1)
    except (OSError, EOFError):
        return _ng("gzip として展開できません")
    if len(data) > MAX_BYTES:
        return _ng("ファイルが大きすぎます(上限 %d MB)" % (MAX_BYTES // 1024 // 1024))

    md5 = hashlib.md5(data).hexdigest()
    want = str(body.get("md5") or "").lower()
    if want and want != md5:
        return _ng("md5 が一致しません(送信側 %s / 受信 %s)" % (want, md5))

    ctype = body.get("content_type") or CONTENT_TYPES.get(os.path.splitext(filename)[1].lower(),
                                                          "application/octet-stream")
    name = _prefix() + filename
    try:
        from google.cloud import storage
        blob = storage.Client().bucket(GCS_BUCKET).blob(name)
        blob.upload_from_string(data, content_type=ctype)
    except Exception as e:
        return _ng("GCS 書き込みエラー: %s" % str(e)[:300], 502)

    return jsonify({"status": "OK", "uri": "gs://%s/%s" % (GCS_BUCKET, name),
                    "size": len(data), "md5": md5,
                    "elapsed": round(time.time() - t0, 2)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
