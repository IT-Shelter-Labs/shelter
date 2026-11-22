package ru.jarvis.assistant

import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.util.concurrent.ConcurrentHashMap

object Endpoints {
    fun sameOrigin(first: String, second: String): Boolean {
        fun origin(raw: String): Triple<String, String, Int> {
            val uri = URI(raw)
            val defaultPort = if (uri.scheme == "https") 443 else 80
            return Triple(uri.scheme, uri.host.lowercase(), if (uri.port < 0) defaultPort else uri.port)
        }
        return origin(first) == origin(second)
    }

    fun checked(raw: String, allowLanHttp: Boolean): String {
        val uri = URI(raw.trim())
        require(uri.scheme in listOf("http", "https") && !uri.host.isNullOrBlank()) { "Нужен полный адрес https://…" }
        require(uri.userInfo == null && uri.query == null && uri.fragment == null) { "Ключи и параметры не должны находиться в адресе сервера" }
        if (uri.scheme == "http") {
            val host = uri.host.removePrefix("[").removeSuffix("]").lowercase()
            val parts = host.split('.').mapNotNull { it.toIntOrNull()?.takeIf { n -> n in 0..255 } }
            val ipv4 = parts.size == 4 && host.split('.').size == 4 &&
                (parts[0] == 10 || parts[0] == 127 || parts[0] == 192 && parts[1] == 168 || parts[0] == 172 && parts[1] in 16..31)
            val local = host == "localhost" || host == "::1" || host.endsWith(".local") || ipv4
            require(allowLanHttp && local) { "HTTP разрешён только для домашней сети после включения соответствующей настройки. Для интернета нужен HTTPS" }
        }
        return raw.trim().trimEnd('/')
    }
}

class Transport {
    private val connections = ConcurrentHashMap.newKeySet<HttpURLConnection>()
    fun cancel() = connections.toList().forEach { it.disconnect() }

    fun json(base: String, path: String, token: String = "", body: JSONObject? = null, lan: Boolean = false): JSONObject {
        val address = Endpoints.checked(base, lan) + path
        val connection = URI(address).toURL().openConnection() as HttpURLConnection
        connections.add(connection)
        try {
            connection.connectTimeout = 10000
            connection.readTimeout = if (path.startsWith("/api/audio")) 12000 else 60000
            connection.instanceFollowRedirects = false // Bearer-ключ никогда не уходит вслед за перенаправлением.
            connection.requestMethod = if (body == null) "GET" else "POST"
            connection.setRequestProperty("Accept", "application/json")
            if (token.isNotEmpty()) connection.setRequestProperty("Authorization", "Bearer $token")
            if (body != null) {
                val bytes = body.toString().toByteArray(Charsets.UTF_8)
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.setFixedLengthStreamingMode(bytes.size)
                connection.doOutput = true
                connection.outputStream.use { it.write(bytes) }
            }
            val code = connection.responseCode
            val source = if (code in 200..299) connection.inputStream else connection.errorStream
            val buffer = ByteArrayOutputStream()
            source?.use { stream ->
                val chunk = ByteArray(8192)
                while (true) {
                    val count = stream.read(chunk)
                    if (count < 0) break
                    if (buffer.size() + count > 4 * 1024 * 1024) throw IOException("Ответ сервера слишком большой")
                    buffer.write(chunk, 0, count)
                }
            }
            val result = runCatching { JSONObject(buffer.toString("UTF-8")) }.getOrDefault(JSONObject())
            if (code !in 200..299) {
                val reason = when (code) {
                    401, 403 -> "Нет доступа: проверьте сопряжение или ключ"
                    429 -> "Лимит сервиса исчерпан; повторите позднее"
                    in 300..399 -> "Сервер перенаправляет запрос. Укажите конечный адрес в настройках"
                    else -> result.optJSONObject("error")?.optString("message") ?: result.optString("error", "Сервер ответил: $code")
                }
                throw IOException(reason.replace(token.ifEmpty { "\u0000" }, "•••").take(300))
            }
            return result
        } finally { connections.remove(connection); connection.disconnect() }
    }
}
