; Дополнительные шаги установщика Shelter (NSIS-хуки Tauri)

!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $UpdateMode <> 1
  ; Автозапуск — чтобы не осталось записи на удалённый файл.
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Jarvis"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" "Jarvis"

  ; Скачанное мастером — Python, библиотеки, модели, журналы: это гигабайты,
  ; и установщик сам о них не знает.
  RMDir /r "$INSTDIR\core\runtime"
  RMDir /r "$INSTDIR\core\models"
  RMDir /r "$INSTDIR\core\logs"
  RMDir /r "$INSTDIR\core\__pycache__"

  ; Личное — настройки, память, напоминания — только по галочке «Удалить данные».
  ${If} $DeleteAppDataCheckboxState = 1
    RMDir /r "$INSTDIR\core\data"
  ${EndIf}
  RMDir "$INSTDIR\core"
  ${EndIf}
!macroend
