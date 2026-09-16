# Jaloliddin Manguberdi 751M 空席通知

2026年11月10日、BUKHARA → TASHKENT、10:57 → 15:06 の列車だけを、公式e-ticketのJSON APIで5分間隔に監視します。空席数が1以上になった初回と、いったん0に戻って再び1以上になったときに、無料のntfyでiPhoneへ通知します。予約・購入・ログインは行いません。

## 2026年9月16日に確認した公式API

公式サイト `https://eticket.railway.uz/` に対し、次のPOSTを実行してHTTP 200・JSON応答を確認しました。対象日の対象区間で10列車が返り、751Mは列車番号 `751М`（最後のMはキリル文字）、ブランド `Jaloliddin Manguberdi`、出発 `10.11.2026 10:57`、到着 `10.11.2026 15:06`、区間 `BUKHARA` / `TASHKENT` でした。対象列車の `cars` は空配列でした。他列車の `cars[]` には `type`、`freeSeats`、`tariffs[]`、`seatDetail` があり、車両の `freeSeats` と `seatDetail` の座席数が一致しました。

```text
POST https://eticket.railway.uz/api/v3/handbook/trains/list
Content-Type: application/json
Accept: application/json
Accept-Language: en
device-type: BROWSER
Origin: https://eticket.railway.uz
X-XSRF-TOKEN: <実行ごとに生成する値>
Cookie: XSRF-TOKEN=<同じ値>

{"directions":{"forward":{"date":"2026-11-10","depStationCode":"2900800","arvStationCode":"2900000"}}}
```

レスポンスの列車配列は `data.directions.forward.trains[]`、列車番号は `number`、名前は `brand`、時刻は `departureDate` / `arrivalDate`、区間は `subRoute`、空席は各 `cars[].freeSeats` です。`seatDetail` の `undef` / `lateralDn` / `lateralUp` / `down` / `up` の合計も照合します。`freeComp` は空きコンパートメント数で座席数に足しません。`tariffs[].freeSeats` は座席車では車両の席数を分けますが、寝台車では0でも車両の `freeSeats` が正数だったため、購入可能判定の主値には使いません。

未確認の点は、**空席が発生した瞬間の751Mの実レスポンス**と、**GitHub-hosted runnerからのAPI到達性**です。現在の対象列車は `cars: []` だったため、空席が出た際の対象列車の車両型は推測しません。想定外の構造・矛盾した座席数・HTTPエラーなら通知せずUNKNOWN/ERRORで終了します。公式のブラウザ検索はこの調査の未ログインセッションではログインページへ移動しましたが、上記POSTは認証なしで200を返しました。

## 設定手順

