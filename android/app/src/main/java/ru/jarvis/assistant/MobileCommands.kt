package ru.jarvis.assistant

import android.content.Context
import android.media.AudioManager
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

internal class MobileCommands(context: Context, private val history: History) {
    private val audio = context.getSystemService(AudioManager::class.java)
    private val remember = Regex("^(?:запомни|remember)(?:[, :]+(.*))?$", RegexOption.IGNORE_CASE)
    private val volume = Regex("(?:громкость(?: на)?|volume(?: to)?) (\\d{1,3})(?: процентов|%)?")

    fun answer(question: String): String? {
        val query = question.lowercase().replace('ё', 'е').trim().trimEnd('.', '?', '!')
        val english = query.none { it in 'а'..'я' }
        val locale = Locale.forLanguageTag(if (english) "en-US" else "ru-RU")
        remember.matchEntire(question.trim())?.let {
            val fact = it.groupValues[1].replace(Regex("^(?:что|that)\\s+", RegexOption.IGNORE_CASE), "").trim()
            if (fact.isBlank()) return if (english) "What should I remember?" else "Что именно запомнить?"
            history.remember(fact)
            return if (english) "Saved." else "Запомнил."
        }
        if (query in setOf("что ты помнишь", "что ты обо мне знаешь", "what do you remember")) {
            return history.facts().joinToString("\n") { it.second }.ifBlank {
                if (english) "There are no saved facts yet." else "Пока нет сохранённых фактов."
            }
        }
        val format = when (query) {
            "который час", "сколько времени", "время", "what time is it" -> "HH:mm"
            "какая сегодня дата", "какое сегодня число", "what is today’s date", "what is today's date" -> "d MMMM yyyy"
            else -> null
        }
        if (format != null) return SimpleDateFormat(format, locale).format(Date())
        volume.matchEntire(query)?.let {
            val percent = it.groupValues[1].toInt().coerceIn(0, 100)
            audio.setStreamVolume(AudioManager.STREAM_MUSIC, audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC) * percent / 100, 0)
            return if (english) "Volume: $percent%." else "Громкость — $percent процентов."
        }
        return null
    }
}
