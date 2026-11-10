package com.jarvis.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.TelephonyManager
import android.util.Log

/**
 * Manifest-declared BroadcastReceiver for ACTION_PHONE_STATE_CHANGED.
 * Forwards call state events directly to JarvisCallManager.
 */
class JarvisPhoneStateReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "JarvisPhoneStateReceiver"
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == TelephonyManager.ACTION_PHONE_STATE_CHANGED) {
            val stateStr = intent.getStringExtra(TelephonyManager.EXTRA_STATE)
            Log.d(TAG, "ACTION_PHONE_STATE_CHANGED received: $stateStr")
            when (stateStr) {
                TelephonyManager.EXTRA_STATE_RINGING -> JarvisCallManager.notifyCallState("RINGING")
                TelephonyManager.EXTRA_STATE_OFFHOOK -> JarvisCallManager.notifyCallState("OFFHOOK")
                TelephonyManager.EXTRA_STATE_IDLE -> JarvisCallManager.notifyCallState("IDLE")
            }
        }
    }
}
