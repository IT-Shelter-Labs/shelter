package ru.jarvis.assistant

import android.speech.tts.TextToSpeech
import java.util.Locale

internal fun TextToSpeech.configureVoice(tag: String, localOnly: Boolean): Boolean {
    val locale = Locale.forLanguageTag(tag)
    if (!localOnly) return setLanguage(locale) >= 0
    val voice = voices.orEmpty().filter {
        !it.isNetworkConnectionRequired && it.locale.language == locale.language &&
            TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED !in it.features
    }.maxWithOrNull(compareBy({ it.locale == locale }, { it.quality })) ?: return false
    return setVoice(voice) == TextToSpeech.SUCCESS
}
