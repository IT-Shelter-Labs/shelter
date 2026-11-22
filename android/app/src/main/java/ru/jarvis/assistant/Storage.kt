package ru.jarvis.assistant

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class Vault(context: Context) {
    private val prefs = context.getSharedPreferences("credentials", Context.MODE_PRIVATE)
    private val alias = "jarvis-device-credentials"
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun set(name: String, value: String) {
        if (value.isEmpty()) { prefs.edit().remove(name).apply(); return }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val bytes = cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        check(prefs.edit().putString(name, Base64.encodeToString(bytes, Base64.NO_WRAP)).commit()) { "Не удалось сохранить ключ" }
    }
    fun get(name: String): String = runCatching {
        val bytes = Base64.decode(prefs.getString(name, ""), Base64.NO_WRAP)
        if (bytes.size < 28) return@runCatching ""
        Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12))) }
            .doFinal(bytes.copyOfRange(12, bytes.size)).toString(Charsets.UTF_8)
    }.getOrDefault("")
}

data class ChatLine(val role: String, val text: String)
class History(context: Context) : SQLiteOpenHelper(context, "conversations.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE messages(id INTEGER PRIMARY KEY, scope TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL)")
        db.execSQL("CREATE INDEX message_scope ON messages(scope,id)")
        db.execSQL("CREATE TABLE facts(id INTEGER PRIMARY KEY, text TEXT NOT NULL UNIQUE)")
    }
    override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) { error("Неизвестная версия памяти") }
    fun add(scope: String, role: String, text: String) = writableDatabase.insertOrThrow("messages", null, ContentValues().apply {
        put("scope", scope); put("role", role); put("text", text)
    })
    fun recent(scope: String, limit: Int = 24): List<ChatLine> {
        val result = mutableListOf<ChatLine>()
        readableDatabase.rawQuery("SELECT role,text FROM messages WHERE scope=? ORDER BY id DESC LIMIT ?", arrayOf(scope, limit.coerceIn(1, 64).toString())).use {
            while (it.moveToNext()) result.add(ChatLine(it.getString(0), it.getString(1)))
        }
        return result.reversed()
    }
    fun remember(text: String) = writableDatabase.insertWithOnConflict("facts", null, ContentValues().apply { put("text", text.take(1000)) }, SQLiteDatabase.CONFLICT_IGNORE)
    fun facts(): List<Pair<Long, String>> {
        val result = mutableListOf<Pair<Long, String>>()
        readableDatabase.rawQuery("SELECT id,text FROM facts ORDER BY id", null).use { while (it.moveToNext()) result.add(it.getLong(0) to it.getString(1)) }
        return result
    }
    fun forget(id: Long) = writableDatabase.delete("facts", "id=?", arrayOf(id.toString()))
    fun clear(scope: String) = writableDatabase.delete("messages", "scope=?", arrayOf(scope))
}
