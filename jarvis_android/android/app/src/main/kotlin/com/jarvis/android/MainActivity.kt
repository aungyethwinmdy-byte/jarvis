package com.jarvis.android

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity: FlutterActivity() {
    private val CHANNEL = "com.jarvis.android/device_control"
    private lateinit var deviceController: DeviceController
    private var callManager: JarvisCallManager? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        WindowOverlayManager.ensureOverlay(this)
        deviceController = DeviceController(this)

        val channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL)
        callManager = JarvisCallManager(this).apply {
            onCallStateListener = { state ->
                runOnUiThread {
                    channel.invokeMethod("onCallStateChanged", mapOf("state" to state))
                }
            }
            onAudioFocusListener = { focus ->
                runOnUiThread {
                    channel.invokeMethod("onAudioFocusChanged", mapOf("focus" to focus))
                }
            }
        }

        channel.setMethodCallHandler { call, result ->
            when (call.method) {
                "toggleTorch" -> {
                    val enable = call.argument<Boolean>("enable") ?: true
                    val res = deviceController.toggleTorch(enable)
                    result.success(res)
                }
                "setVolume" -> {
                    val stream = call.argument<String>("stream") ?: "media"
                    val percent = call.argument<Int>("percent") ?: 50
                    val res = deviceController.setVolume(stream, percent)
                    result.success(res)
                }
                "getVolume" -> {
                    val stream = call.argument<String>("stream")
                    val res = deviceController.getVolume(stream)
                    result.success(res)
                }
                "openApp" -> {
                    val query = call.argument<String>("query") ?: ""
                    val res = deviceController.openApp(query)
                    result.success(res)
                }
                "getDeviceStatus" -> {
                    val res = deviceController.getDeviceStatus()
                    result.success(res)
                }
                "setReminder" -> {
                    val title = call.argument<String>("title") ?: "သတိပေးချက်"
                    val delaySeconds = call.argument<Int>("delaySeconds") ?: 60
                    val res = deviceController.setReminder(title, delaySeconds)
                    result.success(res)
                }
                "playYouTube" -> {
                    val query = call.argument<String>("query") ?: ""
                    val res = deviceController.playYouTube(query)
                    result.success(res)
                }
                "takeCameraPhoto" -> {
                    val camera = call.argument<String>("camera") ?: call.argument<String>("lens") ?: "back"
                    val res = deviceController.takeCameraPhoto(camera)
                    result.success(res)
                }
                "checkMessages" -> {
                    val app = call.argument<String>("app")
                    val res = deviceController.checkMessages(app)
                    result.success(res)
                }
                "inspectScreen" -> {
                    val res = deviceController.inspectScreen()
                    result.success(res)
                }
                "controlScreen" -> {
                    val action = call.argument<String>("action") ?: "click"
                    val target = call.argument<String>("target")
                    val field = call.argument<String>("field")
                    val res = deviceController.controlScreen(action, target, field)
                    result.success(res)
                }
                "sendAppMessage" -> {
                    val app = call.argument<String>("app") ?: "telegram"
                    val recipient = call.argument<String>("recipient")
                    val message = call.argument<String>("message") ?: ""
                    val autoSend = call.argument<Boolean>("autoSend") ?: false
                    val res = deviceController.sendAppMessage(app, recipient, message, autoSend)
                    result.success(res)
                }
                "manageAudioRecording" -> {
                    val action = call.argument<String>("action") ?: "start"
                    val res = deviceController.manageAudioRecording(action)
                    result.success(res)
                }
                "scanMediaFile" -> {
                    val filePath = call.argument<String>("filePath") ?: ""
                    val res = deviceController.scanMediaFile(filePath)
                    result.success(res)
                }
                "getCallState" -> {
                    val state = callManager?.getCurrentCallState() ?: "IDLE"
                    result.success(mapOf("state" to state))
                }
                "requestVoiceFocus" -> {
                    val granted = callManager?.requestAudioFocusForVoice() ?: false
                    result.success(mapOf("granted" to granted))
                }
                "abandonVoiceFocus" -> {
                    callManager?.abandonAudioFocusForVoice()
                    result.success(mapOf("success" to true))
                }
                "makePhoneCall" -> {
                    val recipient = call.argument<String>("recipient") ?: ""
                    val simOperator = call.argument<String>("simOperator")
                    val res = deviceController.makePhoneCall(recipient, simOperator)
                    result.success(res)
                }
                "getSimOperators" -> {
                    val sims = deviceController.getSimCards().map { sim ->
                        mapOf(
                            "slotIndex" to sim.slotIndex,
                            "displayName" to sim.displayName,
                            "carrierName" to sim.carrierName,
                            "subscriptionId" to sim.subscriptionId
                        )
                    }
                    result.success(sims)
                }
                "isAccessibilityEnabled" -> {
                    val enabled = JarvisAccessibilityService.instance != null
                    result.success(mapOf("enabled" to enabled))
                }
                "openAccessibilitySettings" -> {
                    val res = deviceController.openAccessibilitySettings()
                    result.success(res)
                }
                else -> result.notImplemented()
            }
        }
    }

    override fun onResume() {
        super.onResume()
        WindowOverlayManager.ensureOverlay(this)
    }
}
