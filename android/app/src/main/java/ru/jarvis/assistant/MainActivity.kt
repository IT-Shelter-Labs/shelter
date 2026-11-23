package ru.jarvis.assistant

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.app.NotificationManager
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.text.InputType
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.widget.*
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale
import java.util.UUID

class MainActivity : Activity(), RecognitionListener {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val prefs by lazy { getSharedPreferences("settings", MODE_PRIVATE) }
    private val labels by lazy { MobileLabels(this) }
    private val vault by lazy { Vault(this) }
    private val db by lazy { History(this) }
    private val localCommands by lazy { MobileCommands(this, db) }
    private val chat by lazy { MobileChat(applicationContext) }
    private val brain get() = chat.brain
    private val models by lazy { ModelDownloads(this) }
    private val pc = Transport()
    private val sound = PcAudio()
    private var requestJob: Job? = null
    private var downloadJob: Job? = null
    private var downloadState = ""
    private var downloadLabel: TextView? = null
    private var downloadProgress: ProgressBar? = null
    private var wakeLabel: TextView? = null
    private var wakeButton: Button? = null
    private lateinit var timeline: ScrollView
    private var polling: Job? = null
    private var recognizer: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var screen = "home"
    private var draft = ""
    private var voicePermissionAction = ""
    private var statusText = ""
    private var stage: CompanionStage? = null
    private var speechId: String? = null
    private var panelPhase = "Готова помочь"
    private var panelActive = false
    private var generation = 0
    private lateinit var root: LinearLayout
    private lateinit var body: LinearLayout
    private lateinit var status: TextView
    private lateinit var input: EditText
    private lateinit var messages: LinearLayout
    private var scenarios = JSONArray()
    private var remoteMessages = JSONArray()
    private var background = Color.rgb(12, 21, 36)
    private var panel = Color.rgb(25, 38, 57)
    private var ink = Color.rgb(237, 245, 255)
    private var secondary = Color.rgb(166, 188, 211)
    private var accent = Color.rgb(122, 200, 187)
    private val mode get() = prefs.getString("mode", if (base.isBlank()) "cloud" else "pc")!!
    private val lan get() = prefs.getBoolean("lan", false)
    private val base get() = prefs.getString("pc", "")!!
    private val historyScope get() = mode + ":" + if (mode == "cloud") prefs.getString("cloud", "") + ":" + prefs.getString("model", "") else "device"
    private fun dp(n: Int) = (n * resources.displayMetrics.density).toInt()
    private fun state(text: String) {
        statusText = text
        if (!isFinishing && ::status.isInitialized) status.text = labels.text(text)
    }
    private fun fail(error: Throwable) { state(error.message?.take(240) ?: "Не удалось выполнить действие") }
    private fun companion(phase: String, active: Boolean = true) {
        panelPhase = phase
        panelActive = active
        stage?.render(labels.text(phase), active)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 30) window.setDecorFitsSystemWindows(false)
        if (Build.VERSION.SDK_INT >= 29) window.isNavigationBarContrastEnforced = false
        screen = savedInstanceState?.getString("screen")
            ?: if (!prefs.getBoolean("onboarded", false) && !prefs.contains("mode") && !prefs.contains("cloud") && base.isBlank()) "welcome" else "home"
        if (intent.action == WakeService.SHOW_COMPANION) screen = "home"
        draft = savedInstanceState?.getString("draft").orEmpty()
        tts = TextToSpeech(this) { result ->
            if (result == TextToSpeech.SUCCESS) applyTts()
        }
        tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(id: String?) { runOnUiThread { if (id == speechId) companion("Отвечаю") } }
            override fun onDone(id: String?) = finishSpeech(id)
            @Deprecated("Compatibility callback for installed speech engines")
            override fun onError(id: String?) = finishSpeech(id)
            override fun onStop(id: String?, interrupted: Boolean) = finishSpeech(id)
        })
        build()
        scope.launch {
            WakeService.status.collect {
                updateWakeUi()
                when (it) {
                    "Скажите просьбу" -> companion("Слушаю")
                    "Обрабатываю просьбу…" -> companion("Готовлю ответ")
                    "Озвучиваю ответ…" -> companion("Отвечаю")
                    WakeService.WAITING -> companion("Жду голосового вызова", false)
                    "" -> if (panelPhase == "Жду голосового вызова" || panelPhase == "Слушаю") companion("Готова помочь", false)
                }
                if (screen == "home" && mode != "pc" && requestJob?.isActive != true && it == WakeService.WAITING) renderHistory()
            }
        }
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("screen", screen)
        outState.putString("draft", if (screen == "home" && ::input.isInitialized) input.text.toString() else draft)
        super.onSaveInstanceState(outState)
    }
    override fun onStart() { super.onStart(); CompanionOverlay.activityVisible.value = true; startPolling() }
    override fun onResume() {
        super.onResume()
        if (screen == "settings") updateWakeUi()
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.action == WakeService.SHOW_COMPANION) navigate("home")
    }
    private fun finishSpeech(id: String?) {
        runOnUiThread {
            if (id == speechId) {
                speechId = null
                companion("Готова помочь", false)
            }
        }
    }
    @Deprecated("Compatibility callback for Android back navigation")
    override fun onBackPressed() {
        if (screen == "settings" || screen == "commands") navigate("home")
        else super.onBackPressed()
    }
    override fun onStop() {
        CompanionOverlay.activityVisible.value = false
        companion("Готова помочь", false)
        polling?.cancel(); recognizer?.cancel(); sound.stop(); tts?.stop()
        requestJob?.cancel(); chat.cancel()
        super.onStop()
    }
    override fun onDestroy() {
        recognizer?.destroy(); sound.close(); tts?.shutdown(); pc.cancel(); chat.cancel()
        scope.cancel()
        CoroutineScope(Dispatchers.IO).launch { brain.close(); db.close() }
        super.onDestroy()
    }

    private fun text(value: String, size: Float = 15f, translate: Boolean = true) = TextView(this).apply {
        text = if (translate) labels.text(value) else value
        textSize = size
        setTextColor(ink)
        setPadding(0, dp(5), 0, dp(5))
    }
    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun rounded(color: Int) = GradientDrawable().apply { setColor(color); cornerRadius = dp(16).toFloat(); setStroke(dp(1), Color.argb(26, 126, 158, 158)) }
    private fun button(label: String, translate: Boolean = true, action: () -> Unit) = Button(this).apply {
        text = if (translate) labels.text(label) else label
        isAllCaps = false; setTextColor(ink); textSize = 14f
        minHeight = dp(48); minimumHeight = dp(48)
        minWidth = 0; minimumWidth = 0
        background = android.graphics.drawable.RippleDrawable(
            android.content.res.ColorStateList.valueOf(Color.argb(48, 105, 166, 154)), rounded(panel), null,
        )
        setPadding(dp(10), dp(5), dp(10), dp(5)); setOnClickListener { action() }
    }
    private fun row(vararg views: View): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        views.forEach { addView(it, LinearLayout.LayoutParams(0, -2, 1f).apply { setMargins(dp(3), dp(4), dp(3), dp(4)) }) }
    }
    private fun field(parent: LinearLayout, label: String, value: String = "", secret: Boolean = false): EditText {
        parent.addView(text(label, 12f).apply { setTextColor(secondary) })
        return EditText(this).apply {
            setText(value); setTextColor(ink); setHintTextColor(secondary); textSize = 14f
            isSingleLine = true; contentDescription = labels.text(label)
            inputType = if (secret) InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD else InputType.TYPE_CLASS_TEXT
            background = rounded(panel); setPadding(dp(12), dp(7), dp(12), dp(7))
            minimumHeight = dp(48)
            parent.addView(this, LinearLayout.LayoutParams(-1, -2))
        }
    }
    private fun card(parent: LinearLayout, title: String): LinearLayout = column().apply {
        background = rounded(panel); setPadding(dp(14), dp(10), dp(14), dp(14))
        parent.addView(this, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(12) })
        addView(text(title, 17f).apply { setTypeface(null, Typeface.BOLD) })
    }
    private fun build() {
        val theme = prefs.getString("theme", "system")
        val light = theme == "light" || theme == "system" && resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK != Configuration.UI_MODE_NIGHT_YES
        background = if (light) Color.rgb(243, 246, 244) else Color.rgb(18, 24, 25)
        panel = if (light) Color.WHITE else Color.rgb(29, 38, 39)
        ink = if (light) Color.rgb(20, 39, 39) else Color.rgb(238, 245, 242)
        secondary = if (light) Color.rgb(72, 93, 92) else Color.rgb(171, 192, 189)
        accent = if (light) Color.rgb(23, 106, 92) else Color.rgb(140, 218, 198)
        downloadLabel = null
        downloadProgress = null
        wakeLabel = null
        wakeButton = null
        stage = null
        val gutter = dp(maxOf(16, (resources.configuration.screenWidthDp - 680) / 2))
        root = column().apply { setPadding(gutter, dp(12), gutter, dp(8)); setBackgroundColor(this@MainActivity.background) }
        if (theme == "glass") root.background = GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(Color.rgb(24, 62, 81), background, Color.rgb(54, 37, 76)))
        if (Build.VERSION.SDK_INT >= 30) root.setOnApplyWindowInsetsListener { v, insets ->
            val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            val ime = insets.getInsets(WindowInsets.Type.ime())
            v.setPadding(gutter + bars.left, dp(12) + bars.top, gutter + bars.right, dp(8) + maxOf(bars.bottom, ime.bottom))
            insets
        }
        setContentView(root)
        if (Build.VERSION.SDK_INT >= 30) {
            val flags = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
            window.insetsController?.setSystemBarsAppearance(if (light) flags else 0, flags)
        }
        root.addView(text(when (screen) { "settings" -> "Настройки"; "commands" -> "Команды"; else -> getString(R.string.app_name) }, 27f).apply {
            setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL))
            if (Build.VERSION.SDK_INT >= 28) isAccessibilityHeading = true
        })
        status = text(statusText.ifBlank { when (mode) { "pc" -> "Подключение к компьютеру"; "cloud" -> "Облачный режим"; else -> "На устройстве" } }, 13f).apply {
            setTextColor(secondary); accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
            visibility = if (screen == "welcome") View.GONE else View.VISIBLE
        }
        root.addView(status)
        if (screen == "home") {
            stage = CompanionStage(this, panel, ink, accent).also {
                root.addView(it, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) })
                it.render(labels.text(panelPhase), panelActive)
            }
        }
        val scroll = ScrollView(this).apply { isFillViewport = true; clipToPadding = false; setPadding(0, dp(12), 0, dp(8)) }
        timeline = scroll
        body = column()
        scroll.addView(body)
        root.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        when (screen) { "welcome" -> welcome(); "settings" -> settings(); "commands" -> commands(); else -> home() }
        if (screen != "welcome") root.addView(row(tab("Чат", "home"), tab("Команды", "commands"), tab("Настройки", "settings")))
        window.decorView.requestApplyInsets()
    }

    private fun tab(label: String, target: String) = button(label) { navigate(target) }.apply {
        isSelected = screen == target
        if (isSelected) {
            background = rounded(Color.argb(24, Color.red(accent), Color.green(accent), Color.blue(accent)))
            setTextColor(accent)
            setTypeface(null, Typeface.BOLD)
        }
    }

    private fun navigate(target: String) {
        if (screen == target) return
        if (screen == "home" && ::input.isInitialized) draft = input.text.toString()
        recognizer?.cancel()
        // A live request holds its answer view. Stop it before changing screens.
        if (requestJob?.isActive == true && screen == "home") stop(false)
        screen = target
        build()
    }

    private fun welcome() {
        body.addView(CompanionStage(this, panel, ink, accent).apply {
            render(labels.text("Готова помочь"), false)
        }, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(14) })
        body.addView(text("Где будет работать помощник?", 24f).apply { setTypeface(null, Typeface.BOLD) })
        body.addView(text("Выберите режим. Его можно сменить в настройках.", 15f).apply { setTextColor(secondary) })
        body.addView(languageChoice())
        fun option(title: String, detail: String, value: String) {
            val box = card(body, title)
            box.addView(text(detail, 14f).apply { setTextColor(secondary) })
            box.addView(button("Настроить") {
                prefs.edit().putString("mode", value).putBoolean("onboarded", true).apply()
                screen = "settings"
                build()
            })
        }
        option("Мой компьютер", "Подключитесь по коду, чтобы пользоваться моделями, голосом и командами своего ПК.", "pc")
        option("Облако", "Выберите провайдера и модель. Нужен ключ вашего сервиса.", "cloud")
        if (BuildConfig.LOCAL_MODEL) option("На устройстве", "Для беседы скачайте компактную модель. После загрузки она работает без сети.", "local")
    }
    private fun home() {
        messages = column()
        body.addView(messages)
        if (mode == "pc") renderRemote() else renderHistory()
        val composer = column().apply { background = rounded(panel); setPadding(dp(8), dp(8), dp(8), dp(4)) }
        wakeLabel = text("", 12f).apply { setTextColor(accent); accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE }
        composer.addView(wakeLabel)
        input = EditText(this).apply {
            hint = labels.text("Напишите сообщение"); setHintTextColor(secondary); setTextColor(ink); textSize = 16f
            minLines = 1; maxLines = 4; minHeight = dp(48)
            background = rounded(this@MainActivity.background)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            contentDescription = labels.text("Сообщение помощнику")
            setText(draft)
        }
        composer.addView(input)
        composer.addView(row(button("Говорить") { microphone() }, button("Стоп") { stop() }, button("Отправить") { send(input.text.toString()) }.apply {
            background = rounded(accent)
            setTextColor(if (Color.luminance(accent) > 0.45f) Color.rgb(11, 33, 28) else Color.WHITE)
            setTypeface(null, Typeface.BOLD)
        }))
        root.addView(composer)
        updateWakeUi()
    }

    private fun emptyChat() {
        val box = card(messages, "Чем помочь?")
        val setup = when (mode) {
            "pc" -> if (chat.token.isBlank()) "Подключить компьютер" else null
            "cloud" -> if (prefs.getString("cloud", "").isNullOrBlank()) "Настроить облачную модель" else null
            else -> if (!models.local.isFile && !models.imported.isFile) "Загрузить модель для беседы" else null
        }
        box.addView(text(if (setup == null) "Напишите сообщение или нажмите «Говорить»." else "Сначала настройте выбранный режим. Время и дата доступны на телефоне.", 14f).apply { setTextColor(secondary) })
        if (setup != null) box.addView(button(setup) { navigate("settings") })
    }
    private fun line(role: String, value: String): TextView = text(labels.text(if (role == "user") "Вы" else if (mode == "pc") "Помощник" else "Пиппа") + "\n" + value, translate = false).apply {
        setPadding(dp(14), dp(10), dp(14), dp(12)); background = rounded(if (role == "user") Color.argb(24, 90, 211, 230) else panel)
        setTextIsSelectable(true); messages.addView(this, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(10) })
    }
    private fun renderHistory() {
        if (screen != "home") return
        messages.removeAllViews()
        val history = db.recent(historyScope)
        if (history.isEmpty()) emptyChat() else history.forEach { line(it.role, it.text) }
        timeline.post { timeline.fullScroll(View.FOCUS_DOWN) }
    }
    private fun renderRemote() {
        if (screen != "home" || mode != "pc") return
        messages.removeAllViews()
        for (i in maxOf(0, remoteMessages.length() - 20) until remoteMessages.length()) {
            val message = remoteMessages.getJSONObject(i); line(message.optString("role"), message.optString("content"))
        }
        if (remoteMessages.length() == 0) emptyChat()
        timeline.post { timeline.fullScroll(View.FOCUS_DOWN) }
    }
    private fun commands() {
        val box = card(body, if (mode == "pc") "Сценарии компьютера" else "Что можно сказать")
        if (mode == "pc") {
            if (scenarios.length() == 0) box.addView(text("Подключите ПК. Здесь появятся сценарии с запуском кнопкой.", 13f))
            for (i in 0 until scenarios.length()) {
                val item = scenarios.getJSONObject(i)
                box.addView(button(item.getString("name"), translate = false) {
                    val execute = { pcPost("/api/run", JSONObject().put("scenario", item.getString("id")).put("confirmed", item.optString("confirm").isNotBlank())) }
                    if (item.optString("confirm").isBlank()) execute() else AlertDialog.Builder(this).setTitle(item.getString("name")).setMessage(item.getString("confirm"))
                        .setPositiveButton(labels.text("Выполнить")) { _, _ -> execute() }.setNegativeButton(labels.text("Отмена"), null).show()
                }, LinearLayout.LayoutParams(-1, dp(52)).apply { bottomMargin = dp(6) })
            }
        } else listOf("Который час", "Какая сегодня дата", "Громкость 50", "Запомни, что я люблю кофе", "Что ты помнишь").forEach { phrase ->
            box.addView(button(phrase) { navigate("home"); send(labels.text(phrase)) })
        }
    }
    private fun settings() {
        val community = card(body, "Проект")
        val links = row()
        links.addView(button("Telegram") { openProjectLink("https://t.me/+tqB8b6h4JbYwZWVi") }, LinearLayout.LayoutParams(0, dp(44), 1f))
        links.addView(button("Поддержать проект") { openProjectLink("https://t.me/itshelter_bot?start=donate") }, LinearLayout.LayoutParams(0, dp(44), 1f))
        community.addView(links)
        if (downloadState.isNotBlank()) {
            val transfers = card(body, "Загрузки")
            downloadLabel = text(downloadState, 14f).apply { accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE }
            transfers.addView(downloadLabel)
            if (downloadJob?.isActive == true) {
                downloadProgress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply { max = 100 }
                transfers.addView(downloadProgress)
                transfers.addView(button("Отменить загрузку") { downloadJob?.cancel() })
            }
        }
        val general = card(body, "Режим и оформление")
        val modes = listOf("Мой компьютер", "Облако", "На устройстве").map(labels::text)
        val ids = listOf("pc", "cloud", "local")
        val select = Spinner(this).apply { adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, modes); setSelection(ids.indexOf(mode).coerceAtLeast(0)) }
        general.addView(select)
        select.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onNothingSelected(parent: AdapterView<*>?) {}
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (mode != ids[position]) {
                    stop(false)
                    stopService(Intent(this@MainActivity, WakeService::class.java))
                    prefs.edit().putString("mode", ids[position]).apply()
                    applyTts()
                    scope.launch { brain.close() }
                    statusText = ""
                    build()
                    startPolling()
                }
            }
        }
        general.addView(row(button("Как в системе") { prefs.edit().putString("theme", "system").apply(); build() },
            button("Тёмная") { prefs.edit().putString("theme", "dark").apply(); build() },
            button("Светлая") { prefs.edit().putString("theme", "light").apply(); build() }))
        general.addView(text("Язык интерфейса", 14f))
        general.addView(languageChoice())
        if (mode == "pc") {
            val computer = card(body, "Подключить компьютер")
            computer.addView(text("На ПК откройте «Подключения → Телефон» и создайте код. Для удалённого доступа нужен HTTPS.", 14f))
            computer.addView(lanChoice())
            val address = field(computer, "Адрес пульта ПК", base)
            val code = field(computer, "Одноразовый код из Джарвиса на ПК")
            computer.addView(button("Подключить по коду") {
                scope.launch { try {
                    val url = Endpoints.checked(address.text.toString(), lan)
                    state("Подключаю компьютер…")
                    val answer = withContext(Dispatchers.IO) { pc.json(url, "/api/pair", body = JSONObject().put("code", code.text.toString().trim()).put("name", Build.MODEL), lan = lan) }
                    vault.set("device", answer.getString("token"))
                    prefs.edit().putString("pc", url).apply()
                    code.setText("")
                    navigate("home"); state("Компьютер подключён")
                    startPolling()
                } catch (error: Exception) { fail(error) } }
            })
            computer.addView(button("Забыть этот ПК") { stop(); vault.set("device", ""); prefs.edit().remove("pc").apply(); scenarios = JSONArray(); remoteMessages = JSONArray(); state("Подключение удалено с телефона. Отозвать устройство можно и на ПК.") })
        } else if (mode == "cloud") {
            cloudSettings()
        } else {
            val device = card(body, "Локальная модель")
            device.addView(text(if (BuildConfig.LOCAL_MODEL) "Qwen3 0.6B · 347 МБ. Подходит для коротких ответов. После загрузки работает без интернета." else "Для беседы на телефоне нужна сборка Shelter Local (Android 12+). Часы и другие простые команды доступны здесь.", 14f))
            if (BuildConfig.LOCAL_MODEL) {
                val issue = models.localIssue()
                if (issue != null) device.addView(text(issue, 14f))
                if (models.local.isFile || models.imported.isFile) {
                    val imported = models.imported.isFile && !prefs.getBoolean("prefer_downloaded_model", false)
                    device.addView(text(if (imported) "Активна импортированная модель" else "Активна Qwen3 0.6B", 14f).apply { setTextColor(accent) })
                }
                if (!models.local.isFile) device.addView(button("Скачать Qwen3 0.6B") { download(false) }.apply { isEnabled = issue == null && downloadJob?.isActive != true })
                if (models.local.isFile && models.imported.isFile) device.addView(row(
                    button("Использовать Qwen3") { chooseModel(true) },
                    button("Использовать импортированную") { chooseModel(false) },
                ))
                device.addView(button("Импортировать .litertlm") {
                    if (downloadJob?.isActive != true) startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                        type = "*/*"; addCategory(Intent.CATEGORY_OPENABLE)
                    }, 8)
                }.apply { isEnabled = issue == null && downloadJob?.isActive != true })
            }
        }
        voiceSettings()
        val memory = card(body, "Память телефона")
        db.facts().forEach { (id, fact) ->
            memory.addView(text(fact, 13f, translate = false))
            memory.addView(button("Забыть этот факт") {
                AlertDialog.Builder(this).setMessage(fact)
                    .setPositiveButton(labels.text("Забыть")) { _, _ -> db.forget(id); build() }
                    .setNegativeButton(labels.text("Отмена"), null).show()
            })
        }
        memory.addView(button("Очистить текущий разговор") {
            AlertDialog.Builder(this).setMessage(labels.text("Удалить разговор этого режима с телефона? Память ПК не изменится."))
                .setPositiveButton(labels.text("Удалить")) { _, _ -> db.clear(historyScope); state("Разговор удалён") }
                .setNegativeButton(labels.text("Отмена"), null).show()
        })
    }

    private fun openProjectLink(url: String) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (_: ActivityNotFoundException) {
            state("Не удалось открыть ссылку.")
        }
    }

    private fun lanChoice() = CheckBox(this).apply {
        text = labels.text("Разрешить HTTP в доверенной домашней сети")
        setTextColor(ink)
        isChecked = lan
        setOnCheckedChangeListener { _, on -> prefs.edit().putBoolean("lan", on).apply() }
    }

    private fun languageChoice() = row(
        button("Русский") { changeLanguage("ru") },
        button("English") { changeLanguage("en") },
    )

    private fun changeLanguage(language: String) {
        if (labels.isEnglish == (language == "en")) return
        prefs.edit().putString("ui_language", language).apply()
        build()
    }

    private fun chooseModel(downloaded: Boolean) {
        stop(false)
        stopService(Intent(this, WakeService::class.java))
        prefs.edit().putBoolean("prefer_downloaded_model", downloaded).apply()
        scope.launch { brain.close() }
        build()
    }

    private fun voiceSettings() {
        val voice = card(body, "Голос и микрофон")
        voice.addView(CheckBox(this).apply {
            text = labels.text("Озвучивать ответы на телефоне"); setTextColor(ink)
            isChecked = chat.speak
            setOnCheckedChangeListener { _, on ->
                prefs.edit().putBoolean("speak", on).apply()
                if (!on) { sound.stop(); tts?.stop() }
            }
        })
        if (mode == "pc") voice.addView(text("В режиме ПК используется голос персонажа, выбранный на компьютере.", 14f))
        else {
            val languages = listOf("ru-RU", "en-US")
            val select = Spinner(this).apply {
                adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, listOf(labels.text("Русский голос"), "English voice"))
                setSelection(languages.indexOf(chat.voiceLocale).coerceAtLeast(0))
                contentDescription = labels.text("Язык системного голоса")
            }
            voice.addView(select)
            select.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onNothingSelected(parent: AdapterView<*>?) = Unit
                override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                    if (chat.voiceLocale != languages[position]) { prefs.edit().putString("voice_locale", languages[position]).apply(); applyTts() }
                }
            }
            voice.addView(button("Проверить голос") { speak(if (chat.voiceLocale == "en-US") "I’m ready." else "Я готов помочь.", true) })
        }
        voice.addView(text("Фоновый режим"))
        voice.addView(CheckBox(this).apply {
            text = labels.text("Показывать Пиппу поверх приложений")
            setTextColor(ink)
            isChecked = prefs.getBoolean(CompanionOverlay.PREFERENCE, false)
            setOnCheckedChangeListener { _, enabled ->
                prefs.edit().putBoolean(CompanionOverlay.PREFERENCE, enabled).apply()
                if (enabled && !Settings.canDrawOverlays(this@MainActivity)) {
                    val permission = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
                    runCatching { startActivity(permission) }.onFailure { state("Разрешение наложения недоступно") }
                }
                updateWakeUi()
            }
        })
        voice.addView(text("При фоновом вызове Пиппа появляется на время команды. Без разрешения Android остаётся уведомление.", 14f).apply { setTextColor(secondary) })
        voice.addView(text("Скажите «Слушай, помощник», дождитесь сигнала и произнесите просьбу. Запись обрабатывается на телефоне. Текст команды получает выбранный режим. Сеанс длится до 30 минут. Остановить его можно в уведомлении.", 14f).apply { setTextColor(secondary) })
        if (!models.wake.isDirectory) voice.addView(button("Скачать пакет русской речи · 45 МБ") { download(true) }.apply {
            isEnabled = downloadJob?.isActive != true
        }) else {
            wakeButton = button("Включить фоновый микрофон") {
                if (WakeService.status.value.isNotBlank()) stopService(Intent(this, WakeService::class.java))
                else allowMicrophone("wake")
            }
            voice.addView(wakeButton)
        }
        wakeLabel = text("", 13f).apply { setTextColor(accent); accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE }
        voice.addView(wakeLabel)
        updateWakeUi()
    }

    private fun updateWakeUi() {
        val current = WakeService.status.value
        wakeLabel?.apply {
            val overlayNeedsPermission = screen == "settings" && prefs.getBoolean(CompanionOverlay.PREFERENCE, false) &&
                !Settings.canDrawOverlays(this@MainActivity)
            text = labels.text(current.ifBlank { "Фоновый микрофон выключен" }) +
                if (overlayNeedsPermission) "\n" + labels.text("Разрешите показ поверх приложений в Android.") else ""
            visibility = if (current.isNotBlank() || screen == "settings") View.VISIBLE else View.GONE
        }
        wakeButton?.text = labels.text(if (current.isBlank()) "Включить фоновый микрофон" else "Остановить фоновый микрофон")
    }

    private fun download(wake: Boolean) {
        if (downloadJob?.isActive == true) return
        downloadState = "Подготовка загрузки…"
        downloadJob = scope.launch(start = CoroutineStart.LAZY) {
            val progress: (Int) -> Unit = { percent ->
                runOnUiThread {
                    if (downloadJob?.isActive == true) {
                        downloadState = if (percent == 100) "Проверяю модель…" else "Загрузка · $percent%"
                        downloadLabel?.text = labels.text(downloadState)
                        downloadProgress?.progress = percent
                    }
                }
            }
            try {
                if (wake) models.downloadWake(progress)
                else {
                    stop(false)
                    stopService(Intent(this@MainActivity, WakeService::class.java))
                    brain.close()
                    models.downloadLocal(progress) { brain.validate(it.absolutePath, 1280) }
                    prefs.edit().putBoolean("prefer_downloaded_model", true).apply()
                }
                downloadState = if (wake) "Пакет речи готов." else "Модель загружена и проверена."
            } catch (error: CancellationException) {
                downloadState = "Загрузка отменена."
            } catch (error: Exception) {
                downloadState = error.message?.take(180) ?: "Загрузить модель не удалось."
            } finally {
                downloadJob = null
                if (!isFinishing && !isDestroyed && screen == "settings") build()
            }
        }
        downloadJob?.start()
        build()
    }

    private fun cloudSettings() {
        val service = card(body, "Облачная модель")
        val savedAddress = prefs.getString("cloud", "").orEmpty()
        val providers = linkedMapOf(
            "OpenAI" to "https://api.openai.com/v1",
            "OpenRouter" to "https://openrouter.ai/api/v1",
            "DeepSeek" to "https://api.deepseek.com/v1",
            "Dahl Inference" to "https://inference.dahl.global/v1",
            "Свой OpenAI-совместимый API" to ""
        )
        val start = if (savedAddress.isBlank()) 0 else providers.values.indexOf(savedAddress).let { if (it >= 0) it else providers.size - 1 }
        val selector = Spinner(this).apply {
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, providers.keys.map(labels::text))
            setSelection(start)
            contentDescription = labels.text("Провайдер модели")
        }
        service.addView(selector)
        val endpoint = field(service, "Базовый адрес API", savedAddress.ifBlank { providers.values.first() })
        val key = field(service, "API-ключ", vault.get("cloud"), true)
        val model = field(service, "ID модели", prefs.getString("model", "").orEmpty())
        service.addView(lanChoice())
        var current = start
        selector.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onNothingSelected(parent: AdapterView<*>?) {}
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (position == current) return
                current = position
                endpoint.setText(providers.values.elementAt(position))
                key.setText("")
                model.setText("")
            }
        }
        service.addView(button("Сохранить подключение") {
            try {
                val url = Endpoints.checked(endpoint.text.toString(), lan)
                val keyText = key.text.toString().trim()
                require(model.text.isNotBlank() && keyText.isNotBlank()) { "Укажите API-ключ и ID модели" }
                require(savedAddress.isBlank() || Endpoints.sameOrigin(savedAddress, url) || keyText != vault.get("cloud")) {
                    "Для нового сервера введите отдельный ключ API"
                }
                stop(false)
                vault.set("cloud", keyText)
                prefs.edit().putString("cloud", url).putString("model", model.text.toString().trim()).apply()
                screen = "home"
                build()
                state("Облачная модель настроена")
            } catch (error: Exception) { fail(error) }
        })
    }

    private fun startPolling() {
        polling?.cancel()
        if (mode != "pc" || vault.get("device").isEmpty() || base.isEmpty()) return
        polling = scope.launch {
            while (isActive && mode == "pc") {
                try {
                    val answer = withContext(Dispatchers.IO) { pc.json(base, "/api/state", vault.get("device"), lan = lan) }
                    if (!isActive) break
                    scenarios = answer.optJSONArray("scenarios") ?: JSONArray()
                    val next = answer.optJSONArray("messages") ?: JSONArray()
                    if (next.toString() != remoteMessages.toString()) { remoteMessages = next; renderRemote() }
                    val speaking = answer.optBoolean("speaking")
                    val thinking = answer.optBoolean("thinking")
                    if (WakeService.status.value.isBlank() && panelPhase != "Слушаю") {
                        companion(if (speaking) "Отвечаю" else if (thinking) "Готовлю ответ" else "Готова помочь", speaking || thinking)
                    }
                    state(if (speaking) "ПК отвечает" else if (thinking) "ПК думает" else "Компьютер на связи")
                } catch (error: Exception) { if (isActive) state("Нет связи с ПК · ${error.message?.take(100)}") }
                delay(2500)
            }
        }
    }
    private fun pcPost(path: String, body: JSONObject, audio: Boolean = false) {
        val request = UUID.randomUUID().toString()
        val token = vault.get("device")
        if (token.isEmpty()) { state("Сначала подключите ПК по коду"); return }
        body.put("request_id", request)
        scope.launch { try {
            withContext(Dispatchers.IO) { pc.json(base, path, token, body, lan) }
            if (audio) sound.play(base, token, request, lan) { error -> runOnUiThread { state(error) } }
            state("Запрос принят компьютером")
        } catch (error: Exception) { fail(error) } }
    }
    private fun stop(remote: Boolean = true) {
        speechId = null
        generation++; requestJob?.cancel(); chat.cancel(); sound.stop(); tts?.stop(); recognizer?.cancel()
        if (remote) stopService(Intent(this, WakeService::class.java))
        if (remote && mode == "pc" && vault.get("device").isNotEmpty()) pcPost("/api/interrupt", JSONObject())
        if (remote) { state("Остановлено"); companion("Готова помочь", false) }
    }
    private fun send(raw: String) {
        val question = raw.trim()
        if (question.isEmpty()) return
        val selected = mode
        val short = models.local.isFile && (prefs.getBoolean("prefer_downloaded_model", false) || !models.imported.isFile)
        val limit = if (selected == "local") if (short) 900 else 4000 else 12000
        if (question.length > limit) { state("Фраза слишком длинная для выбранного режима: максимум $limit знаков"); return }
        input.setText("")
        draft = ""
        stopService(Intent(this, WakeService::class.java))
        if (mode == "pc") {
            companion("Готовлю ответ")
            val audio = prefs.getBoolean("speak", true)
            pcPost("/api/ask", JSONObject().put("text", question).put("audio", audio), audio)
            return
        }
        stop(false)
        companion("Готовлю ответ")
        val version = generation
        val channel = historyScope
        val context = db.recent(channel, 12)
        val local = localCommands.answer(question)
        if (local != null) { db.add(channel, "user", question); db.add(channel, "assistant", local); renderHistory(); speak(local); return }
        if (context.isEmpty()) messages.removeAllViews()
        line("user", question)
        val output = line("assistant", labels.text("Думаю…"))
        timeline.post { timeline.fullScroll(View.FOCUS_DOWN) }
        requestJob = scope.launch { try {
            state(if (selected == "local") "Модель думает на телефоне…" else "Обращаюсь к выбранному облаку…")
            val facts = db.facts().joinToString("\n") { it.second }.take(if (selected == "local") 1500 else 3000)
            val response = chat.reply(selected, question, context, facts) { partial ->
                runOnUiThread { if (version == generation) output.text = labels.text("Пиппа") + "\n" + partial }
            }
            ensureActive()
            if (version != generation) return@launch
            require(response.isNotBlank()) { "Модель не вернула текст" }
            db.add(channel, "user", question); db.add(channel, "assistant", response)
            output.text = labels.text("Пиппа") + "\n" + response; state("Готово"); speak(response)
        } catch (error: Exception) { if (isActive && version == generation) {
            output.text = labels.text("Не удалось ответить: ${error.message?.take(240)}")
            companion("Готова помочь", false)
            fail(error)
        } } }
    }
    private fun applyTts() {
        ttsReady = tts?.configureVoice(chat.voiceLocale, mode == "local") == true
    }

    private fun speak(value: String, preview: Boolean = false) {
        if (!chat.speak && !preview) { companion("Готова помочь", false); return }
        val id = UUID.randomUUID().toString()
        speechId = id
        if (!ttsReady || tts?.speak(value.take(2000), TextToSpeech.QUEUE_FLUSH, null, id) != TextToSpeech.SUCCESS) {
            finishSpeech(id)
            state("Озвучка недоступна. Установите нужный голос в настройках Android.")
        }
    }
    private fun microphone() {
        if (WakeService.status.value.isNotBlank()) {
            stopService(Intent(this, WakeService::class.java))
            state("Фоновый микрофон выключается. Нажмите «Говорить» ещё раз.")
            return
        }
        allowMicrophone("single")
    }

    private fun allowMicrophone(action: String) {
        voicePermissionAction = action
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 7)
            return
        }
        if (action == "single") { listenOnce(); return }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 9)
            return
        }
        if (!getSystemService(NotificationManager::class.java).areNotificationsEnabled()) {
            state("Для фонового режима включите уведомления Джарвиса в настройках Android.")
            return
        }
        if (mode == "pc" && chat.token.isBlank() || mode == "cloud" && prefs.getString("cloud", "").isNullOrBlank()) {
            state("Сначала настройте выбранный режим помощника.")
            return
        }
        if (requestJob?.isActive == true || downloadJob?.isActive == true) {
            state("Дождитесь ответа или окончания загрузки.")
            return
        }
        sound.stop()
        tts?.stop()
        recognizer?.destroy()
        recognizer = null
        scope.launch {
            brain.close()
            if (!hasWindowFocus()) { state("Включите фоновый микрофон из открытого приложения."); return@launch }
            try { startForegroundService(Intent(this@MainActivity, WakeService::class.java)) }
            catch (_: IllegalStateException) { state("Включите фоновый микрофон из открытого приложения.") }
            catch (_: SecurityException) { state("Android не разрешил фоновый микрофон.") }
        }
    }

    private fun listenOnce() {
        sound.stop(); tts?.stop()
        val offline = Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(this)
        if (mode == "local" && !offline) { state("В системе нет офлайн-распознавания. Используйте текст или установите русский пакет распознавания; звук в облако не отправлен."); return }
        if (!offline && !prefs.getBoolean("systemSpeechAccepted", false)) {
            AlertDialog.Builder(this).setTitle(labels.text("Системное распознавание")).setMessage(labels.text("На этом телефоне распознаватель может использовать облако своего поставщика. Продолжить голосовой ввод?"))
                .setPositiveButton(labels.text("Продолжить")) { _, _ -> prefs.edit().putBoolean("systemSpeechAccepted", true).apply(); microphone() }
                .setNegativeButton(labels.text("Отмена"), null).show(); return
        }
        if (!offline && !SpeechRecognizer.isRecognitionAvailable(this)) {
            state("На телефоне нет распознавания речи. Можно написать текстом.")
            return
        }
        recognizer?.destroy()
        recognizer = if (offline) SpeechRecognizer.createOnDeviceSpeechRecognizer(this) else SpeechRecognizer.createSpeechRecognizer(this)
        recognizer!!.setRecognitionListener(this)
        recognizer!!.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, chat.voiceLocale)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, offline)
        })
        state("Слушаю…")
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grants: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grants)
        if (requestCode != 7 && requestCode != 9) return
        if (grants.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            if (voicePermissionAction == "wake") state("Разрешение получено. Нажмите «Включить фоновый микрофон».")
            else listenOnce()
        } else state(if (requestCode == 9) "Для фонового режима нужны уведомления." else "Микрофон недоступен. Можно написать текстом.")
    }
    override fun onReadyForSpeech(params: Bundle?) { state("Говорите просьбу"); companion("Слушаю") }
    override fun onBeginningOfSpeech() { state("Слышу вас…") }
    override fun onRmsChanged(rmsdB: Float) {}
    override fun onBufferReceived(buffer: ByteArray?) {}
    override fun onEndOfSpeech() { state("Распознаю…"); companion("Готовлю ответ") }
    override fun onError(error: Int) {
        companion("Готова помочь", false)
        state(if (error in listOf(SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT)) "Не расслышал. Нажмите «Говорить» ещё раз." else "Распознавание недоступно (код $error). Можно написать текстом.")
    }
    override fun onResults(results: Bundle?) { if (screen != "home") return; results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let { input.setText(it); send(it) } }
    override fun onPartialResults(results: Bundle?) { results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let { if (screen == "home") input.setText(it) } }
    override fun onEvent(eventType: Int, params: Bundle?) {}

    @Deprecated("Platform callback")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 8 || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        if (downloadJob?.isActive == true || !BuildConfig.LOCAL_MODEL) return
        downloadState = "Копирую модель на телефон…"
        downloadJob = scope.launch(start = CoroutineStart.LAZY) {
            try {
                stop(false)
                stopService(Intent(this@MainActivity, WakeService::class.java))
                brain.close()
                withContext(Dispatchers.IO) {
                val folder = File(filesDir, "models").apply { mkdirs() }
                val partial = File(folder, "assistant.import.litertlm")
                try {
                    val stream = requireNotNull(contentResolver.openInputStream(uri)) { "Не удалось открыть выбранный файл." }
                    stream.use { source -> partial.outputStream().use { output ->
                        val buffer = ByteArray(1024 * 1024); var total = 0L
                        while (true) { ensureActive(); val count = source.read(buffer); if (count < 0) break; total += count; require(total < 5L * 1024 * 1024 * 1024 && folder.usableSpace > 128L * 1024 * 1024) { "Недостаточно места или модель больше 5 ГБ" }; output.write(buffer, 0, count) }
                    } }
                    require(partial.length() > 1024) { "Файл модели пустой" }
                    brain.validate(partial.absolutePath, 8192)
                    ensureActive()
                    java.nio.file.Files.move(partial.toPath(), models.imported.toPath(),
                        java.nio.file.StandardCopyOption.REPLACE_EXISTING, java.nio.file.StandardCopyOption.ATOMIC_MOVE)
                } finally { partial.delete() }
                }
                prefs.edit().putBoolean("prefer_downloaded_model", false).apply()
                downloadState = "Модель импортирована и проверена."
            } catch (_: CancellationException) {
                downloadState = "Импорт отменён."
            } catch (error: Exception) {
                downloadState = error.message?.take(180) ?: "Импорт модели не удался."
            } finally {
                downloadJob = null
                if (!isFinishing && !isDestroyed && screen == "settings") build()
            }
        }
        downloadJob?.start()
        build()
    }
}