1. iPhoneのApp Storeから、オープンソースの **ntfy** アプリをインストールし、通知を許可します。ntfyの無料枠はアカウント作成や支払い方法の登録なしで使えます。[ntfy公式iPhone手順](https://docs.ntfy.sh/subscribe/phone/)
2. 他人に推測されない通知トピックを1個作ります。WindowsのPowerShellを開き、`[guid]::NewGuid().ToString('N')` を実行すると32文字のランダム値が表示されます。この値をコピーします。値はパスワードと同様に扱い、コード、README、Issue、スクリーンショットへ載せないでください。ntfy.shのトピックは名前を知る人なら読んだり投稿したりできる公開チャネルです。
3. ntfyアプリで **＋ → Subscribe to topic** を選び、Serverは `https://ntfy.sh`、Topicに手順2の値を貼り付けて購読します。ntfyアカウントへのログインは不要です。
4. [GitHub](https://github.com/)で無料アカウントを用意し、[New repository](https://github.com/new)で空の**Public** repositoryを作ります。名前は例として `uzbekistan-train-monitor`。README/.gitignoreをGitHub側で自動生成するチェックは外します。GitHub Actionsの標準runnerはPublic repositoryなら無料です。コード、監視対象、状態Issueは公開されますが、手順2のトピックはGitHub Secretに入るため公開されません。[GitHub repository作成手順](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)
5. このフォルダー `uzbekistan-train-monitor` の**中身**を、repositoryのルートにアップロードします。GitHub画面の **Add file → Upload files** で、このフォルダー内のファイルと `.github` フォルダーを一緒にドラッグできます。アップロード後、GitHub上で `.github/workflows/check-train.yml` が存在することを確認してください。[GitHubのアップロード手順](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)
6. Repositoryの **Settings → Secrets and variables → Actions → New repository secret** で、Nameを `NTFY_TOPIC`、Secretを手順2の32文字にして登録します。必要なSecretはこれ1個だけです。`GITHUB_TOKEN` はActionsが自動提供するので登録不要です。[GitHub Secrets手順](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
7. Repositoryの **Settings → General → Features** でIssuesが有効か確認します。監視状態の保存にIssueを1件自動作成します。Repositoryの **Actions** タブでworkflowを有効化します。組織管理のrepositoryではActionsの実行や`issues: write`が制限されていないか管理者に確認してください。
8. **Actions → Check Jaloliddin Manguberdi seats → Run workflow** で `test_mode=true` を選び、手動実行します。iPhoneに「🧪…通知テスト」が**1通**届けば通知設定は成功です。TEST_MODEでは列車APIも本番状態Issueも触りません。同じ手動実行を再度行えば再度テスト通知が届きます。
9. 同じ画面で `test_mode=false` を手動実行し、ログに対象列車と現在の空席数、`result=UNAVAILABLE` が出ることを確認します。これで本番監視開始です。その後の定期実行はGitHub側だけで継続し、PCやiPhoneがOFFでも監視を実行します。iPhoneは通知を受けるため通信できる状態が必要です。Public repositoryのscheduleは60日間repository活動がないと停止しますが、2026年9月16日から対象出発までは60日未満です。念のため10月中にActions画面で直近の定期実行を確認してください。

### Publicにしたくない場合

Private repositoryのGitHub Free枠は月2,000分で、各jobの課金時間は分単位に切り上げられます。5分間隔では無料枠を超えます。完全無料のままPrivateにするなら `.github/workflows/check-train.yml` のcronを `2-59/5 * * * *` から `2,32 * * * *` に変え、30分間隔にしてください。月約1,440回なので、ほかのActionsを大量に使わなければ2,000分枠内に収まります。検知速度を優先する場合はPublicの5分監視を使います。[GitHub Actions料金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

## 通知と状態保存

GitHub Actionsは各実行で環境が消えるため、前回の**確定した** `AVAILABLE` / `UNAVAILABLE` を、repository内の `[train-monitor-state] 2026-11-10 751M` という単一Issueの本文に保存します。Issueは自動作成され、以後は**状態が変わった場合のみ**更新されます。Git commit/pushはありません。`UNKNOWN` / `ERROR` は状態を書き換えません。前回の確定状態がまだなければ、途中でエラーがあっても次の最初の確定AVAILABLEは「初回空席」として通知します。エラーをUNAVAILABLEと見なすことはありません。ntfy送信が失敗すれば状態をAVAILABLEに進めず、次回の確認で再試行します。送信成功後にGitHubへの状態保存だけが失敗した場合は、次回に重複通知する可能性が残ります。この2サービス間に単一の原子的な保存方法がないためです。

Cacheは[未使用時の削除や容量による退避](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)があり永続DBではありません。Artifactは保持期限があり、毎回新しい履歴を生成します。単一Issueは小さな状態を永続化でき、`GITHUB_TOKEN` の `issues: write` のみで運用できます。[GitHub Issue API](https://docs.github.com/en/rest/issues/issues)

通知のタイトルと本文は `notifier.py` で組み立てます。ntfy通知には公式サイトを開くclick URLを付けています。ntfyの無料サービスは1日250メッセージまでで、この監視は状態変化時と手動テスト時しか送信しないため十分余裕があります。[ntfyの制限](https://docs.ntfy.sh/publish/#limitations) 将来Discord等に変更する場合は `notifier.py` の送信関数を差し替えます。以前のPushover送信関数も残してありますが、標準workflowはntfyを使用します。

## 動作と障害時

5分cronはGitHubの最短間隔ですが、[実行遅延・取りこぼしがあり得ます](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)。各チェックの公式APIへのリクエストは1回で、再試行はしません。HTTP timeoutは接続5秒・応答20秒です。403、429、500系、DNS、タイムアウト、JSON不正、対象列車なし、駅コードや列車時刻の不一致、空席フィールド欠落はいずれも通知しません。失敗したworkflowのログを見てください。レスポンス全文・Cookie・`NTFY_TOPIC`はログにもArtifactにも保存しません。UNKNOWNでJSON構造の確認が必要な場合だけ、キー名と型だけの `api-schema-<run_id>` Artifactを7日保存します。

現地時間 `Asia/Tashkent` の **2026年11月10日10:57以降**は `EXPIRED` としてAPIにアクセスせず正常終了します。不要になればActionsのworkflowを無効化できます。

ローカルでテストする場合はPython 3.12以降で `python -m pip install -r requirements.txt`、`python -m pytest -q` を実行します。Secretをローカルファイルに書かないでください。
