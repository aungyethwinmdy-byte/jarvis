package com.jarvis.android

import android.Manifest
import android.app.ActivityOptions
import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.PixelFormat
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.Uri
import android.os.BatteryManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.AlarmClock
import android.provider.ContactsContract
import android.provider.MediaStore
import android.provider.Settings
import android.telecom.PhoneAccountHandle
import android.telecom.TelecomManager
import android.telephony.SubscriptionInfo
import android.telephony.SubscriptionManager
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat

/**
 * WindowOverlayManager attaches a minimal 1x1 transparent overlay to the WindowManager
 * when SYSTEM_ALERT_WINDOW is granted. This satisfies Android 14+ / 16 Background Activity
 * Launch restrictions by setting callingUidHasNonAppVisibleWindow = true (BAL_ALLOW_VISIBLE_WINDOW).
 */
object WindowOverlayManager {
    private const val TAG = "WindowOverlayManager"
    @Volatile
    private var overlayView: View? = null

    fun ensureOverlay(context: Context) {
        if (overlayView != null) return
        Handler(Looper.getMainLooper()).post {
            if (overlayView != null) return@post
            try {
                val appContext = context.applicationContext
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(appContext)) {
                    Log.w(TAG, "canDrawOverlays is false, skipping overlay creation")
                    return@post
                }
                val wm = appContext.getSystemService(Context.WINDOW_SERVICE) as WindowManager
                val view = View(appContext)
                val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                } else {
                    @Suppress("DEPRECATION")
                    WindowManager.LayoutParams.TYPE_PHONE
                }
                val params = WindowManager.LayoutParams(
                    1, 1,
                    type,
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                            WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                            WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                    PixelFormat.TRANSLUCENT
                ).apply {
                    gravity = Gravity.TOP or Gravity.START
                    x = 0
                    y = 0
                }
                wm.addView(view, params)
                overlayView = view
                Log.d(TAG, "Transparent overlay window active -> callingUidHasNonAppVisibleWindow = true (BAL_ALLOW)")
            } catch (e: Exception) {
                Log.w(TAG, "ensureOverlay failed: ${e.message}")
            }
        }
    }
}

class DeviceController(private val context: Context) {

    companion object {
        private const val TAG = "DeviceController"
        @Volatile
        var lastCapturedPhoto: Map<String, Any>? = null
    }

    private val audioRecorder = JarvisAudioRecorder(context)

    init {
        WindowOverlayManager.ensureOverlay(context)
        try {
            val filter = IntentFilter("com.jarvis.android.ACTION_TEST_OPEN_APP")
            val receiver = object : BroadcastReceiver() {
                override fun onReceive(c: Context, i: Intent) {
                    val act = i.getStringExtra("action") ?: "open_app"
                    val q = i.getStringExtra("query") ?: ""
                    Log.d(TAG, "Test broadcast received: action=$act, query=$q")
                    when (act) {
                        "youtube" -> playYouTube(q)
                        "camera_photo" -> takeCameraPhoto()
                        "check_messages" -> {
                            val res = checkMessages(q)
                            Log.d(TAG, "Test check_messages result: $res")
                        }
                        "record_start" -> manageAudioRecording("start")
                        "record_stop" -> manageAudioRecording("stop")
                        "inspect_screen" -> {
                            val res = inspectScreen()
                            Log.d(TAG, "Test inspect_screen result: $res")
                        }
                        "control_screen" -> controlScreen(i.getStringExtra("control_action") ?: "scroll_down", q)
                        else -> openApp(q)
                    }
                }
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                context.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED)
            } else {
                context.registerReceiver(receiver, filter)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Could not register test broadcast receiver: ${e.message}")
        }
    }

    /**
     * Turn the flashlight / torch on or off using CameraManager.
     */
    fun toggleTorch(enable: Boolean): Map<String, Any> {
        return try {
            val cm = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val cameraId = cm.cameraIdList.firstOrNull { id ->
                cm.getCameraCharacteristics(id).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
            } ?: return mapOf(
                "success" to false,
                "message" to "ဤဖုန်းတွင် ဓာတ်မီး (Flashlight) မပါဝင်ပါ ခင်ဗျာ။"
            )

            cm.setTorchMode(cameraId, enable)
            val actionText = if (enable) "ဖွင့်" else "ပိတ်"
            mapOf(
                "success" to true,
                "message" to "ဓာတ်မီးကို $actionText ပေးလိုက်ပါပြီ ခင်ဗျာ။"
            )
        } catch (e: Exception) {
            val msg = e.message ?: ""
            mapOf(
                "success" to false,
                "message" to "ဓာတ်မီး ထိန်းချုပ်ရာတွင် အခက်အခဲရှိပါသည်: $msg"
            )
        }
    }

    /**
     * Set volume level (0-100%) for the specified stream (media, ring, alarm, notification, call).
     */
    fun setVolume(stream: String, percent: Int): Map<String, Any> {
        val streamType = when (stream.lowercase().trim()) {
            "ring", "ringer" -> AudioManager.STREAM_RING
            "alarm" -> AudioManager.STREAM_ALARM
            "notification" -> AudioManager.STREAM_NOTIFICATION
            "call", "voice" -> AudioManager.STREAM_VOICE_CALL
            else -> AudioManager.STREAM_MUSIC
        }
        return try {
            val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            val max = am.getStreamMaxVolume(streamType)
            val clamped = percent.coerceIn(0, 100)
            val target = (clamped * max) / 100
            am.setStreamVolume(streamType, target, AudioManager.FLAG_SHOW_UI)
            val actualPct = (am.getStreamVolume(streamType) * 100) / max
            mapOf(
                "success" to true,
                "percent" to actualPct,
                "message" to "အသံပမာဏကို $actualPct% သို့ သတ်မှတ်ပေးလိုက်ပါပြီ ခင်ဗျာ။"
            )
        } catch (e: Exception) {
            mapOf(
                "success" to false,
                "message" to "အသံပမာဏ ပြောင်းလဲ၍ မရပါ: ${e.message}"
            )
        }
    }

    /**
     * Read current volume level.
     */
    fun getVolume(stream: String?): Map<String, Any> {
        return try {
            val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            val max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
            val current = am.getStreamVolume(AudioManager.STREAM_MUSIC)
            val pct = (current * 100) / max
            mapOf(
                "success" to true,
                "percent" to pct,
                "message" to "လက်ရှိ မီဒီယာအသံပမာဏသည် $pct% ဖြစ်ပါသည် ခင်ဗျာ။"
            )
        } catch (e: Exception) {
            mapOf(
                "success" to false,
                "message" to "အသံပမာဏ စစ်ဆေး၍ မရပါ: ${e.message}"
            )
        }
    }

