package ru.jarvis.assistant

import android.content.Context

class LocalEngine(context: Context) {
    suspend fun validate(path: String, maxTokens: Int) { error("Для модели нужна сборка Shelter Local.") }
    suspend fun reply(path: String, system: String, history: List<ChatLine>, text: String, maxTokens: Int = 8192, onChunk: (String) -> Unit) {
        error("Для модели на устройстве нужна сборка Shelter Local и Android 12+. Эта лёгкая сборка работает с ПК и облаком; локальные команды доступны без модели.")
    }
    fun cancel() {}
    suspend fun close() {}
}
