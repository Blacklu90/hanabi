package io.github.blacklu90.hanabi

import android.annotation.SuppressLint
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.view.Gravity
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.webkit.CookieManager
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
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * Hanabi for Android: the full Hanabi app (Python) runs inside the APK on 127.0.0.1,
 * and this activity shows it full-screen in a WebView. Works offline; nothing leaves the phone.
 */
class MainActivity : ComponentActivity() {
    private lateinit var web: WebView
    private lateinit var splash: View
    private lateinit var status: TextView
    private var fileCallback: ValueCallback<Array<Uri>>? = null

    private val pickFile = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        fileCallback?.onReceiveValue(if (uri != null) arrayOf(uri) else null)
        fileCallback = null
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = FrameLayout(this)
        web = WebView(this)
        root.addView(web, FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT))
        splash = buildSplash()
        root.addView(splash, FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT))
        setContentView(root)

        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false   // deck audio autoplays, like Anki
            allowFileAccess = false
            allowContentAccess = true
            textZoom = 100
            userAgentString = "$userAgentString HanabiAndroid/${BuildConfig.VERSION_NAME}"
        }
        CookieManager.getInstance().setAcceptCookie(true)

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                if (url.host == "127.0.0.1") return false
                // Links to other sites (licences, GitHub, VOICEVOX…) open in the phone's browser.
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, url)) }
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                if (splash.visibility == View.VISIBLE) splash.animate().alpha(0f).setDuration(200)
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

        onBackPressedDispatcher.addCallback(this) {
            if (web.canGoBack()) web.goBack() else { isEnabled = false; onBackPressedDispatcher.onBackPressed() }
        }

        if (savedInstanceState != null && HanabiServer.port != 0) {
            web.restoreState(savedInstanceState)
            splash.visibility = View.GONE
        } else {
            Thread {
                try {
                    val port = HanabiServer.ensureStarted(applicationContext) { msg -> runOnUiThread { status.text = msg } }
                    runOnUiThread { web.loadUrl("http://127.0.0.1:$port/") }
                } catch (e: Throwable) {
                    runOnUiThread { status.text = "Hanabi couldn't start:\n${e.message}" }
                }
            }.start()
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    private fun buildSplash(): View {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(Color.parseColor("#F7F3EC"))
        }
        val icon = ImageView(this).apply { setImageResource(R.mipmap.ic_launcher) }
        box.addView(icon, LinearLayout.LayoutParams(dp(96), dp(96)))
        box.addView(ProgressBar(this), LinearLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT).apply { topMargin = dp(24) })
        status = TextView(this).apply {
            text = getString(R.string.starting)
            setTextColor(Color.parseColor("#4C463F"))
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
        Toast.makeText(this, "Saving $name…", Toast.LENGTH_SHORT).show()
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
                        "Saved $name to Downloads"
                    } else {
                        val dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)!!
                        File(dir, name).outputStream().use { input.copyTo(it) }
                        "Saved to ${dir.path}/$name"
                    }
                }
            } catch (e: Exception) {
                "Couldn't save $name: ${e.message}"
            }
            runOnUiThread { Toast.makeText(this, msg, Toast.LENGTH_LONG).show() }
        }.start()
    }
}

/** Starts the Python app once per process and remembers its port. */
object HanabiServer {
    @Volatile var port = 0
        private set

    @Synchronized
    fun ensureStarted(ctx: Context, progress: (String) -> Unit): Int {
        if (port != 0) return port
        val res = File(ctx.filesDir, "hanabi-res")
        val prefs = ctx.getSharedPreferences("hanabi", Context.MODE_PRIVATE)
        if (prefs.getLong("resVersion", -1) != BuildConfig.VERSION_CODE.toLong() || !File(res, "data/content.db").exists()) {
            progress(ctx.getString(R.string.first_start))
            res.deleteRecursively()
            copyAssetDir(ctx, "hanabi", res)
            prefs.edit().putLong("resVersion", BuildConfig.VERSION_CODE.toLong()).apply()
        }
        if (!Python.isStarted()) Python.start(AndroidPlatform(ctx))
        val data = File(ctx.filesDir, "data").apply { mkdirs() }
        port = Python.getInstance().getModule("hanabi_android")
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
