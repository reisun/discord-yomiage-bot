# discord-yomiage-bot

Discord テキストチャンネルのメッセージを VOICEVOX で音声合成し、音声チャンネルで読み上げる bot。

## セットアップ

1. `.env.example` を `.env` にコピーし、`DISCORD_TOKEN` を設定
2. ホスト側の Ollama を起動し、使用するモデルを用意する
3. Ollama 0.35以降で `ollama pull tev1:0.8b` を実行し、`.env` の `OLLAMA_API_MODE=systemone` と `OLLAMA_MODEL=tev1:0.8b` を設定する
4. `docker compose up -d --build` で起動

## Ollama 接続

bot は Docker Desktop の `http://host.docker.internal:11434` からホスト側の Ollama に直接接続します。`OLLAMA_HOST` を `.env` に設定すると接続先を変更できます。内部プロキシや共有の `llm-network` は不要です。

Ollama の `/api/version` と `/api/tags` に bot コンテナから到達できることを確認してください。Ollama 側は Docker からの接続を受け付ける設定が必要です。自動判定では `/v1/systemone` に「ノーマル」を含むスタイル候補を渡し、候補内の回答だけを採用します。モデル未導入、接続失敗、不正出力、0.75秒タイムアウト時は通常の読み上げスタイルに戻ります。ユーザーが明示したスタイルは優先します。

従来の Qwen を使う場合は `OLLAMA_API_MODE=generate` と `OLLAMA_MODEL=qwen3.5:2b` を設定すると `/api/generate` に切り替わります。`OLLAMA_MODEL` 未指定時は、`systemone` では `tev1:0.8b`、`generate` では `qwen3.5:2b` を使います。

接続方式・確認・復旧手順は [Ollama 接続設計](docs/ollama-connection.md) を参照してください。

## 検証

```bash
docker compose config --quiet
docker compose build bot
docker compose run --rm --no-deps -v "$PWD:/app:ro" bot python -m unittest discover -s tests -v
```

比較は [Ollama 接続設計](docs/ollama-connection.md) のコマンドで再実行できます。[比較結果](docs/ollama-comparison.md) に採用理由を記載しています。

## コマンド

| コマンド | 説明 |
|---------|------|
| `/yo_join` | 音声チャンネルに参加して読み上げ開始 |
| `/yo_leave` | 音声チャンネルから退出 |
| `/yo_voice <ボイス名> <話し方>` | 自分の読み上げボイスを変更（オートコンプリート対応） |
| `/yo_speakers` | 利用可能なボイス一覧を表示 |

## デフォルトボイス

全ユーザー共通でずんだもん（`/yo_voice` で個別に変更可能）

## クレジット

- 音声合成: [VOICEVOX](https://voicevox.hiroshiba.jp/)
- VOICEVOX: ずんだもん
