package ru.jarvis.assistant

import android.content.Context
import com.google.ai.edge.litertlm.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

class LocalEngine(private val context: Context) {
    private val gate = Mutex()
    private var engine: Engine? = null
    private var model = ""
    @Volatile private var conversation: Conversation? = null
    private fun open(path: String, maxTokens: Int): Engine {
        Engine.setNativeMinLogSeverity(LogSeverity.ERROR)
        val next = Engine(EngineConfig(modelPath = path, backend = Backend.CPU(), maxNumTokens = maxTokens, cacheDir = context.cacheDir.absolutePath))
        try { next.initialize(); return next } catch (error: Throwable) { next.close(); throw error }
    }
    suspend fun validate(path: String, maxTokens: Int) = withContext(Dispatchers.IO) {
        gate.withLock { open(path, maxTokens).close() }
    }
    suspend fun reply(path: String, system: String, history: List<ChatLine>, text: String, maxTokens: Int = 8192, onChunk: (String) -> Unit) = withContext(Dispatchers.IO) {
        gate.withLock {
            if (model != path || engine == null) {
                engine?.close()
                engine = null
                model = ""
                engine = open(path, maxTokens)
                model = path
            }
            val config = ConversationConfig(systemInstruction = Contents.of(system),
                initialMessages = history.map { if (it.role == "user") Message.user(it.text) else Message.model(it.text) },
                maxOutputToken = 256, thinkingConfig = ThinkingConfig(enableThinking = false, thinkingTokenBudget = 0), automaticToolCalling = false)
            engine!!.createConversation(config).use { active ->
                conversation = active
                try { active.sendMessageAsync(text).collect { chunk ->
                    onChunk(chunk.contents.contents.filterIsInstance<Content.Text>().joinToString("") { it.text })
                } }
                finally { conversation = null }
            }
        }
    }
    fun cancel() { runCatching { conversation?.cancelProcess() } }
    suspend fun close() = withContext(Dispatchers.IO) { cancel(); gate.withLock { engine?.close(); engine = null; model = "" } }
}
