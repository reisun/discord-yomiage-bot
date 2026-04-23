# TASK.md

## 現在のステータス: 初期実装完了

### 完了済み
- [x] VOICEVOX APIクライアント実装
- [x] 読み上げCog実装（/yo_join, /yo_leave, /yo_voice, /yo_speakers）
- [x] テキストサニタイズ（URL, メンション, 絵文字, コードブロック, ネタバレ）
- [x] 読み上げキュー（順番再生）
- [x] Docker Compose構成（bot + voicevox-engine）
- [x] ユーザー別ボイス設定（デフォルトずんだもん、/yo_voiceで個別変更）
- [x] /yo_voice オートコンプリート（ボイス名 + 話し方の選択式）
- [x] /yo_speakers ボイス別グループ表示
- [x] ギルド同期（即時反映）

### 今後の拡張候補
- [ ] 辞書登録（読み方カスタマイズ） — 据え置き
- [ ] 複数チャンネル同時読み上げ — 構想段階。[設計メモ](docs/feature-multi-channel.md)
- [ ] AquesTalk1（ゆっくりボイス）対応
  - 個人非営利なら無料利用可。2011年1月以前のライセンスは商用含め完全無料
  - Linux共有ライブラリ（.so）を Python ctypes で呼び出す方式
  - VOICEVOX と共存させ /yo_voice で切り替え可能にする
  - HTTP APIではなくC言語ライブラリ直接呼び出しのため実装コストはやや高い
