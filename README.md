# discord-yomiage-bot

Discord テキストチャンネルのメッセージを VOICEVOX で音声合成し、音声チャンネルで読み上げる bot。

## セットアップ

1. `.env.example` を `.env` にコピーし、`DISCORD_TOKEN` を設定
2. ホスト側の Ollama を起動し、使用するモデルを用意する
3. `.env` の `OLLAMA_MODEL` に導入済みモデル名を設定する（未指定時は `qwen3.5:2b`）
4. `docker compose up -d` で起動

## Ollama 接続

bot は Docker Desktop の `http://host.docker.internal:11434` からホスト側の Ollama に直接接続します。`OLLAMA_HOST` を `.env` に設定すると接続先を変更できます。内部プロキシや共有の `llm-network` は不要です。

Ollama の `/api/version` と `/api/tags` に bot コンテナから到達できることを確認してください。Ollama 側は Docker からの接続を受け付ける設定が必要です。モデル未導入や接続失敗時は通常の読み上げスタイルに戻ります。

接続方式・確認・復旧手順は [Ollama 接続設計](docs/ollama-connection.md) を参照してください。

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
