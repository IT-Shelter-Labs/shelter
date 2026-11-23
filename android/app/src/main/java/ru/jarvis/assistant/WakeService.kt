package ru.jarvis.assistant

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import java.util.UUID

class WakeService : Service() {
    companion object {
        private const val CHANNEL = "jarvis_microphone"
        private const val NOTIFICATION = 21
        private const val STOP = "ru.jarvis.assistant.STOP_WAKE"
        const val SHOW_COMPANION = "ru.jarvis.assistant.SHOW_COMPANION"
        const val WAITING = "Жду «Слушай, помощник»"
        private val mutableStatus = MutableStateFlow("")
        val status = mutableStatus.asStateFlow()
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val chat by lazy { MobileChat(applicationContext) }
    private val db by lazy { History(applicationContext) }
    private val commands by lazy { MobileCommands(applicationContext, db) }
    private val labels by lazy { MobileLabels(applicationContext) }
    private val overlay by lazy { CompanionOverlay(this) }
    private val noticePortrait by lazy { android.graphics.BitmapFactory.decodeResource(resources, R.drawable.pippa_portrait) }
    private val pc = Transport()
    private val sound = PcAudio()
    private var listening: Job? = null
    @Volatile private var record: AudioRecord? = null
    private var tts: TextToSpeech? = null
    private val ttsReady = CompletableDeferred<Boolean>()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        scope.launch {
            status.combine(CompanionOverlay.activityVisible) { message, _ -> message }.collect { message ->
                overlay.update(when (message) {
                    "Скажите просьбу" -> "Слушаю"
                    "Обрабатываю просьбу…" -> "Готовлю ответ"
                    "Озвучиваю ответ…" -> "Отвечаю"
                    else -> null
                })
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, id: Int): Int {
        if (intent?.action == STOP || checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (listening?.isActive == true) return START_NOT_STICKY
        val modelPath = ModelDownloads(this).wake
        if (!modelPath.isDirectory) { stopSelf(); return START_NOT_STICKY }
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, labels.text("Фоновый микрофон"), NotificationManager.IMPORTANCE_LOW),
        )
        try {
            val notice = notification("Готовлю фоновое распознавание…")
            if (Build.VERSION.SDK_INT >= 30) startForeground(NOTIFICATION, notice, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
            else startForeground(NOTIFICATION, notice)
        } catch (_: SecurityException) {
            stopSelf()
            return START_NOT_STICKY
        }
        mutableStatus.value = "Готовлю фоновое распознавание…"
        if (chat.speak && chat.mode != "pc") {
            tts = TextToSpeech(this) { result -> ttsReady.complete(result == TextToSpeech.SUCCESS) }
        }
        listening = scope.launch {
            try {
                withTimeoutOrNull(30 * 60 * 1000L) { capture(modelPath.absolutePath) }
            } catch (_: CancellationException) {
                throw CancellationException()
            } catch (_: Exception) {
                report("Фоновый микрофон остановлен. Проверьте разрешение и пакет речи.")
                delay(2400)
            } finally { stopSelf() }
        }
        return START_NOT_STICKY
    }

    private fun notification(message: String): Notification {
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java).setAction(SHOW_COMPANION), flags)
        val stop = PendingIntent.getService(this, 1, Intent(this, WakeService::class.java).setAction(STOP), flags)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle(getString(R.string.app_name) + " · " + labels.text("Микрофон").lowercase())
            .setContentText(labels.text(message))
            .setLargeIcon(noticePortrait)
            .setStyle(Notification.BigTextStyle().bigText(labels.text(message)))
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .addAction(Notification.Action.Builder(null, labels.text("Остановить"), stop).build())
            .build()
    }

