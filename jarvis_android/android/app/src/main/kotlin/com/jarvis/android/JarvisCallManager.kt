package com.jarvis.android

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.telephony.PhoneStateListener
import android.telephony.TelephonyCallback
import android.telephony.TelephonyManager
import android.util.Log
import androidx.core.content.ContextCompat

/**
 * Manages phone call state monitoring (RINGING, OFFHOOK, IDLE) and
 * audio focus changes (LOSS, LOSS_TRANSIENT, GAIN) for Jarvis.
 */
class JarvisCallManager(private val context: Context) {
    companion object {
        private const val TAG = "JarvisCallManager"

        @Volatile
        var instance: JarvisCallManager? = null

        fun notifyCallState(state: String) {
            instance?.dispatchCallState(state)
        }

        fun notifyAudioFocus(focus: String) {
            instance?.dispatchAudioFocus(focus)
        }
    }

    var onCallStateListener: ((String) -> Unit)? = null
    var onAudioFocusListener: ((String) -> Unit)? = null

    private val mainHandler = Handler(Looper.getMainLooper())
    private val telephonyManager = context.getSystemService(Context.TELEPHONY_SERVICE) as? TelephonyManager
    private val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager

    private var telephonyCallback: Any? = null
    private var phoneStateListener: PhoneStateListener? = null
    private var phoneStateReceiver: BroadcastReceiver? = null
    private var audioFocusChangeListener: AudioManager.OnAudioFocusChangeListener? = null
    private var audioFocusRequest: Any? = null

    @Volatile
    private var lastCallState: String = "IDLE"

    init {
        instance = this
        setupCallStateListener()
        setupPhoneStateReceiver()
        setupAudioFocusListener()
    }

    fun dispatchCallState(state: String) {
        if (state == lastCallState && state != "RINGING") {
            Log.d(TAG, "dispatchCallState: duplicate state $state ignored")
            return
        }
        lastCallState = state
        Log.d(TAG, "dispatchCallState: $state")
        mainHandler.post {
            onCallStateListener?.invoke(state)
        }
    }

    fun dispatchAudioFocus(focus: String) {
        Log.d(TAG, "dispatchAudioFocus: $focus")
        mainHandler.post {
            onAudioFocusListener?.invoke(focus)
        }
    }

    fun getCurrentCallState(): String {
        return lastCallState
    }

    private fun setupCallStateListener() {
        val tm = telephonyManager ?: return
        try {
            val hasPermission = ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.READ_PHONE_STATE
            ) == PackageManager.PERMISSION_GRANTED

            if (!hasPermission) {
                Log.w(TAG, "READ_PHONE_STATE permission not yet granted, relying on broadcast receiver & AudioFocus")
            }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                if (hasPermission) {
                    val cb = object : TelephonyCallback(), TelephonyCallback.CallStateListener {
                        override fun onCallStateChanged(state: Int) {
                            handleCallStateInt(state)
                        }
                    }
                    tm.registerTelephonyCallback(context.mainExecutor, cb)
                    telephonyCallback = cb
                    Log.d(TAG, "Registered TelephonyCallback.CallStateListener (API 31+)")
                }
            } else {
                @Suppress("DEPRECATION")
                val listener = object : PhoneStateListener() {
                    @Deprecated("Deprecated in Java")
                    override fun onCallStateChanged(state: Int, phoneNumber: String?) {
                        handleCallStateInt(state)
                    }
                }
                tm.listen(listener, PhoneStateListener.LISTEN_CALL_STATE)
                phoneStateListener = listener
                Log.d(TAG, "Registered PhoneStateListener.LISTEN_CALL_STATE (< API 31)")
            }
        } catch (e: Exception) {
            Log.e(TAG, "setupCallStateListener exception: ${e.message}")
        }
    }

    private fun handleCallStateInt(state: Int) {
        when (state) {
            TelephonyManager.CALL_STATE_RINGING -> dispatchCallState("RINGING")
            TelephonyManager.CALL_STATE_OFFHOOK -> dispatchCallState("OFFHOOK")
            TelephonyManager.CALL_STATE_IDLE -> dispatchCallState("IDLE")
            else -> dispatchCallState("UNKNOWN")
        }
    }

    private fun setupPhoneStateReceiver() {
        try {
            val receiver = object : BroadcastReceiver() {
                override fun onReceive(c: Context, intent: Intent) {
                    val extraState = intent.getStringExtra(TelephonyManager.EXTRA_STATE)
                    Log.d(TAG, "PHONE_STATE broadcast onReceive: $extraState")
                    when (extraState) {
                        TelephonyManager.EXTRA_STATE_RINGING -> dispatchCallState("RINGING")
                        TelephonyManager.EXTRA_STATE_OFFHOOK -> dispatchCallState("OFFHOOK")
                        TelephonyManager.EXTRA_STATE_IDLE -> dispatchCallState("IDLE")
                    }
                }
            }
            val filter = IntentFilter(TelephonyManager.ACTION_PHONE_STATE_CHANGED)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                context.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED)
            } else {
                context.registerReceiver(receiver, filter)
            }
            phoneStateReceiver = receiver
            Log.d(TAG, "Registered dynamic ACTION_PHONE_STATE_CHANGED broadcast receiver")
        } catch (e: Exception) {
            Log.w(TAG, "setupPhoneStateReceiver exception: ${e.message}")
        }
    }

    private fun setupAudioFocusListener() {
        val am = audioManager ?: return
        val listener = AudioManager.OnAudioFocusChangeListener { focusChange ->
            Log.d(TAG, "onAudioFocusChange: $focusChange")
            when (focusChange) {
                AudioManager.AUDIOFOCUS_LOSS -> dispatchAudioFocus("LOSS")
                AudioManager.AUDIOFOCUS_LOSS_TRANSIENT -> dispatchAudioFocus("LOSS_TRANSIENT")
                AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> dispatchAudioFocus("LOSS_TRANSIENT_CAN_DUCK")
                AudioManager.AUDIOFOCUS_GAIN -> dispatchAudioFocus("GAIN")
            }
        }
        audioFocusChangeListener = listener
        Log.d(TAG, "Created AudioFocusChangeListener")
    }

    fun requestAudioFocusForVoice(): Boolean {
        val am = audioManager ?: return false
        val listener = audioFocusChangeListener ?: return false
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val playbackAttributes = AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
                val focusReq = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                    .setAudioAttributes(playbackAttributes)
                    .setAcceptsDelayedFocusGain(true)
                    .setOnAudioFocusChangeListener(listener, mainHandler)
                    .build()
                val res = am.requestAudioFocus(focusReq)
                audioFocusRequest = focusReq
                res == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
            } else {
                @Suppress("DEPRECATION")
                val res = am.requestAudioFocus(
                    listener,
                    AudioManager.STREAM_MUSIC,
                    AudioManager.AUDIOFOCUS_GAIN_TRANSIENT
                )
                res == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
            }
        } catch (e: Exception) {
            Log.w(TAG, "requestAudioFocusForVoice failed: ${e.message}")
            false
        }
    }

    fun abandonAudioFocusForVoice() {
        val am = audioManager ?: return
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val req = audioFocusRequest as? AudioFocusRequest
                if (req != null) {
                    am.abandonAudioFocusRequest(req)
                    audioFocusRequest = null
                }
            } else {
                val listener = audioFocusChangeListener
                if (listener != null) {
                    @Suppress("DEPRECATION")
                    am.abandonAudioFocus(listener)
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "abandonAudioFocusForVoice failed: ${e.message}")
        }
    }
}
