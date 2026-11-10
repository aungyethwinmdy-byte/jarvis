package com.jarvis.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class JarvisTestReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "JarvisTest"
    }

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.getStringExtra("action") ?: ""
        Log.d(TAG, "onReceive test action: $action")
        val controller = DeviceController(context)
        when (action) {
            "take_photo" -> {
                val camera = intent.getStringExtra("camera") ?: intent.getStringExtra("lens") ?: "back"
                val res = controller.takeCameraPhoto(camera)
                Log.d(TAG, "take_photo camera: $camera, result: $res")
            }
            "check_messages" -> {
                val app = intent.getStringExtra("app") ?: "facebook"
                val res = controller.checkMessages(app)
                Log.d(TAG, "check_messages app: $app, result: $res")
            }
            "record_start" -> {
                val res = controller.manageAudioRecording("start")
                Log.d(TAG, "record_start result: $res")
            }
            "record_stop" -> {
                val res = controller.manageAudioRecording("stop")
                Log.d(TAG, "record_stop result: $res")
            }
            "control_screen" -> {
                val ctrlAct = intent.getStringExtra("control_action") ?: intent.getStringExtra("act") ?: "click"
                val target = intent.getStringExtra("target")
                val field = intent.getStringExtra("field")
                val res = controller.controlScreen(ctrlAct, target, field)
                Log.d(TAG, "control_screen action: $ctrlAct, target: $target, result: $res")
            }
            "send_app_message" -> {
                val app = intent.getStringExtra("app") ?: "telegram"
                val recipient = intent.getStringExtra("recipient")
                val msg = intent.getStringExtra("message") ?: "Hello from Jarvis"
                val autoSend = intent.getBooleanExtra("auto_send", false)
                val res = controller.sendAppMessage(app, recipient, msg, autoSend)
                Log.d(TAG, "send_app_message app: $app, recipient: $recipient, result: $res")
            }
            "call_state" -> {
                val state = intent.getStringExtra("state") ?: "IDLE"
                JarvisCallManager.notifyCallState(state)
                Log.d(TAG, "call_state dispatched: $state")
            }
            "audio_focus" -> {
                val focus = intent.getStringExtra("focus") ?: "LOSS"
                JarvisCallManager.notifyAudioFocus(focus)
                Log.d(TAG, "audio_focus dispatched: $focus")
            }
            "make_call" -> {
                val recipient = intent.getStringExtra("recipient") ?: ""
                val op = intent.getStringExtra("operator") ?: intent.getStringExtra("sim")
                val res = controller.makePhoneCall(recipient, op)
                Log.d(TAG, "make_call recipient: $recipient, operator: $op, result: $res")
            }
            else -> {
                Log.d(TAG, "unknown test action: $action")
            }
        }
    }
}
