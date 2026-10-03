# Ollama 接続

## 接続先

感情・話し方の自動選択は、bot から Ollama の `/api/generate` を直接呼び出す。Docker Desktop のホスト側 Ollama を既定とし、URL は `http://host.docker.internal:11434`。`OLLAMA_HOST` で上書きできる。Compose の明示設定でも環境変数の指定を尊重する。

Agent Gateway は Claude Code / Codex CLI 用の API であり、Ollama の呼び出しは担当しない。従来の内部プロキシは `ollama:11434` を転送先としていたが、実環境ではホスト側 Ollama が応答するため直接接続する。bot は Compose の default ネットワークだけで動作し、共有ネットワークへの参加は不要。

## モデルと動作

`OLLAMA_MODEL` は導入済みモデル名に設定する。未指定時は `qwen3.5:2b`。直接接続への変更では判定方式を維持し、通常判定のタイムアウトは2秒。接続失敗・不正出力時は既存の通常スタイルへのフォールバックを使う。文章は設定したローカル Ollama に送る。

## 検証・デプロイ

1. `docker compose config --quiet` で設定を検証する。
2. bot コンテナから `/api/version` と `/api/tags` の応答を確認し、`OLLAMA_MODEL` が存在することを確認する。
3. 更新前の Git commit と bot イメージIDを記録する。
4. `docker compose up -d --build --no-deps bot` で bot のみ更新する。
5. bot の warmup と起動を確認し、合成した日本語例文で `infer_style` が候補内のスタイルを返すことを確認する。

## 復旧

更新前の commit から作業ブランチを作り、更新前の接続設定を明示して bot を再ビルド・起動する。または、記録した旧イメージを Compose override の `image` に指定し、`--no-build` で bot のみ再作成する。接続先やモデルを `.env` で変更した場合は、その設定も更新前の値へ戻す。データvolumeの削除は不要。
