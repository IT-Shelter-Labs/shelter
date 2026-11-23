package ru.jarvis.assistant

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.view.Gravity
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView

/** A static portrait with a short transition on phase changes. No render loop. */
internal class CompanionStage(context: Context, surface: Int, private val ink: Int, private val accent: Int) :
    LinearLayout(context) {
    private val portrait = ImageView(context).apply {
        scaleType = ImageView.ScaleType.CENTER_CROP
        setImageResource(R.drawable.pippa_portrait)
        background = GradientDrawable().apply {
            setColor(Color.rgb(38, 64, 59))
            cornerRadius = dp(18).toFloat()
        }
        clipToOutline = true
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }
    private val phaseLabel = TextView(context).apply {
        textSize = 14f
        setTextColor(ink)
        accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
    }
    private var active = false

    init {
        orientation = HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        setPadding(dp(12), dp(10), dp(12), dp(10))
        background = GradientDrawable().apply {
            colors = intArrayOf(Color.argb(26, Color.red(accent), Color.green(accent), Color.blue(accent)), surface)
            cornerRadius = dp(20).toFloat()
            setStroke(dp(1), Color.argb(75, Color.red(accent), Color.green(accent), Color.blue(accent)))
        }
        addView(portrait, LayoutParams(dp(64), dp(64)))
        addView(LinearLayout(context).apply {
            orientation = VERTICAL
            addView(TextView(context).apply {
                text = MobileLabels(context).text("Пиппа")
                textSize = 19f
                typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
                setTextColor(ink)
            })
            addView(phaseLabel)
        }, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f).apply { marginStart = dp(14) })
    }

    fun render(message: String, engaged: Boolean) {
        if (phaseLabel.text != message) phaseLabel.text = message
        if (active == engaged) return
        active = engaged
        portrait.animate().cancel()
        phaseLabel.setTextColor(if (active) accent else ink)
        val scale = if (active) 1.08f else 1f
        if (isShown && (Build.VERSION.SDK_INT < 26 || ValueAnimator.areAnimatorsEnabled())) {
            portrait.animate().scaleX(scale).scaleY(scale).setDuration(180).start()
        } else {
            portrait.scaleX = scale
            portrait.scaleY = scale
        }
    }

    override fun onDetachedFromWindow() {
        portrait.animate().cancel()
        super.onDetachedFromWindow()
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density + .5f).toInt()
}
