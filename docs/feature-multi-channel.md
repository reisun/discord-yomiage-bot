# 複数チャンネル同時読み上げ（案）

ステータス: 構想段階

## 背景

Discordのbotは1サーバーにつき1つの音声チャンネルにしか接続できない。
同一サーバーで複数の音声チャンネルを同時に読み上げるには、複数のbotが必要になる。

## 方針

- スラッシュコマンドの窓口はメインbot1つに集約する
- メインbotが既に音声チャンネルに接続中の場合、サブbotに委任する
- ユーザーから見た操作は `/yo_join` のみで変わらない

## コンテナ構成

```
voicevox-engine（共有）
  ├── bot-main（メインbot）
  └── bot-sub（サブbot）
```

- サブは別コンテナ・別Discordトークンで運用
- VOICEVOXエンジンはHTTP APIなので1コンテナをメイン・サブで共有可能
- 起動順の依存関係はなし（両方ともvoicevox-engineにのみ依存）

## メイン→サブの連携

サブbotはDiscord Gatewayに接続済みのbot。
discord.pyのbotは起動時点で参加済みギルドの情報を全て持っているため、
Discordイベント以外のトリガー（HTTP、Redis等）からでも音声チャンネルへの接続が可能。

連携方法の候補:
- サブbot内に軽量HTTPエンドポイントを追加（aiohttp等）
- Redis Pub/Sub

いずれもdiscord.pyのasyncioイベントループ上で並行起動できる。

## 動作フロー

1. ユーザーが `/yo_join` を実行
2. メインbotがそのギルドで音声チャンネルに未接続 → メインが接続
3. メインbotが既に別の音声チャンネルに接続中 → サブbotに指示を送信
4. サブbotが指定の音声チャンネルに接続し、読み上げを担当

## docker-compose イメージ

```yaml
services:
  voicevox-engine:
    image: voicevox/voicevox_engine:cpu-ubuntu20.04-latest
  bot-main:
    build: .
    env_file: .env.main
    depends_on: [voicevox-engine]
  bot-sub:
    build: .
    env_file: .env.sub
    depends_on: [voicevox-engine]
```

## 未決事項

- サブbotのスケーリング（サブ1台で足りるか、複数台にするか）
- メイン・サブ間の通信方式の選定
- サブbotのコードをメインと共有する範囲（指示受け口の差分のみにできるか）
- サブbot側の読み上げ対象テキストチャンネルの管理
