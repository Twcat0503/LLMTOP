# 發佈準備與公開檔案

0.1.0 是未發佈的 alpha 基礎版本，尚無官方 repository／套件來源。本機 Git 基礎不等同公開發布；尚未建立 remote、版本 tag 或公開 release。

2026-10-04 收尾核對：程式檔案與先前 Linux VM 的驗證清單一致，既有 wheel／sdist 校驗值吻合；本次遠端 SSH 非互動認證失敗，沒有重新執行 runtime 測試或建置。既有 archives 早於本次文件／Git 修訂，不可作為新 commit 的發布資產。當前阻擋條件見 [TODO](TODO.md)。

## 公開範圍

Git 收錄正式程式、合成／去敏 fixtures、固定依賴、通用文件、MIT 與 CI。.gitattributes 固定文字檔為 LF，sdist 白名單亦包含此規則，避免跨平台 checkout 改變來源位元組。私人原型、工作站 AGENTS、內部環境／原型盤點／完整驗收、真實設定、金鑰、raw telemetry、cache／venv／產物保持 ignore。sdist 使用明確目錄與排除規則；wheel 僅包含 runtime、初始化設定與已建置 Web。

`scripts/check_release.py` 檢查 Git 候選來源、相對文件連結、版本一致性與指定 wheel／sdist。維護者可在被忽略的 `.release-private-patterns` 放入每行一個私人字串；檢查只列檔名與規則，不顯示匹配值。不要提交此檔案。

Git ignore 不會移除已追蹤內容；若已在 index／歷史中，先停止發佈並移出 index，曾洩漏的憑證需另外處理。圖片與第三方授權仍需人工審閱。

## 建置與驗證

在已確認且資源足夠的 Linux／macOS 執行；可另指定所有 cache、TMPDIR 與 installer 目錄。

```sh
uv sync --locked --extra dev
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
uv run python scripts/check_release.py
cd frontend
npm ci --no-audit --no-fund
npm run build
cd ..
uv build
uv run python scripts/check_release.py \
  --wheel dist/llmtop-0.1.0-py3-none-any.whl \
  --sdist dist/llmtop-0.1.0.tar.gz
uv export --locked --no-dev --no-emit-project --no-hashes \
  --output-file dist/dependency-constraints.txt
python3 scripts/install_user.py \
  --wheel dist/llmtop-0.1.0-py3-none-any.whl \
  --constraints dist/dependency-constraints.txt \
  --ensure-path
```

在隔離使用者環境驗證 init、不同目錄的 doctor／once、裸指令 TUI、非 TTY、Web／headless／browser failure 與安裝包 Web 靜態檔。Browser tests 先啟動 serve --demo，再在 frontend 執行 Playwright。合成／idle 結果不代表真實非零負載。

從 sdist 重建 wheel 時，先建置其中的 frontend。Python／Web 應使用同一來源，檢查 metadata、CLI、API 與 frontend manifest 版本一致，記錄來源清單與 SHA-256。

## 首次發佈 gate

- [x] 建立本機 Git 基礎與 LF 規則；私人原型及操作紀錄保持排除。
- [ ] 正式 repository、維護者聯絡與私密回報；更新 package URLs／SECURITY。
- [ ] 確認貢獻／資產可按 MIT 發佈，保留第三方必要授權。
- [ ] 同一來源完成測試、build、wheel／sdist 審查及全新安裝。
- [ ] 實際 portable CI；未測 OS／硬體明確標示。
- [ ] 文件、fixtures、圖片不含私人資訊，產物不入 Git。
- [ ] 維護者確認後建立 tag、release assets 與校驗值。

## 發布順序與完成證據

1. 維護者確認正式 repository URL、公開權利、私密回報與套件來源；再設定 remote，更新 package URLs 與 SECURITY。不要將任意同名 PyPI 套件當成官方來源。
2. 在指定 Linux 測試環境，以乾淨 commit 的來源重新測試、建置、審查及全新安裝；保留命令、退出碼、OS／工具版本、commit 與資產 SHA-256。
3. 推送同一來源，確認 Linux／macOS、Python 3.11／3.14 CI 全部成功。CI 不替代 llama.cpp／macOS 硬體等實機 gate；alpha release notes 必須列出未驗證範圍。
4. 維護者確認後，在該 commit 建立 `v0.1.0` tag 與標為 prerelease 的 GitHub Release，附 wheel、sdist、dependency constraints 與 `SHA256SUMS`。校驗檔須包含所有實際提供下載的資產，不能重用舊來源的包。
5. 核對遠端 tag 指向、release 的 prerelease 狀態、下載檔案及校驗值，記錄 CI run 與 release URL；再更新 README、CHANGELOG 與 TODO 的發布狀態。PyPI 上傳另需確認帳號／專案所有權與發布授權。

未完成上述證據前，版本保持未發佈，不因本機 commit／tag 或已有 wheel 就宣告完成。

U05／U06 待基礎版本與官方來源完成後實作；目前 installer 僅接受明確提供的 wheel。
