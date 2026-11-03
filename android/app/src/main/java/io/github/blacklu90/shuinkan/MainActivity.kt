package io.github.blacklu90.shuinkan

import android.Manifest
import android.annotation.SuppressLint
import android.app.AlertDialog
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.SystemClock
import android.provider.MediaStore
import android.view.Gravity
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.addCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * Shuinkan for Android: the full app (Python) runs inside the APK on 127.0.0.1,
 * and this activity shows it full-screen in a WebView. Works offline; nothing leaves the phone
 * (except Wi-Fi sync, which you start yourself).
 */
class MainActivity : ComponentActivity() {
    private lateinit var root: FrameLayout
    private lateinit var web: WebView
    private lateinit var splash: View
    private lateinit var status: TextView
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    @Volatile private var currentUrl: String = ""
    private var lastBack = 0L
    private var pendingReminder: Triple<Boolean, Int, Int>? = null

    private val pickFile = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        fileCallback?.onReceiveValue(if (uri != null) arrayOf(uri) else null)
        fileCallback = null
    }

    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        val p = pendingReminder ?: return@registerForActivityResult
        pendingReminder = null
        Reminders.save(this, granted && p.first, p.second, p.third)
        if (!granted) Toast.makeText(this, getString(R.string.reminder_denied), Toast.LENGTH_LONG).show()
        web.evaluateJavascript("window.dispatchEvent(new Event('reminderchange'))", null)
    }

    @SuppressLint("SetJavaScriptEnabled", "JavascriptInterface")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Start the app's server first, while the window is still being built.
        val startPath = intent?.getStringExtra(EXTRA_OPEN) ?: lastPage()
        val restoring = savedInstanceState != null && ShuinkanServer.port != 0
        if (!restoring) Thread {
            try {
                val port = ShuinkanServer.ensureStarted(applicationContext) { msg -> runOnUiThread { status.text = msg } }
                runOnUiThread { web.loadUrl("http://127.0.0.1:$port$startPath") }
            } catch (e: Throwable) {
                runOnUiThread { status.text = getString(R.string.start_failed, e.message ?: "") }
            }
        }.start()  // UI updates are posted, so they run after onCreate has built the views
        // Edge to edge (required from Android 15): we pad the content for the bars and the keyboard ourselves.
        WindowCompat.setDecorFitsSystemWindows(window, false)
        root = FrameLayout(this)
        web = WebView(this)
        root.addView(web, FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT))
        splash = buildSplash()
        root.addView(splash, FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT))
        setContentView(root)
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))  // keyboard never covers the answer box
            WindowInsetsCompat.CONSUMED
        }
        setBarColors(Color.parseColor("#F7F3EC"), dark = isNightMode())

        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false   // deck audio autoplays, like Anki
            allowFileAccess = false
            allowContentAccess = true
            setSupportZoom(false)                      // no accidental double-tap zoom while tapping answers
            userAgentString = "$userAgentString ShuinkanAndroid/${BuildConfig.VERSION_NAME}"
        }
        web.overScrollMode = View.OVER_SCROLL_NEVER
        web.addJavascriptInterface(Bridge(), "ShuinkanAndroid")
        CookieManager.getInstance().setAcceptCookie(true)

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                if (url.host == "127.0.0.1") return false
                // Links to other sites (licences, GitHub…) open in the phone's browser.
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, url)) }
                return true
            }

            override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) {
                currentUrl = url
            }

            override fun onPageFinished(view: WebView, url: String) {
                currentUrl = url
                rememberPage(url)
                if (splash.visibility == View.VISIBLE) splash.animate().alpha(0f).setDuration(150)
                    .withEndAction { splash.visibility = View.GONE }
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>,
                                           params: FileChooserParams): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                pickFile.launch("*/*")  // .apkg / .zip / .csv aren't always recognised by MIME type
                return true
            }
        }
        web.setDownloadListener { url, _, disposition, mime, _ -> download(url, disposition, mime) }

        onBackPressedDispatcher.addCallback(this) { handleBack() }

        if (restoring) {
            web.restoreState(savedInstanceState!!)
            splash.visibility = View.GONE
        } else if (ShuinkanServer.port != 0) {
            splash.visibility = View.GONE  // already running (app reopened): no splash at all
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        val path = intent.getStringExtra(EXTRA_OPEN) ?: return
        if (ShuinkanServer.port != 0) web.loadUrl("http://127.0.0.1:${ShuinkanServer.port}$path")
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    // ------------------------------------------------------------ back button
    private fun inProgress(path: String): Boolean =
        path.startsWith("/review") || (path.startsWith("/quiz/") && !path.endsWith("/results")) ||
            Regex("^/learn/(hiragana|katakana)/\\d+$").matches(path) || path.startsWith("/write") || path.startsWith("/match")

    private fun handleBack() {
        val path = Uri.parse(web.url ?: "").path ?: ""
        if (inProgress(path)) {
            AlertDialog.Builder(this)
                .setTitle(R.string.leave_title)
                .setMessage(R.string.leave_message)
                .setPositiveButton(R.string.leave_yes) { _, _ -> goBack() }
                .setNegativeButton(R.string.leave_no, null)
                .show()
        } else goBack()
    }

    private fun goBack() {
        if (web.canGoBack()) { web.goBack(); return }
        val now = SystemClock.elapsedRealtime()
        if (now - lastBack < 2000) finish()
        else { lastBack = now; Toast.makeText(this, R.string.back_again, Toast.LENGTH_SHORT).show() }
    }

    // --------------------------------------------------------- remember page
    private fun rememberPage(url: String) {
        val u = Uri.parse(url)
        val path = u.path ?: return
        if (u.host != "127.0.0.1" || path.startsWith("/api/") || path in listOf("/logout", "/login", "/register") ||
            path.startsWith("/quiz/") || path.startsWith("/anki-")) return
        val full = path + (u.query?.let { "?$it" } ?: "")
        getSharedPreferences("shuinkan", Context.MODE_PRIVATE).edit().putString("lastPage", full).apply()
    }

    private fun lastPage(): String =
        getSharedPreferences("shuinkan", Context.MODE_PRIVATE).getString("lastPage", "/") ?: "/"

    // -------------------------------------------------------------- colours
    private fun isNightMode() = (resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK) ==
        android.content.res.Configuration.UI_MODE_NIGHT_YES

    private fun setBarColors(color: Int, dark: Boolean) {
        root.setBackgroundColor(color)  // shows through the transparent status and navigation bars
        window.setBackgroundDrawable(android.graphics.drawable.ColorDrawable(color))
        WindowInsetsControllerCompat(window, root).apply {
            isAppearanceLightStatusBars = !dark
            isAppearanceLightNavigationBars = !dark
        }
    }

    /** Called from the pages (static/js/app.js). Only our own pages are ever loaded in this WebView. */
    inner class Bridge {
        private fun ours() = Uri.parse(currentUrl).host == "127.0.0.1"

        @JavascriptInterface
        fun setBars(color: String, dark: Boolean) {
            if (!ours()) return
            val c = runCatching { Color.parseColor(color) }.getOrNull() ?: return
            runOnUiThread { setBarColors(c, dark) }
        }

        @JavascriptInterface
        fun getReminder(): String {
            val r = Reminders.load(this@MainActivity)
            return JSONObject().put("enabled", r.first).put("hour", r.second).put("minute", r.third)
                .put("allowed", notificationsAllowed()).toString()
        }

        @JavascriptInterface
        fun setReminder(enabled: Boolean, hour: Int, minute: Int) {
            if (!ours()) return
            val h = hour.coerceIn(0, 23)
            val m = minute.coerceIn(0, 59)
            runOnUiThread {
                if (enabled && !notificationsAllowed() && Build.VERSION.SDK_INT >= 33) {
                    pendingReminder = Triple(true, h, m)
                    askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                } else {
                    Reminders.save(this@MainActivity, enabled, h, m)
                }
            }
        }
    }

    private fun notificationsAllowed() = Build.VERSION.SDK_INT < 33 ||
        ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun buildSplash(): View {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(if (isNightMode()) Color.parseColor("#1A1816") else Color.parseColor("#F7F3EC"))
        }
        val icon = ImageView(this).apply { setImageResource(R.mipmap.ic_launcher) }
        box.addView(icon, LinearLayout.LayoutParams(dp(96), dp(96)))
        box.addView(ProgressBar(this), LinearLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT).apply { topMargin = dp(24) })
        status = TextView(this).apply {
            text = getString(R.string.starting)
            setTextColor(if (isNightMode()) Color.parseColor("#D9D2C7") else Color.parseColor("#4C463F"))
            textSize = 16f
            gravity = Gravity.CENTER
            setPadding(dp(24), dp(16), dp(24), 0)
        }
        box.addView(status, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        return box
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    /** Save exports (.apkg) to the phone's Downloads folder. */
    private fun download(url: String, disposition: String?, mime: String?) {
        val name = URLUtil.guessFileName(url, disposition, mime ?: "application/octet-stream")
        val cookie = CookieManager.getInstance().getCookie(url)
        Toast.makeText(this, getString(R.string.saving, name), Toast.LENGTH_SHORT).show()
        Thread {
            val msg = try {
                val conn = URL(url).openConnection() as HttpURLConnection
                if (cookie != null) conn.setRequestProperty("Cookie", cookie)
                conn.inputStream.use { input ->
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                        val values = ContentValues().apply {
                            put(MediaStore.Downloads.DISPLAY_NAME, name)
                            put(MediaStore.Downloads.MIME_TYPE, mime ?: "application/octet-stream")
                        }
                        val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                            ?: error("no Downloads folder")
                        contentResolver.openOutputStream(uri)!!.use { input.copyTo(it) }
                        getString(R.string.saved_downloads, name)
                    } else {
                        val dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)!!
                        File(dir, name).outputStream().use { input.copyTo(it) }
                        "${dir.path}/$name"
                    }
                }
            } catch (e: Exception) {
                getString(R.string.save_failed, name, e.message ?: "")
            }
            runOnUiThread { Toast.makeText(this, msg, Toast.LENGTH_LONG).show() }
        }.start()
    }

    companion object {
        const val EXTRA_OPEN = "open"
    }
}

