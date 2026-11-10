package com.jarvis.android

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * JarvisAccessibilityService enables autonomous screen inspection and UI automation
 * (clicking buttons, shutter capture, scrolling, typing, reading screen content).
 */
class JarvisAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "JarvisA11yService"

        @Volatile
        var instance: JarvisAccessibilityService? = null
            private set

        fun isAccessibilityEnabled(context: Context): Boolean {
            val expectedServiceName = "${context.packageName}/${JarvisAccessibilityService::class.java.canonicalName}"
            val enabledServices = Settings.Secure.getString(
                context.contentResolver,
                Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
            ) ?: return false
            return enabledServices.split(":").any { it.equals(expectedServiceName, ignoreCase = true) }
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.d(TAG, "JarvisAccessibilityService connected and ready for autonomous agent actions")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Events can be monitored if needed for reactive triggers
    }

    override fun onInterrupt() {
        Log.d(TAG, "JarvisAccessibilityService interrupted")
    }

    override fun onDestroy() {
        super.onDestroy()
        instance = null
        Log.d(TAG, "JarvisAccessibilityService destroyed")
    }

    /**
     * Strict Guard: Detect if current active app or window contains sensitive banking,
     * payment, wallet, password, PIN, or OTP screens.
     */
    fun isSensitiveScreen(): Boolean {
        val root = rootInActiveWindow ?: return false
        val packageName = root.packageName?.toString()?.lowercase() ?: ""
        val sensitiveKeywords = listOf(
            "bank", "kpay", "kbzpay", "ayapay", "wavepay", "wavemoney", "uabpay", "cbbank", "cbpay",
            "onepay", "passcode", "pin", "authenticator", "keychain", "wallet", "password"
        )
        if (sensitiveKeywords.any { packageName.contains(it) }) {
            Log.w(TAG, "Sensitive guard: Blocked sensitive/banking app: $packageName")
            return true
        }

        // Check for password/PIN/OTP fields on screen
        var hasSensitiveField = false
        fun checkSensitiveNodes(node: AccessibilityNodeInfo?) {
            if (node == null || hasSensitiveField) return
            if (node.isPassword) {
                hasSensitiveField = true
                return
            }
            val desc = node.contentDescription?.toString()?.lowercase() ?: ""
            val text = node.text?.toString()?.lowercase() ?: ""
            if (desc.contains("password") || desc.contains("pin code") || desc.contains("enter otp") ||
                text.contains("enter pin") || text.contains("enter password")) {
                hasSensitiveField = true
                return
            }
            for (i in 0 until node.childCount) {
                checkSensitiveNodes(node.getChild(i))
            }
        }
        checkSensitiveNodes(root)
        if (hasSensitiveField) {
            Log.w(TAG, "Sensitive guard: Password or PIN/OTP field detected on active screen.")
            return true
        }
        return false
    }

    /**
     * Inspect and extract all readable text and interactive elements on the current screen.
     */
    fun getScreenContent(): Map<String, Any> {
        val root = rootInActiveWindow ?: return mapOf(
            "success" to false,
            "message" to "လက်ရှိ မျက်နှာပြင် အချက်အလက်ကို ဖတ်၍ မရပါ (မျက်နှာပြင် ပိတ်ထားခြင်း သို့မဟုတ် အခွင့်အရေး မရှိပါ) ခင်ဗျာ။",
            "packageName" to "",
            "elements" to emptyList<String>(),
            "textSummary" to ""
        )

        val packageName = root.packageName?.toString() ?: ""

        // Guard: Never inspect banking, wallet, payment, or password manager apps
        if (isSensitiveScreen()) {
            Log.w(TAG, "Guard blocked screen inspection on sensitive/banking screen: $packageName")
            return mapOf(
                "success" to false,
                "message" to "လုံခြုံရေးအရ Password၊ PIN သို့မဟုတ် ဘဏ်နှင့် ငွေကြေးဆိုင်ရာ အက်ပ်များ၏ မျက်နှာပြင်ကို ဖတ်ရှုခွင့် ပိတ်ပင်ထားပါသည် ခင်ဗျာ။",
                "packageName" to packageName,
                "elements" to emptyList<String>(),
                "textSummary" to ""
            )
        }

        val lowerPkg = packageName.lowercase()
        val isFacebook = lowerPkg.contains("facebook") || lowerPkg.contains("katana") || lowerPkg.contains("lite")
        val tabRegex = Regex("""tab \d+ of \d+""", RegexOption.IGNORE_CASE)
        val boilerplateKeywords = listOf(
            "like button", "comment button", "share button", "send in whatsapp", "send button",
            "more options", "search facebook", "what's on your mind?", "create a post",
            "create story", "add to story", "double tap to", "close button", "dismiss"
        )

        val textList = mutableListOf<String>()
        val clickableList = mutableListOf<String>()
        val postCards = mutableListOf<String>()

        fun traverse(node: AccessibilityNodeInfo?) {
            if (node == null) return

            // Guard: Never read text from password or obscured input fields
            if (node.isPassword) {
                return
            }

            val text = node.text?.toString()?.trim() ?: ""
            val desc = node.contentDescription?.toString()?.trim() ?: ""
            val combined = when {
                text.isNotEmpty() && desc.isNotEmpty() && text != desc -> "$text ($desc)"
                text.isNotEmpty() -> text
                desc.isNotEmpty() -> desc
                else -> ""
            }

            if (combined.isNotEmpty()) {
                val lowerCombined = combined.lowercase()
                val isBoilerplate = tabRegex.containsMatchIn(lowerCombined) ||
                        boilerplateKeywords.any { lowerCombined == it || lowerCombined.startsWith(it) }

                if (!isBoilerplate) {
                    textList.add(combined)
                    val hasBurmese = combined.any { it in '\u1000'..'\u109F' }
                    if (isFacebook && (combined.length >= 20 || (hasBurmese && combined.length >= 8) || (combined.contains(" ") && combined.length >= 12))) {
                        postCards.add(combined)
                    }
                }

                if (node.isClickable && !isBoilerplate) {
                    clickableList.add(combined)
                }
            }

            for (i in 0 until node.childCount) {
                traverse(node.getChild(i))
            }
        }

        traverse(root)

        val uniqueTexts = textList.distinct()
        val textSummary = if (isFacebook && postCards.isNotEmpty()) {
            val formattedPosts = postCards.distinct().mapIndexed { idx, post ->
                "[Post ${idx + 1}] $post"
            }.joinToString("\n\n")
            "=== FACEBOOK FEED POSTS ===\n$formattedPosts\n\n=== ADDITIONAL DETAILS ===\n${uniqueTexts.take(20).joinToString("\n")}"
        } else {
            uniqueTexts.joinToString("\n")
        }
        Log.d(TAG, "getScreenContent extracted ${uniqueTexts.size} elements from $packageName: ${textSummary.replace("\n", " | ").take(200)}")

        return mapOf(
            "success" to true,
            "packageName" to packageName,
            "elementCount" to uniqueTexts.size,
            "clickableElements" to clickableList.distinct().take(30),
            "textSummary" to textSummary.take(4000)
        )
    }

    /**
     * Click on a UI element matching the given text, description, or view ID.
     */
    fun clickElement(query: String): Boolean {
        val root = rootInActiveWindow ?: return false

        // Guard: Never click on sensitive/banking screens or password fields
        if (isSensitiveScreen()) {
            Log.w(TAG, "Guard blocked click on sensitive screen")
            return false
        }

        val q = query.trim().lowercase()

        var targetNode: AccessibilityNodeInfo? = null

        fun findNode(node: AccessibilityNodeInfo?) {
            if (node == null || targetNode != null) return

            val text = node.text?.toString()?.lowercase() ?: ""
            val desc = node.contentDescription?.toString()?.lowercase() ?: ""
            val viewId = node.viewIdResourceName?.lowercase() ?: ""

            if (text.contains(q) || desc.contains(q) || viewId.contains(q)) {
                // Find nearest clickable ancestor or the node itself
                var cur: AccessibilityNodeInfo? = node
                while (cur != null) {
                    if (cur.isClickable) {
                        targetNode = cur
                        return
                    }
                    cur = cur.parent
                }
                if (targetNode == null) {
                    targetNode = node
                }
                return
            }

            for (i in 0 until node.childCount) {
                findNode(node.getChild(i))
            }
        }

        findNode(root)

        if (targetNode != null) {
            val clicked = targetNode?.performAction(AccessibilityNodeInfo.ACTION_CLICK) ?: false
            if (!clicked) {
                // Fallback: Dispatch gesture tap at node bounds
                val rect = Rect()
                targetNode?.getBoundsInScreen(rect)
                if (rect.width() > 0 && rect.height() > 0) {
                    return tapCoordinate(rect.centerX().toFloat(), rect.centerY().toFloat())
                }
            }
            return clicked
        }
        return false
    }

    /**
     * Trigger camera shutter button to take a photo.
     */
    fun clickShutter(): Boolean {
        val root = rootInActiveWindow ?: return false
        val pkg = root.packageName?.toString()?.lowercase() ?: ""
        Log.d(TAG, "clickShutter called. Active package: $pkg")

        val isCameraApp = pkg.contains("camera") || pkg.contains("gallery") || pkg.contains("snap")
        if (!isCameraApp) {
            Log.d(TAG, "Foreground is not camera ($pkg), delaying shutter click")
            return false
        }

        // 1. Explicit Xiaomi / MIUI / Android Camera Shutter IDs
        val shutterViewIds = listOf(
            "shutter_button", "bottom_snap_view", "v9_shutter_button",
            "camera_snap_view", "snap_view", "btn_shutter", "shutter_view",
            "intent_done_apply", "shutter"
        )

        var shutterNode: AccessibilityNodeInfo? = null

        fun findShutter(node: AccessibilityNodeInfo?) {
            if (node == null || shutterNode != null) return

            val viewId = node.viewIdResourceName?.lowercase() ?: ""
            val desc = node.contentDescription?.toString()?.lowercase() ?: ""
            val cls = node.className?.toString()?.lowercase() ?: ""

            if (shutterViewIds.any { viewId.contains(it) }) {
                shutterNode = node
                return
            }

            if (cls.contains("camerasnapview") || cls.contains("v9shutterbutton") || cls.contains("shutterbutton")) {
                shutterNode = node
                return
            }

            val exactDescs = listOf("shutter", "capture", "take photo", "take picture", "shutter button", "camera shutter")
            if (exactDescs.any { desc == it || desc.startsWith("shutter") || desc.startsWith("capture") }) {
                shutterNode = node
                return
            }

            for (i in 0 until node.childCount) {
                findShutter(node.getChild(i))
            }
        }

        findShutter(root)

        if (shutterNode != null) {
            Log.d(TAG, "Found camera shutter node: id=${shutterNode?.viewIdResourceName}, desc=${shutterNode?.contentDescription}")
            val clicked = shutterNode?.performAction(AccessibilityNodeInfo.ACTION_CLICK) ?: false
            if (clicked) {
                return true
            }

            val rect = Rect()
            shutterNode?.getBoundsInScreen(rect)
            if (rect.width() > 0 && rect.height() > 0) {
                return tapCoordinate(rect.centerX().toFloat(), rect.centerY().toFloat())
            }
        }

        // 2. High-reliability fallback coordinate tap for Xiaomi HyperOS portrait camera
        val dm = resources.displayMetrics
        val x = dm.widthPixels * 0.5f
        val y = dm.heightPixels * 0.865f
        Log.d(TAG, "Dispatching coordinate shutter tap at: ($x, $y) for pkg: $pkg")
        return tapCoordinate(x, y)
    }

    /**
     * Scroll the current screen forward (down) or backward (up).
     */
    fun performScroll(forward: Boolean): Boolean {
        val root = rootInActiveWindow ?: return false
        var scrollableNode: AccessibilityNodeInfo? = null

        fun findScrollable(node: AccessibilityNodeInfo?) {
            if (node == null || scrollableNode != null) return
            if (node.isScrollable) {
                scrollableNode = node
                return
            }
            for (i in 0 until node.childCount) {
                findScrollable(node.getChild(i))
            }
        }

        findScrollable(root)

        val action = if (forward) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
        return scrollableNode?.performAction(action) ?: false
    }

    /**
     * Type text into an editable field (focused input, matching field hint/id, or first available).
     */
    fun inputText(text: String, fieldHintOrId: String? = null): Boolean {
        val root = rootInActiveWindow ?: return false

        // Guard: Never type text on sensitive banking/wallet/password screens
        if (isSensitiveScreen()) {
            Log.w(TAG, "inputText blocked by sensitive screen guard")
            return false
        }

        var targetField: AccessibilityNodeInfo? = null

        fun findEditable(node: AccessibilityNodeInfo?) {
            if (node == null || targetField != null) return

            // Never type into password fields
            if (node.isPassword) return

            if (node.isEditable) {
                if (fieldHintOrId.isNullOrBlank()) {
                    targetField = node
                    return
                } else {
                    val hint = node.hintText?.toString()?.lowercase() ?: ""
                    val desc = node.contentDescription?.toString()?.lowercase() ?: ""
                    val textVal = node.text?.toString()?.lowercase() ?: ""
                    val viewId = node.viewIdResourceName?.lowercase() ?: ""
                    val q = fieldHintOrId.lowercase().trim()

                    if (hint.contains(q) || desc.contains(q) || textVal.contains(q) || viewId.contains(q)) {
                        targetField = node
                        return
                    }
                }
            }

            for (i in 0 until node.childCount) {
                findEditable(node.getChild(i))
            }
        }

        // Check currently focused field first if no specific field requested
        if (fieldHintOrId.isNullOrBlank()) {
            val focused = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            if (focused != null && focused.isEditable && !focused.isPassword) {
                targetField = focused
            }
        }

        if (targetField == null) {
            findEditable(root)
        }

        if (targetField != null) {
            targetField?.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
            val args = Bundle().apply {
                putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
            }
            val ok = targetField?.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args) ?: false
            if (ok) {
                Log.d(TAG, "inputText succeeded via ACTION_SET_TEXT: '$text'")
                return true
            }

            // Fallback: tap the field to bring focus, then set text
            val rect = Rect()
            targetField?.getBoundsInScreen(rect)
            if (rect.width() > 0 && rect.height() > 0) {
                tapCoordinate(rect.centerX().toFloat(), rect.centerY().toFloat())
                try { Thread.sleep(250) } catch (_: Exception) {}
                val retryOk = targetField?.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args) ?: false
                Log.d(TAG, "inputText retry after tap: $retryOk")
                return retryOk
            }
        }
        Log.w(TAG, "inputText: No editable field found on screen for target='$fieldHintOrId'")
        return false
    }

    /**
     * Search and collect matching contact/chat names currently visible on screen.
     * Used for multiple contact ambiguity detection ("လူတူရင် စာရင်းပြပြီး အတည်ပြုပါ").
     */
    fun findMatchingContacts(query: String): List<String> {
        val root = rootInActiveWindow ?: return emptyList()
        val q = query.trim().lowercase()
        val matchedNames = mutableListOf<String>()

        fun scan(node: AccessibilityNodeInfo?) {
            if (node == null) return
            val text = node.text?.toString()?.trim() ?: ""
            val desc = node.contentDescription?.toString()?.trim() ?: ""
            val cand = if (text.isNotEmpty()) text else desc

            if (cand.isNotEmpty() && cand.length in 2..50) {
                val lower = cand.lowercase()
                val ignore = listOf("search", "ရှာရန်", "chats", "contacts", "messages", "clear", "cancel", "back", "done")
                if (!ignore.contains(lower) && lower.contains(q)) {
                    var cur: AccessibilityNodeInfo? = node
                    var isClickableRow = false
                    while (cur != null) {
                        if (cur.isClickable) {
                            isClickableRow = true
                            break
                        }
                        cur = cur.parent
                    }
                    if (isClickableRow) {
                        matchedNames.add(cand)
                    }
                }
            }

            for (i in 0 until node.childCount) {
                scan(node.getChild(i))
            }
        }

        scan(root)
        return matchedNames.distinct()
    }

    /**
     * Click the Send, Submit, or Post button in chat or messaging apps.
     * STRICT RULE: Must be a verified clickable Send node. Coordinate blind tap is disabled.
     */
    fun clickSendButton(): Boolean {
        val root = rootInActiveWindow ?: return false

        // Guard: Never click send on sensitive screens
        if (isSensitiveScreen()) {
            Log.w(TAG, "clickSendButton blocked by sensitive screen guard")
            return false
        }

        var sendNode: AccessibilityNodeInfo? = null
        val sendIdentifiers = listOf(
            "send_button", "send_btn", "btn_send", "compose_send_button",
            "action_send", "send_icon", "post_button", "btn_post"
        )
        val sendDescs = listOf("send", "send message", "post", "submit", "ပို့ရန်", "ပေးပို့ရန်")

        fun findSend(node: AccessibilityNodeInfo?) {
            if (node == null || sendNode != null) return
            val viewId = node.viewIdResourceName?.lowercase() ?: ""
            val desc = node.contentDescription?.toString()?.lowercase() ?: ""
            val text = node.text?.toString()?.lowercase() ?: ""

            val matchesSend = sendIdentifiers.any { viewId.contains(it) } ||
                sendDescs.any { desc == it || desc.startsWith("send") || desc.contains("ပို့") } ||
                text == "send" || text == "post" || text == "ပို့ရန်"

            if (matchesSend) {
                var cur: AccessibilityNodeInfo? = node
                while (cur != null) {
                    if (cur.isClickable) {
                        sendNode = cur
                        return
                    }
                    cur = cur.parent
                }
                sendNode = node
                return
            }

            for (i in 0 until node.childCount) {
                findSend(node.getChild(i))
            }
        }

        findSend(root)

        if (sendNode != null) {
            Log.d(TAG, "Found verified send button node: id=${sendNode?.viewIdResourceName}, desc=${sendNode?.contentDescription}")
            val ok = sendNode?.performAction(AccessibilityNodeInfo.ACTION_CLICK) ?: false
            if (ok) return true

            // If performAction returned false, click the verified node bounds directly
            val rect = Rect()
            sendNode?.getBoundsInScreen(rect)
            if (rect.width() > 0 && rect.height() > 0) {
                return tapCoordinate(rect.centerX().toFloat(), rect.centerY().toFloat())
            }
        }

        // Blind coordinate tap is strictly disabled per safety instructions!
        Log.w(TAG, "Verified send button node NOT found on screen. Blind coordinate tap is disabled.")
        return false
    }

    /**
     * Perform global system navigation actions: back, home, recents, notifications.
     */
    fun performGlobal(action: String): Boolean {
        return when (action.lowercase().trim()) {
            "back" -> performGlobalAction(GLOBAL_ACTION_BACK)
            "home" -> performGlobalAction(GLOBAL_ACTION_HOME)
            "recents" -> performGlobalAction(GLOBAL_ACTION_RECENTS)
            "notifications" -> performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)
            else -> false
        }
    }

    /**
     * Dispatch a low-level tap gesture at screen coordinates.
     */
    fun tapCoordinate(x: Float, y: Float): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            val path = Path().apply {
                moveTo(x, y)
            }
            val stroke = GestureDescription.StrokeDescription(path, 0, 50)
            val gesture = GestureDescription.Builder().addStroke(stroke).build()
            return dispatchGesture(gesture, null, null)
        }
        return false
    }
}
