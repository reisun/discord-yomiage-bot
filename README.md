# discord-yomiage-bot

Discord テキストチャンネルのメッセージを VOICEVOX で音声合成し、音声チャンネルで読み上げる bot。

## セットアップ

1. `.env.example` を `.env` にコピーし、`DISCORD_TOKEN` を設定
2. `docker compose up -d` で起動

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
