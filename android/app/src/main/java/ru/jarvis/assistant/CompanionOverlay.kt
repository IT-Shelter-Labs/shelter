package ru.jarvis.assistant

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import kotlinx.coroutines.flow.MutableStateFlow

/** Created on the main thread only. It exists for one active wake interaction. */
internal class CompanionOverlay(private val context: Context) {
    companion object {
        const val PREFERENCE = "companion_overlay"
        val activityVisible = MutableStateFlow(false)
    }

    private val windows = context.getSystemService(WindowManager::class.java)
    private val labels = MobileLabels(context)
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)
    private var container: View? = null
    private var stage: CompanionStage? = null
    private var dismissed = false

    fun update(phase: String?) {
        if (phase == null) dismissed = false
        if (phase == null || dismissed || activityVisible.value || !prefs.getBoolean(PREFERENCE, false) || !Settings.canDrawOverlays(context)) {
            hide()
            return
        }
        if (container == null) {
            val surface = Color.rgb(27, 38, 40)
            val ink = Color.rgb(237, 247, 241)
            val accent = Color.rgb(143, 226, 204)
            val portrait = CompanionStage(context, surface, ink, accent).apply { background = null }
            val view = LinearLayout(context).apply {
                gravity = Gravity.CENTER_VERTICAL
                background = GradientDrawable().apply {
                    setColor(surface)
                    cornerRadius = dp(20).toFloat()
                    setStroke(dp(1), Color.argb(110, Color.red(accent), Color.green(accent), Color.blue(accent)))
                }
                clipToOutline = true
                addView(portrait, LinearLayout.LayoutParams(0, -2, 1f))
                addView(TextView(context).apply {
                    text = "×"
                    textSize = 24f
                    setTextColor(ink)
                    gravity = Gravity.CENTER
                    contentDescription = labels.text("Скрыть Пиппу")
                    setOnClickListener { dismissed = true; hide() }
                }, LinearLayout.LayoutParams(dp(48), dp(64)))
            }
            val params = WindowManager.LayoutParams(
                dp(minOf(300, context.resources.configuration.screenWidthDp - 24)), -2,
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
                PixelFormat.TRANSLUCENT,
            ).apply {
                gravity = Gravity.TOP or Gravity.END
                x = dp(12)
                y = dp(56)
            }
            if (runCatching { windows.addView(view, params) }.isFailure) return
            container = view
            stage = portrait
        }
        stage?.render(labels.text(phase), true)
    }

    fun hide() {
        container?.let { runCatching { windows.removeViewImmediate(it) } }
        container = null
        stage = null
    }

    private fun dp(value: Int) = (value * context.resources.displayMetrics.density + .5f).toInt()
}
