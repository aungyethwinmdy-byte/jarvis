package com.jarvis.android

import android.app.Notification
import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import java.util.Collections
import java.util.LinkedList

/**
 * JarvisNotificationListener intercepts and records incoming notifications in real-time,
 * allowing Jarvis to check and report new messages from Telegram, Viber, Facebook, etc.
 */
class JarvisNotificationListener : NotificationListenerService() {

    companion object {
        private const val TAG = "JarvisNotifListener"
        private const val MAX_HISTORY = 50

        @Volatile
        var instance: JarvisNotificationListener? = null
            private set

        private val notificationHistory = Collections.synchronizedList(LinkedList<Map<String, Any>>())

        fun isNotificationListenerEnabled(context: Context): Boolean {
            val packageName = context.packageName
            val flat = Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners")
            return flat != null && flat.contains(packageName)
        }

        fun getRecentNotifications(appFilter: String? = null): List<Map<String, Any>> {
            synchronized(notificationHistory) {
                if (appFilter.isNullOrBlank() || appFilter.equals("all", ignoreCase = true)) {
                    return notificationHistory.toList()
                }
                val filter = appFilter.trim().lowercase()
                return notificationHistory.filter { item ->
                    val pkg = (item["package"] as? String)?.lowercase() ?: ""
                    val app = (item["appName"] as? String)?.lowercase() ?: ""
                    val title = (item["title"] as? String)?.lowercase() ?: ""
                    pkg.contains(filter) || app.contains(filter) || title.contains(filter)
                }
            }
        }

        fun clearNotifications() {
            synchronized(notificationHistory) {
                notificationHistory.clear()
            }
        }
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        instance = this
        Log.d(TAG, "JarvisNotificationListener connected successfully")
        // Populate active notifications
        try {
            val active = activeNotifications ?: emptyArray()
            for (sbn in active) {
                recordNotification(sbn)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Error populating active notifications: ${e.message}")
        }
    }

    override fun onListenerDisconnected() {
        super.onListenerDisconnected()
        instance = null
        Log.d(TAG, "JarvisNotificationListener disconnected")
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        super.onNotificationPosted(sbn)
        if (sbn == null) return
        recordNotification(sbn)
    }

    private fun recordNotification(sbn: StatusBarNotification) {
        try {
            val pkg = sbn.packageName ?: return
            // Ignore system/ambient notifications and Jarvis's own notifications
            if (pkg == packageName || pkg == "android" || pkg == "com.android.systemui") {
                return
            }

            val extras = sbn.notification.extras ?: return
            val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.trim() ?: ""
            val text = (extras.getCharSequence(Notification.EXTRA_BIG_TEXT)
                ?: extras.getCharSequence(Notification.EXTRA_TEXT))?.toString()?.trim() ?: ""
            val subText = extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString()?.trim() ?: ""

            // Skip empty notifications
            if (title.isEmpty() && text.isEmpty()) {
                return
            }

            // Guard: Never record banking, payment, or financial notifications
            val lowerPkg = pkg.lowercase()
            val sensitiveBankKeywords = listOf(
                "bank", "kpay", "kbzpay", "ayapay", "wavepay", "wavemoney", "uabpay", "cbbank", "cbpay",
                "onepay", "authenticator", "wallet", "trustwallet", "binance"
            )
            if (sensitiveBankKeywords.any { lowerPkg.contains(it) }) {
                Log.d(TAG, "Guard dropped notification from banking/financial app: $pkg")
                return
            }

            // Guard: Never record OTP, PIN, or verification codes
            val fullText = "$title $text $subText".lowercase()
            val otpKeywords = listOf(
                "otp", "one-time", "verification code", "security code", "passcode",
                "secret code", "auth code", "confirmation code", "pin code",
                "လျှို့ဝှက်ကုဒ်", "အတည်ပြုကုဒ်", "လုံခြုံရေးကုဒ်"
            )
            if (otpKeywords.any { fullText.contains(it) }) {
                Log.d(TAG, "Guard dropped notification containing OTP/PIN/verification code")
                return
            }

            val appName = try {
                val pm = packageManager
                val ai = pm.getApplicationInfo(pkg, 0)
                pm.getApplicationLabel(ai).toString()
            } catch (e: Exception) {
                pkg
            }

            val item = mapOf(
                "package" to pkg,
                "appName" to appName,
                "title" to title,
                "text" to text,
                "subText" to subText,
                "postTime" to sbn.postTime,
                "isOngoing" to sbn.isOngoing
            )

            synchronized(notificationHistory) {
                // Avoid rapid duplicates
                val firstItem = notificationHistory.firstOrNull()
                val isDuplicate = firstItem != null &&
                        firstItem["package"] == pkg &&
                        firstItem["title"] == title &&
                        firstItem["text"] == text
                if (!isDuplicate) {
                    notificationHistory.add(0, item)
                    if (notificationHistory.size > MAX_HISTORY) {
                        notificationHistory.removeAt(notificationHistory.size - 1)
                    }
                    Log.d(TAG, "Notification recorded from $appName: [$title] $text")
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Error recording notification: ${e.message}")
        }
    }
}
