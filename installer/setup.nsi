; kasugai_qgis NSIS インストーラースクリプト
; 本体 qgis_launcher.exe と動作に必要なファイル一式をインストール/更新
; 使い方: release ビルド後、 makensis.exe setup.nsi でコンパイル
;
; 2種類のインストーラーを生成できる:
;   全体版   : makensis.exe setup.nsi
;              → kasugai_qgis-setup.exe (EXE + ini/profiles/ProjectFiles 等のデータ一式)
;              初期インストールおよび「全体更新」用
;   EXEのみ版: makensis.exe /DUPDATE_ONLY setup.nsi
;              → kasugai_qgis-update.exe (EXE 本体のみ、データは触らない)
;              通常のバージョンアップ(自動更新)用

!define PRODUCT_NAME "kasugai_qgis"
!define PRODUCT_VERSION "2.0.3"
!define PRODUCT_PUBLISHER "yamamoto-ryuzo"
!define PRODUCT_DIR "kasugai_qgis"

; 現代風 UI
!include "MUI2.nsh"
!include "LogicLib.nsh"

; 基本情報
!ifdef UPDATE_ONLY
Name "${PRODUCT_NAME} ${PRODUCT_VERSION} (本体更新)"
OutFile "..\public\kasugai_qgis-update.exe"
!else
Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "..\public\kasugai_qgis-setup.exe"
!endif
InstallDir "$PROFILE\kasugai\${PRODUCT_DIR}"
RequestExecutionLevel user

; 圧縮設定（プロファイル・プラグインを含めるため LZMA/SOLID）
SetCompressor /SOLID lzma

; UI 設定
!define MUI_ABORTWARNING
!define MUI_ICON "app_icon.ico"
!define MUI_UNICON "app_icon.ico"

; ページ
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

; 完了ページのチェックボックス設定
!define MUI_FINISHPAGE_TITLE "kasugai セットアップの完了"
!define MUI_FINISHPAGE_TEXT "kasugai は、このコンピュータにインストールされました。$\r$\n「完了」をクリックしてセットアップを閉じます。"
!define MUI_FINISHPAGE_TEXT_LARGE
!define MUI_FINISHPAGE_RUN "$INSTDIR\qgis_launcher.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "--open-browser"
!define MUI_FINISHPAGE_RUN_TEXT "kasugai を実行(R)"
!define MUI_FINISHPAGE_RUN_CHECKED
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "デスクトップショートカットを作成する"
!define MUI_FINISHPAGE_SHOWREADME_CHECKED
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION CreateDesktopShortcut
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_LANGUAGE "Japanese"

; 強制上書き
SetOverwrite on

Section "MainSection" SecMain
  SetOutPath "$INSTDIR"

  ; 実行中の qgis_launcher.exe を .old にリネームしてから上書き
  ; （Rust 側で起動前に終了しているはずだが、二重起動等に備える）
  ${If} ${FileExists} "$INSTDIR\qgis_launcher.exe"
    Delete "$INSTDIR\qgis_launcher.exe.old"
    Rename "$INSTDIR\qgis_launcher.exe" "$INSTDIR\qgis_launcher.exe.old"
  ${EndIf}

  ; 本体実行ファイル
  File "..\target\release\qgis_launcher.exe"