    private fun report(message: String) {
        mutableStatus.value = message
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION, notification(message))
    }

    @SuppressLint("MissingPermission")
    private suspend fun capture(modelPath: String) = withContext(Dispatchers.IO) {
        val sampleRate = 16000
        val minimum = AudioRecord.getMinBufferSize(sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        require(minimum > 0)
        Model(modelPath).use { model ->
            Recognizer(model, sampleRate.toFloat(), """["слушай помощник","джарвис","[unk]"]""").use { wake ->
                Recognizer(model, sampleRate.toFloat()).use { speech ->
                    val microphone = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, sampleRate,
                        AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(4800, minimum))
                    record = microphone
                    try {
                        check(microphone.state == AudioRecord.STATE_INITIALIZED)
                        ensureActive()
                        microphone.startRecording()
                        check(microphone.recordingState == AudioRecord.RECORDSTATE_RECORDING)
                        report(WAITING)
                        val samples = ShortArray(1600)
                        var deadline = 0L
                        while (isActive) {
                            val now = SystemClock.elapsedRealtime()
                            if (deadline != 0L && now >= deadline) {
                                deadline = 0L
                                speech.reset()
                                wake.reset()
                                report(WAITING)
                            }
                            val count = microphone.read(samples, 0, samples.size, AudioRecord.READ_NON_BLOCKING)
                            check(count >= 0)
                            if (count < 1) { delay(25); continue }
                            if (deadline == 0L) {
                                if (wake.acceptWaveForm(samples, count)) {
                                    val word = JSONObject(wake.result).optString("text")
                                    if (word == "слушай помощник" || word == "джарвис") {
                                        deadline = now + 8000
                                        speech.reset()
                                        report("Скажите просьбу")
                                        runCatching { android.media.ToneGenerator(android.media.AudioManager.STREAM_MUSIC, 45).let { tone ->
                                            tone.startTone(android.media.ToneGenerator.TONE_PROP_BEEP, 100)
                                            try { delay(120) } finally { tone.release() }
                                        } }
                                    }
                                }
                            } else if (speech.acceptWaveForm(samples, count)) {
                                val question = JSONObject(speech.result).optString("text").trim().take(500)
                                if (question.isNotEmpty()) {
                                    microphone.stop()
                                    try { answer(question) }
                                    finally {
                                        ensureActive()
                                        deadline = 0L
                                        wake.reset()
                                        speech.reset()
                                        microphone.startRecording()
                                        report(WAITING)
                                    }
                                }
                            }
                        }
                    } finally {
                        record = null
                        runCatching { microphone.stop() }
                        microphone.release()
                    }
                }
            }
        }
    }

    private suspend fun answer(question: String) {
        val mode = chat.mode
        val historyScope = chat.historyScope
        report("Обрабатываю просьбу…")
        try {
            if (mode == "pc") {
                val base = chat.base
                val token = chat.token
                val request = UUID.randomUUID().toString()
                val lan = chat.lan
                val voiced = chat.speak
                require(token.isNotBlank()) { "Подключите компьютер в приложении." }
                val body = JSONObject().put("text", question).put("audio", voiced).put("request_id", request)
                pc.json(base, "/api/ask", token, body, lan)
                if (voiced) {
                    report("Озвучиваю ответ…")
                    val audio = sound.play(base, token, request, lan) { report("Ответ ПК доступен в приложении.") }
                    try { withTimeoutOrNull(35_000) { audio.join() } } finally { sound.stop() }
                }
            } else {
                val facts = db.facts().joinToString("\n") { it.second }.take(750)
                val reply = commands.answer(question) ?: chat.reply(mode, question, db.recent(historyScope, 8), facts)
                require(reply.isNotBlank()) { "Модель не вернула текст." }
                db.add(historyScope, "user", question)
                db.add(historyScope, "assistant", reply)
                if (chat.speak) {
                    report("Озвучиваю ответ…")
                    readReply(reply)
                }
            }
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            report("Не удалось ответить. Проверьте выбранный режим.")
            delay(1800)
        }
    }

    private suspend fun readReply(text: String) = withContext(Dispatchers.Main) {
        val voice = tts ?: return@withContext
        if (withTimeoutOrNull(4000) { ttsReady.await() } != true) return@withContext
        if (!voice.configureVoice(chat.voiceLocale, chat.mode == "local")) return@withContext
        val done = CompletableDeferred<Unit>()
        voice.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) = Unit
            override fun onDone(utteranceId: String?) { done.complete(Unit) }
            @Deprecated("System callback")
            override fun onError(utteranceId: String?) { done.complete(Unit) }
        })
        if (voice.speak(text.take(1000), TextToSpeech.QUEUE_FLUSH, null, "wake-reply") == TextToSpeech.SUCCESS) {
            try { withTimeoutOrNull(20_000) { done.await() } } finally { voice.stop() }
        }
    }

    override fun onDestroy() {
        val previous = listening
        scope.cancel()
        overlay.hide()
        chat.cancel()
        pc.cancel()
        sound.close()
        runCatching { record?.stop() }
        tts?.shutdown()
        stopForeground(STOP_FOREGROUND_REMOVE)
        mutableStatus.value = ""
        CoroutineScope(Dispatchers.IO).launch {
            previous?.join()
            chat.closeLocal()
            db.close()
        }
        super.onDestroy()
    }
}