/** Starts the Python app once per process and remembers its port. */
object ShuinkanServer {
    @Volatile var port = 0
        private set

    @Synchronized
    fun ensureStarted(ctx: Context, progress: (String) -> Unit): Int {
        if (port != 0) return port
        val res = File(ctx.filesDir, "shuinkan-res")
        val prefs = ctx.getSharedPreferences("shuinkan", Context.MODE_PRIVATE)
        if (prefs.getLong("resVersion", -1) != BuildConfig.VERSION_CODE.toLong() || !File(res, "data/content.db").exists()) {
            progress(ctx.getString(R.string.first_start))
            res.deleteRecursively()
            copyAssetDir(ctx, "shuinkan", res)
            prefs.edit().putLong("resVersion", BuildConfig.VERSION_CODE.toLong()).apply()
        }
        if (!Python.isStarted()) Python.start(AndroidPlatform(ctx))
        val data = File(ctx.filesDir, "data").apply { mkdirs() }
        port = Python.getInstance().getModule("shuinkan_android")
            .callAttr("start", res.absolutePath, data.absolutePath).toInt()
        return port
    }

    private fun copyAssetDir(ctx: Context, path: String, dest: File) {
        val am = ctx.assets
        val children = am.list(path) ?: emptyArray()
        if (children.isEmpty()) {  // a file
            dest.parentFile?.mkdirs()
            am.open(path).use { input -> dest.outputStream().use { input.copyTo(it, 1 shl 16) } }
            return
        }
        dest.mkdirs()
        for (c in children) copyAssetDir(ctx, "$path/$c", File(dest, c))
    }
}