    /**
     * Open an app installed on the phone by its name or package.
     */
    fun openApp(query: String): Map<String, Any> {
        val q = query.trim().lowercase()
        Log.d(TAG, "openApp request query: '$query', normalized: '$q'")
        if (q.isEmpty()) {
            return mapOf(
                "success" to false,
                "message" to "ဖွင့်မည့် အက်ပ်အမည် မပါဝင်ပါ ခင်ဗျာ။"
            )
        }

        // Ensure BAL overlay is active if permitted
        WindowOverlayManager.ensureOverlay(context)

        val pm = context.packageManager

        try {
            var targetIntent: Intent? = null
            var appLabel = query.trim()

            // 1. Direct System Intent Handlers for Core Functions
            when {
                // Camera: prioritize explicit package to launch real Camera activity (not AssistantCamera stub)
                q.contains("camera") || q.contains("ကင်မရာ") || q.contains("ဓာတ်ပုံရိုက်") || q.contains("ဓါတ်ပုံရိုက်") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.android.camera")
                        ?: pm.getLaunchIntentForPackage("com.google.android.GoogleCamera")
                        ?: Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA)
                    appLabel = "Camera (ကင်မရာ)"
                }
                // Settings: prioritize explicit package to launch MainSettings directly
                q.contains("setting") || q.contains("ဆက်တင်") || q.contains("ချိန်ညှိ") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.android.settings")
                        ?: pm.getLaunchIntentForPackage("com.miui.securitycenter")
                        ?: Intent(Settings.ACTION_SETTINGS)
                    appLabel = "Settings (ဆက်တင်)"
                }
                // YouTube
                q.contains("youtube") || q.contains("ယူကျူ") || q.contains("ယူကျု") || q.contains("yt") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.google.android.youtube")
                        ?: pm.getLaunchIntentForPackage("com.google.android.apps.youtube.mango")
                        ?: pm.getLaunchIntentForPackage("app.revanced.android.youtube")
                        ?: Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com"))
                    appLabel = "YouTube"
                }
                // Facebook
                q.contains("facebook") || q.contains("ဖေ့ဘုတ်") || q.contains("ဖေ့စ်ဘွတ်") || q.contains("ဖေ့စ်ဘုတ်") || q.contains("ဖေ့ဘွတ်") || q.contains("fb") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.facebook.katana")
                        ?: pm.getLaunchIntentForPackage("com.facebook.lite")
                        ?: Intent(Intent.ACTION_VIEW, Uri.parse("https://www.facebook.com"))
                    appLabel = "Facebook"
                }
                // Telegram
                q.contains("telegram") || q.contains("တယ်လီဂရမ်") || q.contains("တဲလီဂရမ်") || q.contains("တေလီဂရမ်") -> {
                    targetIntent = pm.getLaunchIntentForPackage("org.telegram.messenger")
                        ?: pm.getLaunchIntentForPackage("org.telegram.plus")
                        ?: pm.getLaunchIntentForPackage("org.thunderdog.challegram")
                    appLabel = "Telegram"
                }
                // Messenger
                q.contains("messenger") || q.contains("မက်ဆင်ဂျာ") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.facebook.orca")
                        ?: pm.getLaunchIntentForPackage("com.facebook.mlite")
                    appLabel = "Messenger"
                }
                // Viber
                q.contains("viber") || q.contains("ဗိုက်ဘာ") || q.contains("ဗိုင်ဘာ") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.viber.voip")
                    appLabel = "Viber"
                }
                // TikTok
                q.contains("tiktok") || q.contains("တစ်တော့") || q.contains("တစ်တော") || q.contains("တစ်တော့ခ်") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.zhiliaoapp.musically")
                        ?: pm.getLaunchIntentForPackage("com.ss.android.ugc.trill")
                    appLabel = "TikTok"
                }
                // Chrome / Web Browser
                q.contains("chrome") || q.contains("browser") || q.contains("ဘရောက်ဇာ") || q.contains("ခရုမ်း") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.android.chrome")
                        ?: Intent(Intent.ACTION_VIEW, Uri.parse("https://www.google.com"))
                    appLabel = "Chrome"
                }
                // Google Maps
                q.contains("map") || q.contains("မြေပုံ") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.google.android.apps.maps")
                        ?: Intent(Intent.ACTION_VIEW, Uri.parse("geo:0,0"))
                    appLabel = "Maps"
                }
                // Gallery / Photos
                q.contains("gallery") || q.contains("photo") || q.contains("ဓာတ်ပုံကြည့်") || q.contains("ပုံများ") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.miui.gallery")
                        ?: pm.getLaunchIntentForPackage("com.google.android.apps.photos")
                        ?: pm.getLaunchIntentForPackage("com.android.gallery3d")
                        ?: Intent(Intent.ACTION_VIEW).setType("image/*")
                    appLabel = "Gallery (ဓာတ်ပုံများ)"
                }
                // Calculator
                q.contains("calculator") || q.contains("ဂဏန်းပေါင်းစက်") || q.contains("ဂဏန်းတွက်") || q.contains("တွက်စက်") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.miui.calculator")
                        ?: pm.getLaunchIntentForPackage("com.google.android.calculator")
                        ?: pm.getLaunchIntentForPackage("com.android.calculator2")
                    appLabel = "Calculator (ဂဏန်းပေါင်းစက်)"
                }
                // Clock / Alarm
                q.contains("clock") || q.contains("alarm") || q.contains("နာရီ") || q.contains("နှိုးစက်") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.google.android.deskclock")
                        ?: pm.getLaunchIntentForPackage("com.android.deskclock")
                        ?: Intent(AlarmClock.ACTION_SHOW_ALARMS)
                    appLabel = "Clock (နာရီ)"
                }
                // Sound Recorder
                q.contains("recorder") || q.contains("အသံဖမ်း") || q.contains("voice recorder") || q.contains("sound recorder") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.android.soundrecorder")
                        ?: pm.getLaunchIntentForPackage("com.miui.soundrecorder")
                        ?: pm.getLaunchIntentForPackage("com.google.android.apps.recorder")
                    appLabel = "Sound Recorder (အသံဖမ်းစက်)"
                }
                // Dialer / Phone Call
                q.contains("phone") || q.contains("call") || q.contains("ဖုန်းခေါ်") || q.contains("ဖုန်းဆက်") -> {
                    targetIntent = Intent(Intent.ACTION_DIAL)
                    appLabel = "Phone (ဖုန်းခေါ်ဆိုမှု)"
                }
                // Play Store
                q.contains("play store") || q.contains("playstore") || q.contains("store") || q.contains("စတိုး") -> {
                    targetIntent = pm.getLaunchIntentForPackage("com.android.vending")
                    appLabel = "Play Store"
                }
            }

            // 2. If not a recognized direct shortcut, try package name directly
            if (targetIntent == null) {
                targetIntent = pm.getLaunchIntentForPackage(query.trim())
            }

            // 3. Fallback: Search all installed launcher activities
            if (targetIntent == null) {
                val launcherIntent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
                val resolveInfos = pm.queryIntentActivities(launcherIntent, 0)
                val match = resolveInfos.firstOrNull {
                    val label = it.loadLabel(pm).toString().lowercase()
                    val pkg = it.activityInfo.packageName.lowercase()
                    label.contains(q) || pkg.contains(q)
                }
                if (match != null) {
                    targetIntent = pm.getLaunchIntentForPackage(match.activityInfo.packageName)
                    appLabel = match.loadLabel(pm).toString()
                }
            }

            // 4. Also try search in all installed applications
            if (targetIntent == null) {
                val installedApps = pm.getInstalledApplications(0)
                val appMatch = installedApps.firstOrNull {
                    val label = pm.getApplicationLabel(it).toString().lowercase()
                    val pkg = it.packageName.lowercase()
                    label.contains(q) || pkg.contains(q)
                }
                if (appMatch != null) {
                    targetIntent = pm.getLaunchIntentForPackage(appMatch.packageName)
                    appLabel = pm.getApplicationLabel(appMatch).toString()
                }
            }

            if (targetIntent != null) {
                launchIntentSafely(targetIntent, appLabel)
                Log.d(TAG, "openApp completed launch sequence for: $appLabel")
                return mapOf(
                    "success" to true,
                    "message" to "$appLabel အက်ပ်ကို ဖွင့်ပေးလိုက်ပါပြီ ခင်ဗျာ။"
                )
            }

            Log.w(TAG, "openApp could not find any app matching: $query")
            return mapOf(
                "success" to false,
                "message" to "'$query' အမည်ရှိ အက်ပ်ကို ရှာမတွေ့ပါ ခင်ဗျာ။"
            )
        } catch (e: Exception) {
            Log.e(TAG, "openApp exception: ${e.message}", e)
            return mapOf(
                "success" to false,
                "message" to "အက်ပ်ဖွင့်ရာတွင် အမှားဖြစ်ပွားပါသည်: ${e.message}"
            )
        }
    }

    /**
     * Reliable multi-strategy intent launcher supporting Android 14+ background activity starts.
     */
    fun launchIntentSafely(targetIntent: Intent, appLabel: String): Boolean {
        WindowOverlayManager.ensureOverlay(context)
        targetIntent.addFlags(
            Intent.FLAG_ACTIVITY_NEW_TASK or
            Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED or
            Intent.FLAG_ACTIVITY_CLEAR_TOP
        )

        val options = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ActivityOptions.makeBasic().apply {
                setPendingIntentBackgroundActivityStartMode(
                    ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED
                )
            }
        } else {
            ActivityOptions.makeBasic()
        }
        val optionsBundle = options.toBundle()

        // Strategy 1: Direct startActivity with ActivityOptions
        try {
            context.startActivity(targetIntent, optionsBundle)
            Log.d(TAG, "Direct startActivity dispatched for: $appLabel")
        } catch (e: Exception) {
            Log.w(TAG, "Direct startActivity failed: ${e.message}")
        }

        // Strategy 2: PendingIntent with MODE_BACKGROUND_ACTIVITY_START_ALLOWED
        try {
            val requestCode = (System.currentTimeMillis() % 100000).toInt()
            val pi = PendingIntent.getActivity(
                context,
                requestCode,
                targetIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            pi.send(context, 0, null, null, null, null, optionsBundle)
            Log.d(TAG, "PendingIntent send dispatched for: $appLabel")
        } catch (pe: Exception) {
            Log.w(TAG, "PendingIntent send failed: ${pe.message}")
        }

        // Strategy 3: FullScreenIntent Notification Trampoline fallback
        launchViaFullScreenNotification(context, targetIntent, appLabel)
        return true
    }

    private fun launchViaFullScreenNotification(context: Context, intent: Intent, title: String) {
        try {
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val channelId = "jarvis_app_launcher_channel"
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val channel = NotificationChannel(
                    channelId,
                    "Jarvis App Launcher",
                    NotificationManager.IMPORTANCE_HIGH
                ).apply {
                    description = "Instant app launcher for voice assistant"
                    lockscreenVisibility = android.app.Notification.VISIBILITY_PUBLIC
                }
                nm.createNotificationChannel(channel)
            }

            val requestCode = 9991
            val pi = PendingIntent.getActivity(
                context,
                requestCode,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            val iconRes = context.applicationInfo.icon.let {
                if (it != 0) it else android.R.drawable.ic_dialog_info
            }

            val notif = NotificationCompat.Builder(context, channelId)
                .setSmallIcon(iconRes)
                .setContentTitle("JARVIS")
                .setContentText("$title အက်ပ်ကို ဖွင့်နေပါသည်...")
                .setPriority(NotificationCompat.PRIORITY_MAX)
                .setCategory(NotificationCompat.CATEGORY_ALARM)
                .setFullScreenIntent(pi, true)
                .setContentIntent(pi)
                .setAutoCancel(true)
                .build()

            nm.notify(9999, notif)

            // Auto dismiss notification after a brief delay
            Handler(Looper.getMainLooper()).postDelayed({
                try {
                    nm.cancel(9999)
                } catch (_: Exception) {}
            }, 2500)
        } catch (e: Exception) {
            Log.w(TAG, "launchViaFullScreenNotification failed: ${e.message}")
        }
    }

    /**
     * Get device status (battery capacity, charging state, temperature, volume, ringer mode).
     */
    fun getDeviceStatus(): Map<String, Any> {
        return try {
            val bm = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
            val capacity = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)

            val batteryIntent = context.registerReceiver(
                null,
                IntentFilter(Intent.ACTION_BATTERY_CHANGED)
            )
            val status = batteryIntent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
            val plugged = batteryIntent?.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1) ?: -1
            val tempRaw = batteryIntent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) ?: -1
            val tempC = if (tempRaw > 0) tempRaw / 10.0 else null

            val isCharging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
                             status == BatteryManager.BATTERY_STATUS_FULL
            val pluggedType = when (plugged) {
                BatteryManager.BATTERY_PLUGGED_AC -> "AC အားသွင်းကြိုး"
                BatteryManager.BATTERY_PLUGGED_USB -> "USB"
                BatteryManager.BATTERY_PLUGGED_WIRELESS -> "ကြိုးမဲ့အားသွင်းစနစ်"
                else -> if (isCharging) "အားသွင်းနေသည်" else "အားမသွင်းပါ"
            }

            val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            val musicMax = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
            val musicCur = am.getStreamVolume(AudioManager.STREAM_MUSIC)
            val musicPct = (musicCur * 100) / musicMax

            val ringerMode = when (am.ringerMode) {
                AudioManager.RINGER_MODE_SILENT -> "အသံတိတ် (Silent)"
                AudioManager.RINGER_MODE_VIBRATE -> "တုန်ခါမှု (Vibrate)"
                else -> "သာမန် (Normal)"
            }

            val chargingText = if (isCharging) "အားသွင်းနေပါသည် ($pluggedType)" else "ဘက်ထရီဖြင့် အသုံးပြုနေပါသည်"
            val tempText = if (tempC != null) "၊ အပူချိန် ${tempC}°C" else ""
            val summary = "လက်ရှိ ဘက်ထရီ $capacity% ရှိပြီး $chargingText$tempText။ မီဒီယာ အသံပမာဏသည် $musicPct% ဖြစ်ပြီး ဖုန်းသံစနစ်သည် $ringerMode ဖြစ်ပါသည် ခင်ဗျာ။"

            mapOf(
                "success" to true,
                "batteryPercent" to capacity,
                "isCharging" to isCharging,
                "pluggedType" to pluggedType,
                "temperature" to (tempC ?: 0.0),
                "mediaVolumePercent" to musicPct,
                "ringerMode" to ringerMode,
                "summary" to summary
            )
        } catch (e: Exception) {
            mapOf(
                "success" to false,
                "message" to "စက်ပစ္စည်း အခြေအနေ စစ်ဆေး၍ မရပါ: ${e.message}"
            )
        }
    }

    /**
     * Schedule a reliable reminder via Android AlarmManager exact alarm while idle.
     */
    fun setReminder(title: String, delaySeconds: Int): Map<String, Any> {
        return try {
            val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val intent = Intent(context, ReminderReceiver::class.java).apply {
                putExtra("title", title)
            }
            val requestCode = (System.currentTimeMillis() % 100000).toInt()
            val pendingIntent = PendingIntent.getBroadcast(
                context,
                requestCode,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            val triggerAtMillis = System.currentTimeMillis() + (delaySeconds.coerceAtLeast(2) * 1000L)

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                alarmManager.setExactAndAllowWhileIdle(
                    AlarmManager.RTC_WAKEUP,
                    triggerAtMillis,
                    pendingIntent
                )
            } else {
                alarmManager.setExact(
                    AlarmManager.RTC_WAKEUP,
                    triggerAtMillis,
                    pendingIntent
                )
            }

            val timeDesc = if (delaySeconds < 60) "$delaySeconds စက္ကန့်" else "${delaySeconds / 60} မိနစ်"
            mapOf(
                "success" to true,
                "message" to "ဆရာ့အတွက် '$title' သတိပေးချက်ကို $timeDesc အကြာတွင် ဖုန်းပေါ်၌ တိကျစွာ သတ်မှတ်ပေးထားပြီး ဖြစ်ပါသည် ခင်ဗျာ။"
            )
        } catch (e: Exception) {
            mapOf(
                "success" to false,
                "message" to "သတိပေးချက် သတ်မှတ်ရာတွင် အမှားဖြစ်ပွားပါသည်: ${e.message}"
            )
        }
    }

    /**
     * Play or search for music/video on YouTube directly.
     */
    fun playYouTube(query: String): Map<String, Any> {
        return try {
            val q = query.trim()
            val targetIntent = if (q.isNotEmpty()) {
                Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com/results?search_query=${Uri.encode(q)}")).apply {
                    setPackage("com.google.android.youtube")
                }
            } else {
                context.packageManager.getLaunchIntentForPackage("com.google.android.youtube")
                    ?: Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com"))
            }
            val label = if (q.isNotEmpty()) "YouTube: $q" else "YouTube"
            launchIntentSafely(targetIntent, label)
            val msg = if (q.isNotEmpty()) {
                "YouTube တွင် '$q' ကို ရှာဖွေဖွင့်ပေးလိုက်ပါပြီ ခင်ဗျာ။"
            } else {
                "YouTube အက်ပ်ကို ဖွင့်ပေးလိုက်ပါပြီ ခင်ဗျာ။"
            }
            mapOf("success" to true, "message" to msg)
        } catch (e: Exception) {
            mapOf("success" to false, "message" to "YouTube ဖွင့်ရာတွင် အခက်အခဲရှိပါသည်: ${e.message}")
        }
    }

    /**
     * Open camera and trigger photo shutter capture automatically using Jarvis native CameraX.
     * Supports both back camera ("back", default) and front camera ("front" / "selfie").
     */
    fun takeCameraPhoto(camera: String? = "back"): Map<String, Any> {
        val hasCamPerm = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        if (!hasCamPerm) {
            Log.w(TAG, "takeCameraPhoto failed: CAMERA permission not granted")
            return mapOf(
                "success" to false,
                "permissionDenied" to true,
                "message" to "ကင်မရာ permission လိုနေပါတယ် ခင်ဗျာ။ ကျေးဇူးပြု၍ Settings ထဲတွင် Camera permission ပေးပါ ခင်ဗျာ။"
            )
        }

        val cam = camera?.trim()?.lowercase() ?: "back"
        val isFront = cam.contains("front") || cam.contains("selfie") || cam.contains("ရှေ့")
        val lensLabel = if (isFront) "ရှေ့ကင်မရာ (Front)" else "နောက်ကင်မရာ (Back)"

        return try {
            val intent = Intent(context, CameraActivity::class.java).apply {
                putExtra("auto_capture", true)
                putExtra("camera", if (isFront) "front" else "back")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            }
            launchIntentSafely(intent, "Jarvis Camera")

            mapOf(
                "success" to true,
                "camera" to if (isFront) "front" else "back",
                "message" to "$lensLabel ဖြင့် ဓာတ်ပုံရိုက်ကူးပေးနေပါပြီ ခင်ဗျာ။ Gallery ထဲတွင် တိုက်ရိုက် သိမ်းဆည်းပေးမည် ဖြစ်ပါသည် ခင်ဗျာ။"
            )
        } catch (e: Exception) {
            Log.e(TAG, "takeCameraPhoto failed: ${e.message}", e)
            mapOf("success" to false, "message" to "ကင်မရာ ဓာတ်ပုံရိုက်ရာတွင် အခက်အခဲရှိပါသည်: ${e.message}")
        }
    }

    /**
     * Inspect incoming notifications for new messages (Telegram, Viber, Facebook, Messenger, etc.).
     */
    fun checkMessages(appFilter: String?): Map<String, Any> {
        return try {
            // Guard: Check Notification Listener permission
            if (!JarvisNotificationListener.isNotificationListenerEnabled(context)) {
                Log.w(TAG, "checkMessages: Notification Listener permission is disabled")
                return mapOf(
                    "success" to false,
                    "permissionDenied" to true,
                    "count" to 0,
                    "messages" to emptyList<Map<String, Any>>(),
                    "summary" to "Settings > Notifications > Jarvis ကို ခွင့်ပြုပေးပါ ခင်ဗျာ။"
                )
            }

            val filter = appFilter?.trim()?.lowercase() ?: "all"
            val notifs = JarvisNotificationListener.getRecentNotifications(filter)

            val isFacebookQuery = filter.contains("face") || filter.contains("fb")
            if (isFacebookQuery) {
                val fbNotifs = notifs.filter {
                    val pkg = (it["package"] as? String)?.lowercase() ?: ""
                    pkg == "com.facebook.katana" || pkg == "com.facebook.lite" || pkg == "com.facebook.orca"
                }

                if (fbNotifs.isEmpty()) {
                    return mapOf(
                        "success" to true,
                        "count" to 0,
                        "messages" to emptyList<Map<String, Any>>(),
                        "summary" to "Facebook တွင် notification အသစ် မရှိပါ ခင်ဗျာ။"
                    )
                }

                val details = fbNotifs.take(5).map { item ->
                    val sender = item["title"] ?: ""
                    val content = item["text"] ?: ""
                    val lower = "$sender $content".lowercase()
                    val type = when {
                        lower.contains("comment") || lower.contains("replied") || lower.contains("မှတ်ချက်") -> "မှတ်ချက် (Comment)"
                        lower.contains("tag") || lower.contains("mentioned") -> "Tag / Mention"
                        lower.contains("message") || lower.contains("မက်ဆင်ဂျာ") -> "မက်ဆေ့ခ်ျ"
                        lower.contains("react") || lower.contains("like") -> "Reaction"
                        lower.contains("friend") -> "Friend Request"
                        else -> "သတိပေးချက်"
                    }
                    "• $sender မှ $type: $content"
                }.joinToString("\n")

                val summary = "Facebook တွင် notification အသစ် ${fbNotifs.size} ခု တက်နေပါသည် ခင်ဗျာ:\n$details"
                return mapOf(
                    "success" to true,
                    "count" to fbNotifs.size,
                    "messages" to fbNotifs.take(10),
                    "summary" to summary
                )
            }

            val appLabel = when {
                filter.contains("tele") -> "Telegram"
                filter.contains("viber") -> "Viber"
                filter.contains("mess") -> "Messenger"
                else -> if (filter == "all") "အက်ပ်များ" else filter
            }

            if (notifs.isEmpty()) {
                return mapOf(
                    "success" to true,
                    "count" to 0,
                    "messages" to emptyList<Map<String, Any>>(),
                    "summary" to "လက်ရှိတွင် $appLabel မှ notification အသစ် မရှိပါ ခင်ဗျာ။"
                )
            }

            val count = notifs.size
            val topList = notifs.take(5).map { item ->
                val sender = item["title"] ?: ""
                val content = item["text"] ?: ""
                val app = item["appName"] ?: ""
                "[$app] $sender: $content"
            }
            val detailStr = topList.joinToString("\n")
            val summary = "လက်ရှိတွင် $appLabel မှ စာအသစ် $count စောင် တွေ့ရှိပါသည်:\n$detailStr\nဖြစ်ပါသည် ခင်ဗျာ။"

            mapOf(
                "success" to true,
                "count" to count,
                "messages" to notifs.take(10),
                "summary" to summary
            )
        } catch (e: Exception) {
            mapOf("success" to false, "summary" to "စာအသစ် စစ်ဆေးရာတွင် အခက်အခဲရှိပါသည်: ${e.message}")
        }
    }

    /**
     * Open Android system Accessibility settings so the user can grant permission.
     */
    fun openAccessibilitySettings(): Map<String, Any> {
        return try {
            val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
            mapOf("success" to true)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to open accessibility settings: ${e.message}")
            mapOf("success" to false, "message" to (e.message ?: ""))
        }
    }

    /**
     * Read on-screen UI text and content (e.g. Facebook feed, browser, chat).
     */
    fun inspectScreen(): Map<String, Any> {
        val a11y = JarvisAccessibilityService.instance
        if (a11y == null) {
            try {
                openAccessibilitySettings()
            } catch (_: Exception) {}
            return mapOf(
                "success" to false,
                "message" to "JARVIS Accessibility Service ကို ဖွင့်ထားခြင်း မရှိပါ ခင်ဗျာ။ Settings ထဲတွင် ခွင့်ပြုပေးနိုင်ရန် ဖွင့်လှစ်ပေးထားပါသည် ခင်ဗျာ။",
                "textSummary" to ""
            )
        }
        var res = a11y.getScreenContent()
        var pkg = (res["packageName"] as? String)?.lowercase() ?: ""

        // If currently in Jarvis and an app transition might be occurring, retry up to 3 times (with 400ms delay) to let target app appear
        if (pkg.contains("com.jarvis.android")) {
            for (retry in 1..3) {
                try { Thread.sleep(400) } catch (_: Exception) {}
                val nextRes = a11y.getScreenContent()
                val nextPkg = (nextRes["packageName"] as? String)?.lowercase() ?: ""
                if (!nextPkg.contains("com.jarvis.android") && nextPkg.isNotEmpty()) {
                    res = nextRes
                    pkg = nextPkg
                    break
                }
            }
        }

        if (pkg.contains("facebook") || pkg.contains("katana") || pkg.contains("lite")) {
            val summary = res["textSummary"] as? String ?: ""
            // If Facebook was recently opened and feed hasn't scrolled past story tray, scroll down once to reveal posts
            if (!summary.contains("=== FACEBOOK FEED POSTS ===") || summary.length < 200) {
                a11y.performScroll(true)
                try {
                    Thread.sleep(800)
                } catch (_: Exception) {}
                return a11y.getScreenContent()
            }
        }
        return res
    }

    /**
     * Notify Android MediaScanner to index newly saved audio or media files.
     */
    fun scanMediaFile(filePath: String): Map<String, Any> {
        return try {
            val file = java.io.File(filePath)
            if (file.exists()) {
                android.media.MediaScannerConnection.scanFile(
                    context,
                    arrayOf(file.absolutePath),
                    arrayOf("audio/wav", "audio/x-wav", "audio/*")
                ) { path, uri ->
                    Log.d(TAG, "MediaScanner indexed audio file: $path -> $uri")
                }
            }
            mapOf("success" to true, "path" to filePath)
        } catch (e: Exception) {
            mapOf("success" to false, "message" to (e.message ?: ""))
        }
    }

    /**
     * Send chat or text message inside an installed app (Telegram, Viber, Facebook, etc.).
     * Confirmation gate: default autoSend = false (draft mode).
     * Only sends after user explicit confirmation.
     */
    fun sendAppMessage(
        app: String,
        recipient: String?,
        message: String,
        autoSend: Boolean = false
    ): Map<String, Any> {
        val a11y = JarvisAccessibilityService.instance
        if (a11y == null) {
            try {
                openAccessibilitySettings()
            } catch (_: Exception) {}
            return mapOf(
                "success" to false,
                "message" to "JARVIS Accessibility Service ကို ဖွင့်ထားခြင်း မရှိပါ ခင်ဗျာ။ Settings ထဲတွင် ခွင့်ပြုပေးနိုင်ရန် ဖွင့်လှစ်ပေးထားပါသည် ခင်ဗျာ။"
            )
        }

        if (a11y.isSensitiveScreen()) {
            return mapOf(
                "success" to false,
                "message" to "လုံခြုံရေးအရ Password၊ PIN သို့မဟုတ် ဘဏ်နှင့် ငွေကြေးဆိုင်ရာ အက်ပ်များ၏ မျက်နှာပြင်တွင် စာပို့ခွင့် ပိတ်ပင်ထားပါသည် ခင်ဗျာ။"
            )
        }

        // 1. Open the requested messaging app
        val openRes = openApp(app)
        if (openRes["success"] != true) {
            return mapOf(
                "success" to false,
                "message" to "$app အက်ပ်ကို ဖွင့်၍ မရပါ ခင်ဗျာ။"
            )
        }

        // 2. Wait for app window to settle
        try { Thread.sleep(1200) } catch (_: Exception) {}

        if (a11y.isSensitiveScreen()) {
            return mapOf(
                "success" to false,
                "message" to "လုံခြုံရေးအရ အရေးကြီးသော မျက်နှာပြင်ဖြစ်သဖြင့် ဆက်လက်ဆောင်ရွက်ခွင့် ပိတ်ပင်ထားပါသည် ခင်ဗျာ။"
            )
        }

        // 3. Search recipient if provided with ambiguous contact detection ("လူတူရင် စာရင်းပြပြီး အတည်ပြုပါ")
        if (!recipient.isNullOrBlank()) {
            Log.d(TAG, "sendAppMessage: Searching recipient '$recipient' in $app")
            val searchClicked = a11y.clickElement("Search") ||
                    a11y.clickElement("ရှာရန်") ||
                    a11y.clickElement("search") ||
                    a11y.clickElement("menu_search") ||
                    a11y.clickElement("action_search") ||
                    a11y.clickElement("search_icon") ||
                    a11y.clickElement("compose") ||
                    a11y.clickElement("fab_compose") ||
                    a11y.clickElement("fab")

            if (searchClicked) {
                try { Thread.sleep(600) } catch (_: Exception) {}
                val searchTyped = a11y.inputText(recipient, "search") || a11y.inputText(recipient)
                Log.d(TAG, "sendAppMessage: Typed recipient query '$recipient': $searchTyped")
                try { Thread.sleep(1200) } catch (_: Exception) {}

                // Check for multiple/ambiguous contacts
                val matchingContacts = a11y.findMatchingContacts(recipient)
                Log.d(TAG, "sendAppMessage: Found matching contacts for '$recipient': $matchingContacts")
                if (matchingContacts.size > 1) {
                    val contactListStr = matchingContacts.joinToString("၊ ")
                    return mapOf(
                        "success" to false,
                        "ambiguous" to true,
                        "contacts" to matchingContacts,
                        "message" to "လူတူ/အမည်တူ ${matchingContacts.size} ဦး တွေ့ရှိပါသည်: $contactListStr ဖြစ်ပါသည်။ မည်သူ့ထံ ပို့ဆောင်ရမည်ကို အတည်ပြုပေးပါ ဆရာ။"
                    )
                }

                // Click recipient name from result list
                val recClicked = a11y.clickElement(recipient)
                Log.d(TAG, "sendAppMessage: Clicked recipient '$recipient' -> $recClicked")
                if (recClicked) {
                    try { Thread.sleep(1000) } catch (_: Exception) {}
                }
            }
        }

        // 4. Type the message
        Log.d(TAG, "sendAppMessage: Typing message '$message' in $app")
        var typed = a11y.inputText(message, "message") ||
                a11y.inputText(message, "write a message") ||
                a11y.inputText(message, "type a message") ||
                a11y.inputText(message, "send_text") ||
                a11y.inputText(message, "စာရိုက်ပါ") ||
                a11y.inputText(message)

        if (!typed) {
            // Tap message input area then type
            a11y.clickElement("message") || a11y.clickElement("write a message") || a11y.clickElement("type a message") || a11y.clickElement("send_text")
            try { Thread.sleep(400) } catch (_: Exception) {}
            typed = a11y.inputText(message)
        }

        if (!typed) {
            return mapOf(
                "success" to false,
                "message" to "$app တွင် စာရိုက်ကွက် ရှာမတွေ့ပါ ခင်ဗျာ။"
            )
        }

        // 5. Confirmation Gate: autoSend default false
        // Draft is ready -> Read back recipient + text to user -> wait for confirmation
        return if (autoSend) {
            try { Thread.sleep(500) } catch (_: Exception) {}
            val sent = a11y.clickSendButton()
            if (sent) {
                mapOf(
                    "success" to true,
                    "sent" to true,
                    "draft" to false,
                    "message" to "$app တွင် ${recipient ?: ""} ထံသို့ '$message' ဟု စာပို့ပေးလိုက်ပါပြီ ခင်ဗျာ။"
                )
            } else {
                mapOf(
                    "success" to true,
                    "sent" to false,
                    "draft" to true,
                    "message" to "$app တွင် စာရိုက်ထည့်ထားပြီးပါပြီ၊ Verified Send ခလုတ် ရှာမတွေ့သဖြင့် ဆရာကိုယ်တိုင် စစ်ဆေးပေးပါ ခင်ဗျာ။"
                )
            }
        } else {
            // DRAFT MODE: Read back recipient + text to user for confirmation
            mapOf(
                "success" to true,
                "sent" to false,
                "draft" to true,
                "app" to app,
                "recipient" to (recipient ?: ""),
                "messageText" to message,
                "message" to "မူကြမ်း: $app တွင် ${recipient ?: ""} ထံသို့ '$message' ဟု စာရိုက်ထားပြီးပါပြီ ဆရာ။ ပို့လိုက်ရမလား ခင်ဗျာ။"
            )
        }
    }

    /**
     * Autonomous agent UI interaction: click, send, scroll, input, back, home.
     * Note: Coordinate blind tap and arbitrary tap(x,y) are strictly disabled for safety.
     */
    fun controlScreen(
        action: String,
        target: String?,
        field: String? = null
    ): Map<String, Any> {
        val a11y = JarvisAccessibilityService.instance
        if (a11y == null) {
            try {
                openAccessibilitySettings()
            } catch (_: Exception) {}
            return mapOf(
                "success" to false,
                "message" to "JARVIS Accessibility Service ကို ဖွင့်ထားခြင်း မရှိပါ ခင်ဗျာ။ Settings ထဲတွင် ခွင့်ပြုပေးနိုင်ရန် ဖွင့်လှစ်ပေးထားပါသည် ခင်ဗျာ။"
            )
        }

        if (a11y.isSensitiveScreen()) {
            return mapOf(
                "success" to false,
                "message" to "လုံခြုံရေးအရ Password၊ PIN သို့မဟုတ် ဘဏ်နှင့် ငွေကြေးဆိုင်ရာ အက်ပ်များ၏ မျက်နှာပြင်တွင် ထိန်းချုပ်ခွင့် ပိတ်ပင်ထားပါသည် ခင်ဗျာ။"
            )
        }

        val act = action.trim().lowercase()
        return when {
            act == "click" -> {
                val q = target ?: ""
                val ok = a11y.clickElement(q)
                mapOf("success" to ok, "message" to if (ok) "'$q' ကို နှိပ်လိုက်ပါပြီ ခင်ဗျာ။" else "'$q' ကို ရှာမတွေ့ပါ ခင်ဗျာ။")
            }
            act == "send" || act.contains("ပို့") -> {
                val ok = a11y.clickSendButton()
                mapOf("success" to ok, "message" to if (ok) "Verified Send ခလုတ်ကို နှိပ်ပြီး စာပို့ပေးလိုက်ပါပြီ ခင်ဗျာ။" else "Verified Send ခလုတ် ရှာမတွေ့ပါ ခင်ဗျာ။")
            }
            act.contains("down") || act.contains("forward") -> {
                val ok = a11y.performScroll(true)
                mapOf("success" to ok, "message" to if (ok) "မျက်နှာပြင်ကို အောက်သို့ ဆွဲချလိုက်ပါပြီ ခင်ဗျာ။" else "Scroll မရပါ ခင်ဗျာ။")
            }
            act.contains("up") || act.contains("backward") -> {
                val ok = a11y.performScroll(false)
                mapOf("success" to ok, "message" to if (ok) "မျက်နှာပြင်ကို အပေါ်သို့ ပြန်ဆွဲတင်လိုက်ပါပြီ ခင်ဗျာ။" else "Scroll မရပါ ခင်ဗျာ။")
            }
            act == "back" -> {
                val ok = a11y.performGlobal("back")
                mapOf("success" to ok, "message" to if (ok) "Back ပြန်ဆုတ်လိုက်ပါပြီ ခင်ဗျာ။" else "Back မရပါ ခင်ဗျာ။")
            }
            act == "home" -> {
                val ok = a11y.performGlobal("home")
                mapOf("success" to ok, "message" to if (ok) "Home မျက်နှာပြင်သို့ သွားလိုက်ပါပြီ ခင်ဗျာ။" else "Home မရပါ ခင်ဗျာ။")
            }
            act == "input" || act == "type" -> {
                val text = target ?: ""
                val ok = a11y.inputText(text, field)
                mapOf("success" to ok, "message" to if (ok) "'$text' ကို ရိုက်ထည့်လိုက်ပါပြီ ခင်ဗျာ။" else "စာရိုက်ထည့်၍ မရပါ ခင်ဗျာ။")
            }
            act.contains("shutter") -> {
                val ok = a11y.clickShutter()
                mapOf("success" to ok, "message" to if (ok) "Shutter ခလုတ်ကို နှိပ်ပေးလိုက်ပါပြီ ခင်ဗျာ။" else "Shutter နှိပ်မရပါ ခင်ဗျာ။")
            }
            else -> mapOf("success" to false, "message" to "မသိရှိသော လုပ်ဆောင်ချက် ဖြစ်ပါသည်: $action")
        }
    }

    /**
     * Start or stop native audio recording on-demand.
     */
    fun manageAudioRecording(action: String): Map<String, Any> {
        val act = action.trim().lowercase()
        return if (act == "start" || act == "record" || act.contains("စတင်") || act.contains("ဖွင့်")) {
            audioRecorder.startRecording()
        } else if (act == "stop" || act == "finish" || act == "end" || act.contains("ရပ်") || act.contains("ပိတ်")) {
            audioRecorder.stopRecording()
        } else {
            if (JarvisAudioRecorder.isRecording) {
                audioRecorder.stopRecording()
            } else {
                audioRecorder.startRecording()
            }
        }
    }

    data class SimCardInfo(
        val slotIndex: Int,
        val carrierName: String,
        val displayName: String,
        val subscriptionId: Int,
        val handle: PhoneAccountHandle?
    )

    fun getSimCards(): List<SimCardInfo> {
        val result = mutableListOf<SimCardInfo>()
        val telecomManager = context.getSystemService(Context.TELECOM_SERVICE) as? TelecomManager
        val subscriptionManager = context.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE) as? SubscriptionManager

        try {
            val phoneAccounts = if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED) {
                telecomManager?.callCapablePhoneAccounts ?: emptyList()
            } else emptyList()

            val subs = if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED) {
                subscriptionManager?.activeSubscriptionInfoList ?: emptyList()
            } else emptyList()

            for (sub in subs) {
                val carrier = sub.carrierName?.toString() ?: ""
                val disp = sub.displayName?.toString() ?: ""
                val slot = sub.simSlotIndex
                val subId = sub.subscriptionId
                val matchedHandle = phoneAccounts.find { it.id == subId.toString() }
                result.add(SimCardInfo(slot, carrier, disp, subId, matchedHandle))
            }

            if (result.isEmpty() && phoneAccounts.isNotEmpty()) {
                phoneAccounts.forEachIndexed { idx, handle ->
                    val acc = telecomManager?.getPhoneAccount(handle)
                    val label = acc?.label?.toString() ?: "SIM ${idx + 1}"
                    result.add(SimCardInfo(idx, label, label, -1, handle))
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "getSimCards exception: ${e.message}")
        }
        return result
    }

    fun findContactPhoneNumber(recipient: String): Pair<String, String>? {
        val q = recipient.trim()
        if (q.isEmpty()) return null

        val digitsOnly = q.replace(Regex("""[^\d+]"""), "")
        if (digitsOnly.length >= 7 && (digitsOnly.startsWith("09") || digitsOnly.startsWith("+95") || digitsOnly.startsWith("959") || digitsOnly.startsWith("01"))) {
            return Pair(q, digitsOnly)
        }

        if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
            Log.w(TAG, "READ_CONTACTS permission not granted")
            return null
        }

        val searchTargets = mutableListOf<String>()
        val lower = q.lowercase()
        when {
            lower == "mother" || lower == "mom" || lower == "mum" || lower.contains("အမေ") || lower.contains("မေမေ") -> {
                searchTargets.addAll(listOf("အမေ", "မေမေ", "Mother", "Mom", "Mum"))
            }
            lower == "father" || lower == "dad" || lower.contains("အဖေ") || lower.contains("ဖေဖေ") -> {
                searchTargets.addAll(listOf("အဖေ", "ဖေဖေ", "Father", "Dad"))
            }
            lower == "sister" || lower.contains("အစ်မ") || lower.contains("မမ") -> {
                searchTargets.addAll(listOf("အစ်မ", "မမ", "Sister"))
            }
            lower == "brother" || lower.contains("အစ်ကို") || lower.contains("ကိုကို") -> {
                searchTargets.addAll(listOf("အစ်ကို", "ကိုကို", "Brother"))
            }
            else -> {
                searchTargets.add(q)
            }
        }

        val uri = ContactsContract.CommonDataKinds.Phone.CONTENT_URI
        val projection = arrayOf(
            ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
            ContactsContract.CommonDataKinds.Phone.NUMBER
        )

        for (target in searchTargets) {
            val selection = "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ?"
            val selectionArgs = arrayOf("%$target%")
            try {
                context.contentResolver.query(uri, projection, selection, selectionArgs, null)?.use { cursor ->
                    val nameIdx = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME)
                    val numIdx = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.NUMBER)
                    while (cursor.moveToNext()) {
                        val name = cursor.getString(nameIdx) ?: target
                        val number = cursor.getString(numIdx) ?: continue
                        val cleanNum = number.replace(Regex("""[^\d+]"""), "")
                        if (cleanNum.isNotEmpty()) {
                            return Pair(name, cleanNum)
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "findContactPhoneNumber query failed for $target: ${e.message}")
            }
        }
        return null
    }

    fun makePhoneCall(recipient: String, simOperator: String?): Map<String, Any> {
        val contact = findContactPhoneNumber(recipient)
        if (contact == null) {
            return mapOf(
                "success" to false,
                "message" to "လိပ်စာစာအုပ် (Contacts) ထဲတွင် '$recipient' အမည်ဖြင့် ဖုန်းနံပါတ် ရှာမတွေ့ပါ ခင်ဗျာ။"
            )
        }

        val (displayName, phoneNumber) = contact
        val simCards = getSimCards()
        var selectedSim: SimCardInfo? = null
        val requestedOp = simOperator?.trim()?.lowercase() ?: ""

        if (requestedOp.isNotEmpty()) {
            selectedSim = simCards.find { sim ->
                val c = sim.carrierName.lowercase()
                val d = sim.displayName.lowercase()
                when {
                    requestedOp.contains("mpt") -> c.contains("mpt") || d.contains("mpt")
                    requestedOp.contains("mytel") -> c.contains("mytel") || d.contains("mytel")
                    requestedOp.contains("atom") || requestedOp.contains("telenor") -> c.contains("atom") || c.contains("telenor") || d.contains("atom") || d.contains("telenor")
                    requestedOp.contains("ooredoo") -> c.contains("ooredoo") || d.contains("ooredoo")
                    requestedOp.contains("1") -> sim.slotIndex == 0
                    requestedOp.contains("2") -> sim.slotIndex == 1
                    else -> c.contains(requestedOp) || d.contains(requestedOp)
                }
            }

            if (selectedSim == null && simCards.isNotEmpty()) {
                val availableNames = simCards.map { it.carrierName.ifEmpty { it.displayName } }.filter { it.isNotEmpty() }
                return mapOf(
                    "success" to false,
                    "message" to "ဆရာ့ဖုန်းတွင် '$simOperator' SIM ကတ် မတွေ့ရှိပါ။ လက်ရှိ ထည့်သွင်းထားသော SIM မှာ ${availableNames.joinToString(", ")} ဖြစ်ပါသည် ခင်ဗျာ။"
                )
            }
        }

        if (selectedSim == null && simCards.isNotEmpty()) {
            selectedSim = simCards.first()
        }

        try {
            val uri = Uri.parse("tel:$phoneNumber")
            val telecomManager = context.getSystemService(Context.TELECOM_SERVICE) as? TelecomManager
            val extras = Bundle().apply {
                if (selectedSim?.handle != null) {
                    putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE, selectedSim.handle)
                }
                if (selectedSim != null) {
                    putBoolean("com.android.phone.force.slot", true)
                    putInt("com.android.phone.extra.slot", selectedSim.slotIndex)
                    putInt("simSlot", selectedSim.slotIndex)
                    putInt("subscription", selectedSim.subscriptionId)
                }
            }

            val hasCallPermission = ContextCompat.checkSelfPermission(context, Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED
            if (hasCallPermission && Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && telecomManager != null) {
                telecomManager.placeCall(uri, extras)
            } else {
                val intent = Intent(if (hasCallPermission) Intent.ACTION_CALL else Intent.ACTION_DIAL, uri).apply {
                    putExtras(extras)
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                context.startActivity(intent)
            }

            val opLabel = selectedSim?.carrierName?.ifEmpty { selectedSim.displayName } ?: "ပုံမှန်လိုင်း"
            val message = "$displayName ($phoneNumber) ထံသို့ $opLabel ဖြင့် ဖုန်းခေါ်ဆိုပေးလိုက်ပါပြီ ခင်ဗျာ။"
            Log.d(TAG, "makePhoneCall success: $message")
            return mapOf(
                "success" to true,
                "message" to message,
                "contact" to displayName,
                "phoneNumber" to phoneNumber,
                "operator" to opLabel
            )
        } catch (e: Exception) {
            Log.e(TAG, "makePhoneCall error: ${e.message}")
            return mapOf(
                "success" to false,
                "message" to "ဖုန်းခေါ်ဆိုရာတွင် အခက်အခဲရှိပါသည်: ${e.message}"
            )
        }
    }
}