!ifndef UPDATE_ONLY
  ; ===== 以下は全体版のみ: データ一式の配置 =====

  ; qgis_settings.json は初回のみ配置（ユーザー設定を上書きしない）
  ${If} ${FileExists} "$INSTDIR\qgis_settings.json"
    ; 既存設定あり：上書きしない
  ${Else}
    File "..\download\qgis_settings.json"
  ${EndIf}

  ; ユーザーロール制御用 ini フォルダ
  SetOutPath "$INSTDIR\ini"
  File /r "..\download\ini\*.*"

  ; 配布プロファイル
  SetOutPath "$INSTDIR\profiles"
  File /r "..\download\profiles\*.*"

  ; サンプルプロジェクト
  SetOutPath "$INSTDIR\ProjectFiles"
  File /r "..\download\ProjectFiles\*.*"

  ; 設定例ファイル
  SetOutPath "$INSTDIR"
  File "..\download\qgislocalsync.config.example"
  File "..\download\qgis_settings_override.json.example"
  File "..\download\qgis_settings_USERNAME.json.example"
  File "app_icon.ico"

  ; スタートメニューショートカット
  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortcut "$SMPROGRAMS\${PRODUCT_NAME}\kasugai_qgis.lnk" "$INSTDIR\qgis_launcher.exe" "--open-browser" "$INSTDIR\qgis_launcher.exe" 0 SW_SHOWNORMAL "" "" "$INSTDIR"
!endif

  ; 古いバックアップを削除
  Delete "$INSTDIR\qgis_launcher.exe.old"

!ifndef UPDATE_ONLY
  ; アンインストーラー作成
  WriteUninstaller "$INSTDIR\uninstall.exe"
!endif
SectionEnd

; サイレントインストール完了後は本体を自動起動
; サイレント実行＝本体の自動更新から呼ばれたケース。
; 起動直後にまた更新チェックが走ると「更新→再起動→更新」の無限ループになりうるため、
; --no-update-check を必ず付けて起動する。
Function .onInstSuccess
  ${If} ${Silent}
    Exec '"$INSTDIR\qgis_launcher.exe" --open-browser --no-update-check'
  ${EndIf}
FunctionEnd

; サイレントインストール時の /D 対応
Function .onInit
  ${If} $INSTDIR == ""
    StrCpy $INSTDIR "$PROFILE\kasugai\${PRODUCT_DIR}"
  ${EndIf}

  ; 既に管理者権限で実行されている場合は権限チェック不要
  UserInfo::GetAccountType
  Pop $0
  ${If} $0 == "Admin"
    Return
  ${EndIf}

  ; インストール先への書き込み権限を確認
  CreateDirectory "$INSTDIR"
  FileOpen $0 "$INSTDIR\__write_test__.tmp" w
  ${If} $0 == ""
    ; 書き込み権限がないので管理者権限で再起動
    MessageBox MB_OK|MB_ICONINFORMATION "インストール先フォルダに書き込む権限が必要なため、管理者権限で再起動します。"
    ExecShell "runas" "$EXEDIR\$EXEFILE" "$CMDLINE"
    Quit
  ${EndIf}
  FileClose $0
  Delete "$INSTDIR\__write_test__.tmp"
FunctionEnd

; 完了ページの「デスクトップショートカットを作成する」チェックボックスが選択されたときの処理
Function CreateDesktopShortcut
  CreateShortcut "$DESKTOP\kasugai_qgis.lnk" "$INSTDIR\qgis_launcher.exe" "--open-browser" "$INSTDIR\qgis_launcher.exe" 0 SW_SHOWNORMAL "" "" "$INSTDIR"
FunctionEnd

; アンインストール（全体版のみ）
!ifndef UPDATE_ONLY
Section "Uninstall"
  Delete "$INSTDIR\qgis_launcher.exe"
  Delete "$INSTDIR\qgis_launcher.exe.old"
  Delete "$INSTDIR\qgis_settings.json"
  Delete "$INSTDIR\uninstall.exe"
  Delete "$INSTDIR\qgislocalsync.config.example"
  Delete "$INSTDIR\qgis_settings_override.json.example"
  Delete "$INSTDIR\qgis_settings_USERNAME.json.example"
  Delete "$INSTDIR\app_icon.ico"
  RMDir /r "$INSTDIR\ini"
  RMDir /r "$INSTDIR\profiles"
  RMDir /r "$INSTDIR\ProjectFiles"
  Delete "$DESKTOP\kasugai_qgis.lnk"
  RMDir /r "$SMPROGRAMS\${PRODUCT_NAME}"
  RMDir "$INSTDIR"
SectionEnd
!endif
