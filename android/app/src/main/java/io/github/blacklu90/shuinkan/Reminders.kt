package io.github.blacklu90.shuinkan

import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.database.sqlite.SQLiteDatabase
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import java.io.File
import java.util.Calendar

/**
 * Optional daily reminder. At the chosen time we look straight into the app's database
 * (no need to start Python) and only notify when there is something to study.
 */
object Reminders {
    private const val CHANNEL = "daily"
    private const val PREFS = "shuinkan"

    fun load(ctx: Context): Triple<Boolean, Int, Int> {
        val p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return Triple(p.getBoolean("remind", false), p.getInt("remindHour", 19), p.getInt("remindMinute", 0))
    }

    fun save(ctx: Context, enabled: Boolean, hour: Int, minute: Int) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putBoolean("remind", enabled).putInt("remindHour", hour).putInt("remindMinute", minute).apply()
        schedule(ctx)
    }

    private fun pending(ctx: Context) = PendingIntent.getBroadcast(
        ctx, 1, Intent(ctx, ReminderReceiver::class.java),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    fun schedule(ctx: Context) {
        val am = ctx.getSystemService(AlarmManager::class.java) ?: return
        val pi = pending(ctx)
        am.cancel(pi)
        val (enabled, hour, minute) = load(ctx)
        if (!enabled) return
        val at = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, hour); set(Calendar.MINUTE, minute); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
            if (timeInMillis <= System.currentTimeMillis() + 30_000) add(Calendar.DAY_OF_YEAR, 1)
        }
        // Inexact: Android may shift it by a few minutes to save battery. No special alarm permission needed.
        am.setInexactRepeating(AlarmManager.RTC_WAKEUP, at.timeInMillis, AlarmManager.INTERVAL_DAY, pi)
    }

    /** (reviews due now, new cards waiting), straight from the database. */
    fun counts(ctx: Context): Pair<Int, Int> {
        val f = File(ctx.filesDir, "data/shuinkan.db")
        if (!f.exists()) return 0 to 0
        return try {
            SQLiteDatabase.openDatabase(f.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
                val now = (System.currentTimeMillis() / 1000).toString()
                val due = db.rawQuery("SELECT COUNT(*) FROM srs_cards WHERE total_reviews > 0 AND suspended = 0 AND due_at <= ? AND buried_until <= ?",
                    arrayOf(now, now)).use { c -> if (c.moveToFirst()) c.getInt(0) else 0 }
                val fresh = db.rawQuery("SELECT COUNT(*) FROM srs_cards WHERE total_reviews = 0 AND suspended = 0", null)
                    .use { c -> if (c.moveToFirst()) c.getInt(0) else 0 }
                due to fresh
            }
        } catch (e: Exception) { 0 to 0 }
    }

    fun notifyIfNeeded(ctx: Context) {
        val (due, fresh) = counts(ctx)
        val text = when {
            due > 0 -> ctx.resources.getQuantityString(R.plurals.reminder_due, due, due)
            fresh > 0 -> ctx.getString(R.string.reminder_new)
            else -> return
        }
        val nm = ctx.getSystemService(NotificationManager::class.java) ?: return
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, ctx.getString(R.string.reminder_channel), NotificationManager.IMPORTANCE_DEFAULT))
        }
        val open = PendingIntent.getActivity(ctx, 2,
            Intent(ctx, MainActivity::class.java).putExtra(MainActivity.EXTRA_OPEN, "/review")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(ctx, CHANNEL)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(ctx.getString(R.string.reminder_title))
            .setContentText(text)
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        try { NotificationManagerCompat.from(ctx).notify(1, n) } catch (e: SecurityException) { /* notifications turned off */ }
    }
}

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val done = goAsync()
        Thread { try { Reminders.notifyIfNeeded(ctx) } finally { done.finish() } }.start()
    }
}

/** Alarms are cleared when the phone restarts or the app is updated: set it again. */
class RescheduleReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) = Reminders.schedule(ctx)
}
