package ru.jarvis.assistant

import android.content.Context
import org.json.JSONObject

internal class MobileLabels(context: Context) {
    private val app = context.applicationContext
    private val settings = app.getSharedPreferences("settings", Context.MODE_PRIVATE)
    private val english by lazy { app.assets.open("english.json").bufferedReader().use { JSONObject(it.readText()) } }
    val isEnglish get() = settings.getString("ui_language", "ru") == "en"

    fun text(value: String): String {
        if (!isEnglish) return value
        if (english.has(value)) return english.getString(value)
        val tail = value.substringAfter(" · ", "")
        return when {
            value.startsWith("Загрузка · ") -> "Downloading · $tail"
            value.startsWith("Нет связи с ПК · ") -> "Computer unavailable · ${text(tail)}"
            value.startsWith("Не удалось ответить: ") -> "Could not reply: ${text(value.substringAfter(": "))}"
            value.startsWith("Распознавание недоступно (код ") ->
                "Speech recognition is unavailable (code ${value.substringAfter("(код ").substringBefore(')')}). You can type instead."
            value.startsWith("Фраза слишком длинная для выбранного режима: максимум ") ->
                "Message is too long for this mode (${value.substringAfter("максимум ").substringBefore(' ')} characters maximum)."
            value.startsWith("Сервер модели ответил кодом ") -> "Model server returned HTTP ${value.substringAfterLast(' ')}"
            value.startsWith("Сервер ответил: ") -> "Server returned HTTP ${value.substringAfterLast(' ')}"
            value.startsWith("Громкость — ") -> "Volume: ${value.substringAfter("— ").substringBefore(' ')}%."
            else -> value
        }
    }
}
