package com.animan.extensions.probe

class ProbeActivity : android.app.Activity() {
    override fun onCreate(state: android.os.Bundle?) {
        super.onCreate(state)
        setContentView(android.widget.TextView(this).apply { text = "AnimeLab APK instrumentation" })
    }
}
