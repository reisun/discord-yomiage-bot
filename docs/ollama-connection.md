# Ollama 接続・スタイル判定

## 接続先

bot は Windows ホスト側 Ollama (`http://host.docker.internal:11434`) を直接呼び出す。`OLLAMA_HOST` で接続先を上書きでき、Compose の環境設定も指定値を尊重する。内部プロキシや共有ネットワークへの参加は不要。Ollama 自体は Windows 側で管理し、本プロジェクトの Docker Compose は bot と VOICEVOX のみを起動する。

## Decision API

`OLLAMA_API_MODE=systemone`（既定）で `/v1/systemone` を利用する。Ollama 0.35以降と対応モデルが必要。`OLLAMA_MODEL` 未指定時は `tev1:0.8b`。ボイスが持つスタイル名を `questions.style.criteria` に渡し、文章は `state` に渡す。文章中の指示を実行せず、自然な読み方を選ぶよう指定する。

`answers.style.type=choice` かつ `choice` が候補内の文字列である場合だけ採用する。確率の集中度を表す `confidence` を正解率として扱わず、未検証のしきい値で分岐しない。候補は重複を除いて2〜24件。0件は失敗扱い、1件はAPIを呼ばずそのスタイルを使用し、24件超では通常スタイルに戻す。

自動選択には「ノーマル」も含め、感情のない文章を非ノーマルへ強制しない。明示的に選ばれた話し方は自動判定より優先する。ボイスにスタイルがない場合は既定speakerを使用する。

選択指示は、話者の感情と意図する読み方に最も近い候補を選ぶよう指定し、短文・口語も対象にする。「感情が不明ならノーマル」という指示は設けない。ノーマルは事実説明・通常の情報・感情的に中立な文章として説明する。なみだめには悲しみ・孤独・傷つき・見捨てられた気持ち・落胆、ツンツンには怒り・苛立ち・抗議も含める。ツンツンは怒り専用の音声ではなく、ずんだもんにある候補の中で近い表現として選ばれる。ヒソヒソには秘密の情報共有・ここだけの話を含める。感情を独立分類する二段階方式には変更していない。

通常判定のHTTPタイムアウトは合計0.75秒。通信失敗・不正応答・タイムアウトは `None` を返し、そのボイスのノーマル（なければ先頭スタイル）へ戻す。文字列の生成結果から番号を抽出する処理はDecision APIでは使わない。

## ロード・常駐

起動時は2候補のDecision APIリクエストでモデルをロードする（最大120秒）。`keep_alive=10m` と4分ごとの同APIリクエストで常駐を維持する。初回ロードの速度は通常判定の0.75秒制限と分けて評価する。終了時はkeepalive taskをキャンセルして待機し、HTTP sessionを閉じる。Discord再接続時にkeepalive taskを重複作成しない。

## 従来API・復旧

`OLLAMA_API_MODE=generate` と `OLLAMA_MODEL=qwen3.5:2b` で `/api/generate` を使う。番号生成・ランダムな候補順・モデル別設定は従来方式を維持する。モデル未指定時の既定は `qwen3.5:2b`。

接続失敗時に外部APIや別モデルへ自動送信しない。文章は設定したローカル Ollama に送る。

## 検証・反映

1. Windows側Ollamaで `ollama --version` と `ollama list` を確認する。Tev1は `ollama pull tev1:0.8b` で用意する。
2. `docker compose config --quiet`、READMEのunittestコマンド、`git diff --check` で検証する。
3. bot コンテナから `/api/version` と `/api/tags` に到達し、設定モデルが存在することを確認する。
4. 反映前のcommit・botイメージID・`.env` のモデル/APIモードを記録する。
5. `docker compose up -d --build --no-deps bot` でbotのみ更新する。
6. warmup成功・Bot readyを確認し、合成日本語例文で候補内のスタイルが返ることを確認する。

復旧は `.env` に従来のモデルと `OLLAMA_API_MODE=generate` を指定して `docker compose up -d --no-deps bot`。コード自体の復旧が必要なら、記録した旧イメージをCompose overrideの `image` に指定し `--no-build` で再作成する。旧コードはAPIモード設定を使わないので、旧モデル名も明示する。Windows側モデルやvolumeの削除は不要。

## 比較の再実行

例文は `tests/fixtures/voice_styles.json` の合成文章48件。基本感情6候補24件、実際のずんだもん8スタイル候補24件。各例文を2回、固定seedで文章順と候補順を変更し、全モデルで同じ候補順を使う。期待ラベルは読み方の意図であり、客観的な唯一の正解ではない。

```bash
docker compose run --rm --no-deps -v "$PWD:/app" --user "$(id -u):$(id -g)" bot \
  python scripts/compare_ollama.py \
  --target generate=qwen3.5:2b \
  --target systemone=tev1:4b \
  --target systemone=tev1:0.8b \
  --output docs/benchmarks/ollama-new.json
```

モデルは順次ロードし、warmupを通常判定時間から除外する。全例文に両APIでノーマルを含めるため、ノーマルを除外していた旧botそのものの精度との比較ではない。結果にはfixture hash、モデルdigest、Ollamaバージョン、ロード情報、全判定、グループ別・ラベル別一致率、通常判定のp50/p95/最大応答時間を保存する。未応答は一致率・有効応答率を下げる。

合成例文への一致率は実際のDiscord会話の精度保証ではない。短文、皮肉、複数感情などは別途評価が必要。

参考: [Ollama Decision API](https://docs.ollama.com/capabilities/decision)、[Tev1モデル仕様](https://ollama.com/library/tev1)。
