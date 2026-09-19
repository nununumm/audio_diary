# 音声日記 (audio_diary)

音声で話すだけで日記を残せる、自分専用の Web アプリ（PWA）です。

- 🎙 スマホのブラウザで録音 → **Gemini** で文字起こし
- ✨ 「えーと」などのフィラーを除去し、曖昧な話し方を自然な文章に**AI整形**
- 📷 写真を添付
- 🔍 過去の日記を**全文検索**
- 📱 ホーム画面に追加してアプリのように使える（PWA）
- 🗄 データは自宅サーバーに保存（写真の保存先は将来クラウド等へ差し替え可能）

生の文字起こしと AI 整形後の本文の**両方を保存**するので、整形で意図がずれても元を確認・修正できます。

---

## 構成

```
audio_diary/
├─ backend/            FastAPI + SQLite
│  ├─ app/
│  │  ├─ main.py          ルート定義
│  │  ├─ config.py        設定（.env）
│  │  ├─ db.py            SQLite スキーマ / 全文検索(FTS5)
│  │  ├─ auth.py          単一ユーザー認証（署名Cookie）
│  │  ├─ transcription.py 文字起こし（Gemini / Google STT 切替）
│  │  ├─ cleanup.py       AI整形（Gemini）
│  │  ├─ audio.py         音声形式の正規化（ffmpeg）
│  │  ├─ images.py        写真のサムネイル生成
│  │  └─ storage.py       写真の保存（ローカル／将来クラウド）
│  ├─ requirements.txt
│  └─ .env.example
└─ frontend/           PWA（バニラJS）
   ├─ index.html / app.js / styles.css
   ├─ manifest.json / sw.js / icon.svg
```

---

## セットアップ（ローカル / サーバー共通）

### 1. Gemini API キーを取得
無料で取得できます: <https://aistudio.google.com/apikey>

### 2. 依存パッケージ
```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. ffmpeg（推奨）
ブラウザの録音形式（WebM/Opus）を Gemini が読める形式に変換するのに使います。
未インストールでも動く場合がありますが、入れておくと確実です。
```bash
# Debian/Ubuntu 系（古いスマホの Linux 含む）
sudo apt install ffmpeg
```

### 4. 設定ファイル
```bash
cp .env.example .env
# .env を編集:
#   DIARY_SECRET_KEY  … python -c "import secrets;print(secrets.token_urlsafe(48))" で生成
#   DIARY_PASSWORD    … ログインパスワード
#   GEMINI_API_KEY    … 手順1で取得したキー
```

### 5. 起動
```bash
# backend ディレクトリで
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
ブラウザで `http://<サーバーのIP>:8000/` を開く → パスワードでログイン。

> `GEMINI_API_KEY` 未設定でも起動はできます（文字起こしはサンプル文、整形は無効）。動作確認用です。

---

## 文字起こしプロバイダの切り替え

`.env` の `DIARY_TRANSCRIBER` で選べます。

| 値 | 内容 | 必要なもの |
|----|------|-----------|
| `gemini`（既定） | Gemini で文字起こし | `GEMINI_API_KEY` のみ |
| `google_stt` | Google Cloud Speech-to-Text | `pip install google-cloud-speech` + `GOOGLE_APPLICATION_CREDENTIALS`（サービスアカウントJSON） |

---

## 外出先から安全に使う（Tailscale + HTTPS）

自分専用ですが外からも使うため、**ポートを直接公開せず Tailscale（無料VPN）経由**を推奨します。
Tailscale は無料で HTTPS 証明書も発行できるので、**VPN + HTTPS + アプリのログイン**の三重で守れます。追加費用はかかりません。

1. サーバーとスマホの両方に Tailscale を入れてログイン（同じアカウント）
2. サーバーで HTTPS 配信を有効化:
   ```bash
   # uvicorn を 8000 で起動しておき、Tailscale で HTTPS 公開
   tailscale serve https / http://127.0.0.1:8000
   ```
3. スマホから `https://<マシン名>.<tailnet>.ts.net/` を開く
4. HTTPS で使う場合は `app/main.py` の Cookie 設定を `secure=True` に変更するとより安全です

> ポートをそのままインターネットに公開する運用は推奨しません（総当たり攻撃の対象になります）。どうしても公開する場合は、リバースプロキシ（Caddy 等）で HTTPS 化し、ログイン試行のレート制限を必ず追加してください。

---

## データとバックアップ

- 日記本文: `backend/data/diary.db`（SQLite）
- 写真: `backend/data/photos/`
- バックアップはこの `data/` ディレクトリをコピーするだけです。
- 写真の保存先は `app/storage.py` の `StorageBackend` を実装すれば、Google Drive や別サーバーへ差し替えられます（サーバー容量対策）。

---

## 今後の拡張（土台のみ用意済み）

- **Google カレンダー連携**（用途が決まり次第）
- 写真のクラウド移送（`StorageBackend` 追加実装）
- オフライン録音キュー
