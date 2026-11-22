package ru.jarvis.assistant

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.util.Base64
import kotlinx.coroutines.*

class PcAudio {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val net = Transport()
    private var job: Job? = null
    @Volatile private var track: AudioTrack? = null
    fun play(base: String, token: String, request: String, lan: Boolean, onError: (String) -> Unit): Job {
        val previous = job
        stop()
        job = scope.launch {
            previous?.join()
            var cursor = 0
            var rate = 0
            var frames = 0L
            try {
                while (isActive) {
                    val answer = net.json(base, "/api/audio?request=$request&after=$cursor", token, lan = lan)
                    val chunks = answer.getJSONArray("chunks")
                    for (i in 0 until chunks.length()) {
                        ensureActive()
                        val chunk = chunks.getJSONObject(i)
                        val nextRate = chunk.getInt("rate")
                        require(nextRate in 8000..48000) { "Неизвестный формат звука" }
                        if (nextRate != rate) {
                            track?.run { stop(); release() }
                            val size = maxOf(AudioTrack.getMinBufferSize(nextRate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT), nextRate)
                            track = AudioTrack.Builder().setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                                .setAudioFormat(AudioFormat.Builder().setSampleRate(nextRate).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                                .setBufferSizeInBytes(size).setTransferMode(AudioTrack.MODE_STREAM).build().apply { play() }
                            rate = nextRate; frames = 0
                        }
                        val bytes = Base64.decode(chunk.getString("pcm"), Base64.NO_WRAP)
                        var written = 0
                        while (written < bytes.size && isActive) {
                            val count = track!!.write(bytes, written, bytes.size - written, AudioTrack.WRITE_BLOCKING)
                            check(count > 0) { "Аудиоустройство отключилось" }
                            written += count
                        }
                        frames += written / 2
                        cursor = chunk.getInt("seq")
                    }
                    if (answer.optBoolean("done")) {
                        val until = System.currentTimeMillis() + 2500
                        while (isActive && track != null && (track!!.playbackHeadPosition.toLong() and 0xffffffffL) < frames && System.currentTimeMillis() < until) delay(20)
                        val error = answer.optString("error")
                        if (error.isNotBlank() && error != "остановлено") onError(error)
                        break
                    }
                }
            } catch (error: Exception) { if (isActive) onError(error.message ?: "Звук недоступен") }
            finally { track?.run { runCatching { stop() }; release() }; track = null }
        }
        return checkNotNull(job)
    }
    fun stop() { job?.cancel(); net.cancel(); track?.run { runCatching { pause(); flush() } } }
    fun close() { stop(); scope.cancel() }
}
