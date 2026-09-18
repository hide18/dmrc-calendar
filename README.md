# dmrc-calendar

ドラマチックレコード（ドマレコ）の TimeTree 公開カレンダーを取得し、iPhone などで照会できる `.ics` を [GitHub Pages](https://hide18.github.io/dmrc-calendar/) で配信するリポジトリです。

- ICS: https://hide18.github.io/dmrc-calendar/dmrc_schedule.ics
- 更新: GitHub Actions が 6 時間ごとに TimeTree から再取得して Pages にデプロイ

## ワンタイムセットアップ（以降は手作業不要）

GitHub は **約 60 日間リポジトリにアクティビティがないと**、`schedule` ワークフローを `disabled_inactivity` で自動停止します。  
`GITHUB_TOKEN` による commit はアクティビティにカウントされないため、**自分の PAT で毎月 keepalive commit** する仕組みを入れています。

### 1. Fine-grained PAT を作る

1. https://github.com/settings/personal-access-tokens を開く
2. **Generate new token**（Fine-grained）
3. 設定例:
   - Token name: `dmrc-calendar-keepalive`
   - Expiration: **No expiration**（または 1 年。期限切れ時は Issue で通知されます）
   - Resource owner: 自分
   - Repository access: **Only select repositories** → `dmrc-calendar`
   - Permissions → Repository permissions:
     - **Contents**: Read and write
     - **Workflows**: Read and write（任意。手動再実行用）
4. 生成したトークン文字列を控える

### 2. リポジトリに Secret を登録

1. https://github.com/hide18/dmrc-calendar/settings/secrets/actions
2. **New repository secret**
   - Name: `KEEPALIVE_PAT`
   - Value: さきほどのトークン

### 3. 止まっている Workflow を有効化（初回・停止後のみ）

1. [Update DMRC Calendar](https://github.com/hide18/dmrc-calendar/actions/workflows/update-calendar.yml) → **Enable workflow** → **Run workflow**
2. [Keepalive](https://github.com/hide18/dmrc-calendar/actions/workflows/keepalive.yml) → **Enable workflow** → **Run workflow**

これ以降は通常、追加操作は不要です。

## 障害時の通知（メール + 許可リンク）

`KEEPALIVE_PAT` 未設定・期限切れ・push 失敗などで keepalive が落ちると、リポジトリに Issue が自動作成（または追記）されます。

- GitHub の通知設定が有効なら **メールが届きます**
- Issue 内のリンクから **Enable workflow / Run workflow**（許可ボタン相当）と Secret 更新ができます

## ワークフロー構成

| Workflow | 役割 |
|----------|------|
| `update-calendar.yml` | 6 時間ごと / 手動 / コード push で ICS 再生成 → Pages デプロイ |
| `keepalive.yml` | 毎月1日 / 手動で PAT による活性維持 commit |

## ローカル実行

```bash
pip install -r requirements.txt
playwright install chromium
python fetch_and_generate.py
```

生成物は `dist/` に出力されます。
