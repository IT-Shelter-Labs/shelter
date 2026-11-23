package ru.jarvis.assistant

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import android.os.Process
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.zip.ZipInputStream

internal class ModelDownloads(private val context: Context) {
    val local = File(context.filesDir, "models/qwen3-0.6b.litertlm")
    val imported = File(context.filesDir, "models/assistant.litertlm")
    val wake = File(context.filesDir, "wake/vosk-model-small-ru-0.22")

    fun localIssue(): String? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return "Для локальной модели нужен Android 12 или новее."
        if (!Process.is64Bit() || Build.SUPPORTED_64_BIT_ABIS.none { it in listOf("arm64-v8a", "x86_64") })
            return "Для локальной модели нужен 64-разрядный Android."
        val memory = ActivityManager.MemoryInfo()
        context.getSystemService(ActivityManager::class.java).getMemoryInfo(memory)
        if (memory.totalMem < 2_500_000_000L) return "Для модели нужно устройство примерно с 3 ГБ ОЗУ или больше."
        return null
    }

    suspend fun downloadLocal(progress: (Int) -> Unit, validate: suspend (File) -> Unit) = withContext(Dispatchers.IO) {
        localIssue()?.let { throw IllegalStateException(it) }
        val folder = local.parentFile!!
        folder.mkdirs()
        val partial = File(folder, "qwen.download.litertlm")
        try {
            fetch(
                "https://huggingface.co/litert-community/Qwen3-0.6B-int4/resolve/01d8620f3233a158edc2aa2c84f5d5e3fa0c02c0/qwen3_0.6b_nothink_q4_block32_ekv1280.litertlm",
                partial, 370_000_000L, progress, "2df6821ec12702dafd33915e7a1a1adc7c4b053f3672fd9555dfaf3a114c4139",
            )
            ensureActive()
            validate(partial)
            ensureActive()
            Files.move(partial.toPath(), local.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
        } finally { partial.delete() }
    }

    suspend fun downloadWake(progress: (Int) -> Unit) = withContext(Dispatchers.IO) {
        val folder = wake.parentFile!!
        folder.mkdirs()
        require(folder.usableSpace > 210_000_000L) { "Освободите 210 МБ для пакета распознавания." }
        val archive = File(folder, "vosk.part")
        val staging = File(folder, "extract")
        try {
            // The upstream model is also mirrored by Rhasspy. Pin its published file digest.
            fetch(
                "https://huggingface.co/rhasspy/vosk-models/resolve/e7ac2109d134b5f2404ba95389b2fb51916d4cab/ru/vosk-model-small-ru-0.22.zip",
                archive, 60_000_000L, progress, "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4",
            )
            staging.mkdirs()
            val root = staging.canonicalPath + File.separator
            var unpacked = 0L
            var entries = 0
            ZipInputStream(archive.inputStream().buffered()).use { zip ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    ensureActive()
                    val entry = zip.nextEntry ?: break
                    val target = File(staging, entry.name).canonicalFile
                    require(++entries <= 100 && target.path.startsWith(root)) { "Неверный пакет распознавания." }
                    if (entry.isDirectory) target.mkdirs()
                    else {
                        target.parentFile?.mkdirs()
                        target.outputStream().use { output ->
                            while (true) {
                                ensureActive()
                                val count = zip.read(buffer)
                                if (count < 0) break
                                unpacked += count
                                require(unpacked <= 160_000_000L) { "Пакет распознавания слишком велик." }
                                output.write(buffer, 0, count)
                            }
                        }
                    }
                    zip.closeEntry()
                }
            }
            val prepared = File(staging, wake.name)
            require(File(prepared, "am/final.mdl").isFile && File(prepared, "conf/model.conf").isFile) { "В пакете нет модели Vosk." }
            ensureActive()
            Files.move(prepared.toPath(), wake.toPath(), StandardCopyOption.ATOMIC_MOVE)
        } finally { archive.delete(); staging.deleteRecursively() }
    }

    private suspend fun fetch(url: String, file: File, max: Long, progress: (Int) -> Unit, sha: String? = null) =
        withContext(Dispatchers.IO) {
            require(file.parentFile!!.usableSpace > max + 128_000_000L) { "Недостаточно места для загрузки модели." }
            var address = URL(url)
            var connection: HttpURLConnection? = null
            try {
                for (attempt in 0..5) {
                    require(address.protocol == "https") { "Сервер предложил небезопасную загрузку." }
                    connection = address.openConnection() as HttpURLConnection
                    val current = connection
                    current.instanceFollowRedirects = false
                    current.connectTimeout = 12_000
                    current.readTimeout = 12_000
                    current.setRequestProperty("Accept-Encoding", "identity")
                    val code = current.responseCode
                    if (code == 200) break
                    val next = current.getHeaderField("Location")
                    require(code in setOf(301, 302, 303, 307, 308) && !next.isNullOrBlank() && attempt < 5) { "Сервер модели ответил кодом $code." }
                    address = URL(address, next)
                    current.disconnect()
                    connection = null
                    ensureActive()
                }
                val current = checkNotNull(connection)
                val length = current.contentLengthLong
                require(length <= max) { "Файл модели больше ожидаемого." }
                val digest = MessageDigest.getInstance("SHA-256")
                var total = 0L
                var percent = -1
                current.inputStream.use { input -> file.outputStream().buffered().use { output ->
                    val buffer = ByteArray(128 * 1024)
                    while (true) {
                        ensureActive()
                        val count = input.read(buffer)
                        if (count < 0) break
                        total += count
                        require(total <= max) { "Файл модели больше ожидаемого." }
                        output.write(buffer, 0, count)
                        digest.update(buffer, 0, count)
                        val next = (100 * total / (length.takeIf { it > 0 } ?: max)).toInt().coerceIn(0, 99)
                        if (next != percent) { progress(next); percent = next }
                    }
                } }
                require(total > 1_000_000L && (length < 0 || total == length)) { "Загрузка модели прервалась." }
                if (sha != null) {
                    val actual = digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
                    require(actual == sha) { "Контрольная сумма модели не совпала." }
                }
                progress(100)
            } finally { connection?.disconnect() }
        }
}
