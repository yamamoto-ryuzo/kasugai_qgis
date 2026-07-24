; kasugai_qgis NSIS インストーラースクリプト
; 本体（qgis_launcher.exe）のみをインストール/更新する軽量セットアップ
; 使い方: release ビルド後、 makensis.exe setup.nsi でコンパイル

!define PRODUCT_NAME "kasugai_qgis"
!define PRODUCT_VERSION "1.4.0"
!define PRODUCT_PUBLISHER "yamamoto-ryuzo"
!define PRODUCT_DIR "kasugai_qgis"

; 現代風 UI
!include "MUI2.nsh"
!include "LogicLib.nsh"

; 基本情報
Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "..\download\kasugai_qgis_${PRODUCT_VERSION}_x64-setup.exe"
InstallDir "C:\Kasugai\${PRODUCT_DIR}"
RequestExecutionLevel admin

; UI 設定
!define MUI_ABORTWARNING
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"

; ページ
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
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

  ; qgis_settings.json は初回のみ配置（ユーザー設定を上書きしない）
  ${If} ${FileExists} "$INSTDIR\qgis_settings.json"
    ; 既存設定あり：上書きしない
  ${Else}
    File "..\download\qgis_settings.json"
  ${EndIf}

  ; インストール情報をレジストリに記録
  WriteRegStr HKLM "Software\${PRODUCT_NAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\${PRODUCT_NAME}" "Version" "${PRODUCT_VERSION}"

  ; スタートメニューショートカット
  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortcut "$SMPROGRAMS\${PRODUCT_NAME}\kasugai_qgis.lnk" "$INSTDIR\qgis_launcher.exe"

  ; 古いバックアップを削除
  Delete "$INSTDIR\qgis_launcher.exe.old"

  ; アンインストーラー作成
  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

; サイレントインストール時の /D 対応
Function .onInit
  ${If} $INSTDIR == ""
    StrCpy $INSTDIR "C:\Kasugai\${PRODUCT_DIR}"
  ${EndIf}
FunctionEnd

; アンインストール
Section "Uninstall"
  Delete "$INSTDIR\qgis_launcher.exe"
  Delete "$INSTDIR\qgis_launcher.exe.old"
  Delete "$INSTDIR\qgis_settings.json"
  Delete "$INSTDIR\uninstall.exe"
  RMDir /r "$SMPROGRAMS\${PRODUCT_NAME}"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "Software\${PRODUCT_NAME}"
SectionEnd
