# pmj-simpletool-real

本番系統(pmj-door-real から呼ばれ、`gs://pmjbase/real/` 直下に置く)。ソースは pmj-simpletool とほぼ同じ。

小さな道具をまとめる Cloud Run サービス (Python / Flask)。
今あるのは「ファイルを GCS に置く」(`POST /gcs_put`) だけ。

## 2系統

| 系統 | 呼び出し元 → door | このサービス | 置き先 |
|---|---|---|---|
| 検証 | test1 の cron → pmj-door | pmj-simpletool | `gs://pmjbase/` 直下 |
| 本番 | test1 の cron → pmj-door-real | **pmj-simpletool-real** | `gs://pmjbase/real/` 直下 |

ソースは2つのリポジトリでほぼ同じで、違いは既定値だけ
(`SERVICE_NAME` と `GCS_PREFIX` の既定。こちらは直下、-real は `real/`)。

## 使い方 (door 経由)

```
POST https://pmj-door-real-512697354748.asia-northeast1.run.app/call
Authorization: Bearer <ID token>
{
  "target": "simpletool",
  "path": "/gcs_put",
  "payload": {
    "filename": "v2ac_kanjo_master.json",
    "content_gzip_b64": "<中身を gzip → base64>",
    "md5": "<元の中身の md5>"
  }
}
→ { "status":"OK", "uri":"gs://pmjbase/real/v2ac_kanjo_master.json", "size":..., "md5":"...", "elapsed":... }
```

- ファイル名はフォルダなし(英数字と `. _ -` のみ)。決まったフォルダ(直下 / real/)以外には置けない
- md5 を渡すと照合し、違えば NG
- 展開後の上限は 50MB (`SIMPLETOOL_MAX_MB`)

## Cloud Run の設定

- ソース: このリポジトリ(push で自動ビルド)
- 認証: 「認証が必要」。pmj-door-real のサービスアカウントに `roles/run.invoker` を付ける
- このサービスのサービスアカウントに、バケット `pmjbase` への書き込み権限 (`roles/storage.objectAdmin` など)
- pmj-door-real の環境変数に `TARGET_SIMPLETOOL=<このサービスの URL>` を追加
- 環境変数(任意): `GCS_BUCKET`(既定 pmjbase) / `GCS_PREFIX`(既定 real/) / `SIMPLETOOL_MAX_MB`(既定 50)

## 呼び出し元 (test1 の cron)

`/data/pmj_cron/master_to_gcs.php` が10分ごとに `/var/www/html/pys/v2ac_kanjo_master.json` を見て、
30分以内に更新されていて、かつ前回送ったものと中身(md5)が違えば、2系統それぞれへ送る。
ソースは pmj-font リポジトリの `_server/` にある。
